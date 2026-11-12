"""채팅 서비스 (쓰기 · 비즈니스 로직).

뷰와 WebSocket consumer 는 이 모듈만 통해 채팅방/메시지를 만들고 읽음 처리한다.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import ChatMessage, ChatRoom

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 1000
NOTIFY_PREVIEW_LENGTH = 40


class ChatError(Exception):
    """사용자에게 그대로 보여줄 수 있는 채팅 오류."""


# ───────────────────────── 조회성 헬퍼 ─────────────────────────


def unread_chat_count(user) -> int:
    """내가 참여한 채팅방에서 상대가 보낸 안 읽은 메시지 총 개수."""
    if not getattr(user, "is_authenticated", False):
        return 0
    return (
        ChatMessage.objects.filter(Q(room__seller=user) | Q(room__buyer=user), is_read=False)
        .exclude(sender=user)
        .count()
    )


def room_group_name(room_id) -> str:
    """채널 레이어 그룹 이름 (방 하나 = 그룹 하나)."""
    return f"chat_room_{room_id}"


def _display_name(user) -> str:
    # 순환 import 방지를 위해 지연 import
    from apps.core.templatetags.poly_tags import display_name

    return display_name(user)


def message_flags(content: str) -> dict:
    """메시지 본문에 대한 협상 여부 · 사기 의심 규칙 결과. AI 서비스 오류는 무시한다."""
    from apps.ai.services.fraud import check_text_rules
    from apps.ai.services.negotiation import detect_negotiation

    try:
        is_negotiation = bool(detect_negotiation(content))
    except Exception:  # noqa: BLE001 - 보조 기능이 채팅을 막으면 안 됨
        logger.exception("detect_negotiation 실패")
        is_negotiation = False
    try:
        warnings = list(check_text_rules(content) or [])
    except Exception:  # noqa: BLE001
        logger.exception("check_text_rules 실패")
        warnings = []
    return {"is_negotiation": is_negotiation, "fraud_warnings": warnings}


def serialize_message(message: ChatMessage, flags: dict | None = None) -> dict:
    """WebSocket 으로 보내는 메시지 payload."""
    flags = flags if flags is not None else message_flags(message.content)
    return {
        "id": message.pk,
        "content": message.content,
        "sender_id": message.sender_id,
        "sender_name": _display_name(message.sender),
        "created_at": timezone.localtime(message.created_at).isoformat(),
        "is_read": message.is_read,
        "is_negotiation": flags["is_negotiation"],
        "fraud_warnings": flags["fraud_warnings"],
    }


# ───────────────────────── 채팅방 ─────────────────────────


def get_or_create_room(product, buyer) -> tuple[ChatRoom, bool]:
    """상품에 대한 (buyer 기준) 채팅방을 찾거나 만든다. (room, created) 반환.

    - 내 상품에는 채팅할 수 없다.
    - 차단 관계면 채팅할 수 없다.
    - 거래완료 상품은 기존 방만 열 수 있다.
    """
    from apps.moderation.services import is_blocked_between

    if product.seller_id == buyer.pk:
        raise ChatError("내 상품에는 채팅할 수 없어요.")
    if is_blocked_between(buyer, product.seller):
        raise ChatError("차단한(또는 나를 차단한) 사용자와는 채팅할 수 없어요.")

    existing = ChatRoom.objects.filter(product=product, buyer=buyer).first()
    if existing:
        return existing, False
    if product.status == product.Status.SOLD:
        raise ChatError("거래가 끝난 상품이라 새 채팅을 시작할 수 없어요.")

    try:
        with transaction.atomic():
            room = ChatRoom.objects.create(product=product, seller_id=product.seller_id, buyer=buyer)
    except IntegrityError:  # 동시에 두 번 눌렀을 때
        return ChatRoom.objects.get(product=product, buyer=buyer), False
    return room, True


# ───────────────────────── 메시지 ─────────────────────────


def send_message(room: ChatRoom, sender, content: str) -> ChatMessage:
    """메시지를 저장하고 방의 마지막 메시지 시각 갱신 + 상대에게 알림을 보낸다.

    실패(참여자 아님, 빈 메시지, 너무 김, 차단)는 ChatError.
    브로드캐스트는 호출하는 쪽(consumer/view)이 broadcast_message 로 한다.
    """
    from apps.moderation.services import is_blocked_between
    from apps.notifications.models import Notification
    from apps.notifications.services import notify

    if not room.has_member(sender):
        raise ChatError("이 채팅방에 참여하고 있지 않아요.")
    content = (content or "").strip()
    if not content:
        raise ChatError("메시지를 입력해 주세요.")
    if len(content) > MAX_MESSAGE_LENGTH:
        raise ChatError(f"메시지는 {MAX_MESSAGE_LENGTH:,}자까지 보낼 수 있어요.")

    other = room.other_user(sender)
    if is_blocked_between(sender, other):
        raise ChatError("차단한(또는 나를 차단한) 사용자에게는 메시지를 보낼 수 없어요.")

    with transaction.atomic():
        message = ChatMessage.objects.create(room=room, sender=sender, content=content)
        room.last_message_at = message.created_at
        ChatRoom.objects.filter(pk=room.pk).update(last_message_at=message.created_at)

        preview = content if len(content) <= NOTIFY_PREVIEW_LENGTH else content[:NOTIFY_PREVIEW_LENGTH] + "…"
        # 같은 방의 안 읽은 새 메시지 알림은 하나로 합친다
        notify(
            other,
            Notification.Kind.NEW_MESSAGE,
            f"{_display_name(sender)}님: {preview}",
            url=reverse("chat:room", args=[room.pk]),
            collapse_key=room.pk,
        )
    return message


def mark_room_read(room: ChatRoom, reader) -> list[int]:
    """reader 가 받은(상대가 보낸) 안 읽은 메시지를 읽음 처리하고 그 id 목록을 반환."""
    if not room.has_member(reader):
        return []
    qs = ChatMessage.objects.filter(room=room, is_read=False).exclude(sender=reader)
    ids = list(qs.values_list("pk", flat=True))
    if ids:
        ChatMessage.objects.filter(pk__in=ids).update(is_read=True, read_at=timezone.now())
    return ids


# ───────────────────────── 실시간 브로드캐스트 ─────────────────────────


def _group_send(room_id, event: dict) -> None:
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(room_group_name(room_id), event)
    except Exception:  # noqa: BLE001 - 실시간 전송 실패가 저장을 막으면 안 됨
        logger.exception("채널 레이어 전송 실패 (room=%s)", room_id)


def broadcast_message(message: ChatMessage, flags: dict | None = None) -> dict:
    """방 참여자들의 WebSocket 으로 새 메시지를 보낸다. payload 반환."""
    payload = serialize_message(message, flags)
    _group_send(message.room_id, {"type": "chat.message", "message": payload})
    return payload


def broadcast_read(room_id, reader_id, message_ids: list[int]) -> None:
    """읽음 이벤트를 방에 알린다 (보낸 사람 화면에 '읽음' 표시용)."""
    if not message_ids:
        return
    _group_send(room_id, {"type": "chat.read", "reader_id": reader_id, "message_ids": list(message_ids)})
