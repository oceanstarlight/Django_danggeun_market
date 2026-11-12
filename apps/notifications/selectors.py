"""알림 조회 전용 함수."""

from django.db.models import Count, Q

from .models import Notification

DROPDOWN_LIMIT = 10


def notifications_for(user, unread_only=False):
    """user 의 알림 (최신순)."""
    qs = Notification.objects.filter(user=user)
    if unread_only:
        qs = qs.filter(is_read=False)
    return qs.order_by("-created_at", "-pk")


def recent_notifications(user, limit=DROPDOWN_LIMIT):
    """nav 드롭다운에 보여줄 최근 알림."""
    return list(notifications_for(user)[:limit])


def notification_counts(user) -> dict:
    """{'all': 전체 수, 'unread': 안 읽은 수} 를 쿼리 한 번으로."""
    agg = Notification.objects.filter(user=user).aggregate(
        all=Count("pk"), unread=Count("pk", filter=Q(is_read=False))
    )
    return {"all": agg["all"] or 0, "unread": agg["unread"] or 0}
