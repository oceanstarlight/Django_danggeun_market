"""채팅 조회 (목록 · 방 · 메시지). N+1 을 피하도록 select/prefetch/annotate 를 모아 둔다."""

from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404

from apps.products.models import ProductImage

from .models import ChatMessage, ChatRoom

ROOM_MESSAGES_PAGE = 50

LIST_FILTERS = ("all", "selling", "buying", "unread")


def _images_prefetch():
    return Prefetch("product__images", queryset=ProductImage.objects.order_by("order", "id"))


def rooms_for_user(user, filter_key="all"):
    """채팅 목록: 마지막 메시지 순 + 상대/상품 정보 + 마지막 메시지 미리보기 + 안읽음 수.

    상대가 만들기만 하고 대화가 없는 방(내가 판매자)은 숨긴다.
    """
    last = ChatMessage.objects.filter(room=OuterRef("pk")).order_by("-created_at", "-pk")
    qs = (
        ChatRoom.objects.filter(Q(seller=user) | Q(buyer=user))
        .filter(Q(last_message_at__isnull=False) | Q(buyer=user))
        .select_related(
            "product",
            "product__region",
            "seller",
            "seller__profile",
            "seller__profile__region",
            "buyer",
            "buyer__profile",
            "buyer__profile__region",
        )
        .prefetch_related(_images_prefetch())
        .annotate(
            unread=Count("messages", filter=Q(messages__is_read=False) & ~Q(messages__sender=user)),
            last_message_content=Subquery(last.values("content")[:1]),
            last_message_sender_id=Subquery(last.values("sender_id")[:1]),
        )
        .order_by(F("last_message_at").desc(nulls_last=True), "-created_at")
    )
    if filter_key == "selling":
        qs = qs.filter(seller=user)
    elif filter_key == "buying":
        qs = qs.filter(buyer=user)
    elif filter_key == "unread":
        qs = qs.filter(unread__gt=0)
    return qs


def list_counts(user) -> dict:
    """목록 탭 숫자 (전체/판매/구매/안읽음 방 개수) — 쿼리 1번."""
    rows = (
        ChatRoom.objects.filter(Q(seller=user) | Q(buyer=user))
        .filter(Q(last_message_at__isnull=False) | Q(buyer=user))
        .annotate(unread=Count("messages", filter=Q(messages__is_read=False) & ~Q(messages__sender=user)))
        .values_list("seller_id", "unread")
    )
    counts = {"all": 0, "selling": 0, "buying": 0, "unread": 0}
    for seller_id, unread in rows:
        counts["all"] += 1
        counts["selling" if seller_id == user.pk else "buying"] += 1
        if unread:
            counts["unread"] += 1
    return counts


def get_room_for_member(room_id, user) -> ChatRoom:
    """방 + 상품/참여자 정보. 없으면 404, 참여자가 아니면 403."""
    room = get_object_or_404(
        ChatRoom.objects.select_related(
            "product",
            "product__region",
            "product__buyer",
            "seller",
            "seller__profile",
            "seller__profile__region",
            "buyer",
            "buyer__profile",
            "buyer__profile__region",
        ).prefetch_related(_images_prefetch()),
        pk=room_id,
    )
    if not room.has_member(user):
        raise PermissionDenied("이 채팅방에 참여하고 있지 않아요.")
    return room


def room_messages(room, before_id=None, limit=ROOM_MESSAGES_PAGE):
    """최근 메시지 limit 개(오래된 → 최신 순)와 더 이전 메시지가 있는지 여부."""
    qs = ChatMessage.objects.filter(room=room).select_related("sender", "sender__profile")
    if before_id:
        # (created_at, pk) 기준 커서 — id 순서와 시간 순서가 달라도 안전
        ref = ChatMessage.objects.filter(room=room, pk=before_id).values_list("created_at", flat=True).first()
        if ref is None:
            return [], False
        qs = qs.filter(Q(created_at__lt=ref) | Q(created_at=ref, pk__lt=before_id))
    chunk = list(qs.order_by("-created_at", "-pk")[: limit + 1])
    has_more = len(chunk) > limit
    chunk = chunk[:limit]
    chunk.reverse()
    return chunk, has_more


def room_messages_after(room, after_id, limit=200):
    """after_id 이후 메시지 (재연결 시 놓친 메시지 보충용)."""
    ref = ChatMessage.objects.filter(room=room, pk=after_id).values_list("created_at", flat=True).first()
    qs = ChatMessage.objects.filter(room=room)
    if ref is not None:
        qs = qs.filter(Q(created_at__gt=ref) | Q(created_at=ref, pk__gt=after_id))
    elif after_id:
        qs = qs.filter(pk__gt=after_id)
    return list(qs.select_related("sender", "sender__profile").order_by("created_at", "pk")[:limit])
