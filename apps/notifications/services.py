"""알림 서비스 (다른 앱은 이 함수들만 사용)."""

from django.db import transaction
from django.utils import timezone

from .models import Notification


def notify(user, kind, message, url="", collapse_key=None):
    """알림을 만든다.

    collapse_key 가 있으면 같은 user/kind/url 의 '안 읽은' 알림이 있을 때
    새로 만들지 않고 내용과 시각만 갱신한다 (예: 같은 채팅방 새 메시지).
    """
    message = (message or "")[:200]
    url = (url or "")[:300]
    if user is None or not getattr(user, "pk", None):
        return None

    if collapse_key is not None:
        with transaction.atomic():
            existing = (
                Notification.objects.select_for_update()
                .filter(user=user, kind=kind, url=url, is_read=False)
                .order_by("-created_at")
                .first()
            )
            if existing:
                existing.message = message
                existing.created_at = timezone.now()  # 목록 맨 위로 올리기
                existing.save(update_fields=["message", "created_at"])
                return existing

    return Notification.objects.create(user=user, kind=kind, message=message, url=url)


def unread_count(user) -> int:
    """안 읽은 알림 수."""
    if not getattr(user, "is_authenticated", False):
        return 0
    return Notification.objects.filter(user=user, is_read=False).count()


def mark_all_read(user) -> int:
    """모든 알림 읽음 처리. 변경된 개수를 반환."""
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)


def mark_read(notification):
    """알림 하나 읽음 처리."""
    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
    return notification
