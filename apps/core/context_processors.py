"""모든 템플릿에서 쓰는 nav 컨텍스트."""

import logging

from django.db import DatabaseError

logger = logging.getLogger(__name__)


def nav(request):
    """nav_unread_notifications, nav_unread_chats, nav_categories 를 제공한다."""
    from apps.chat.services import unread_chat_count
    from apps.notifications.services import unread_count
    from apps.products.models import Category

    user = getattr(request, "user", None)
    unread_notifications = 0
    unread_chats = 0
    if user is not None and user.is_authenticated:
        try:
            unread_notifications = unread_count(user)
            unread_chats = unread_chat_count(user)
        except DatabaseError:  # nav 때문에 페이지 전체가 깨지지 않게
            logger.exception("nav 배지 조회 실패")

    return {
        "nav_unread_notifications": unread_notifications,
        "nav_unread_chats": unread_chats,
        # 지연 평가 QuerySet: 템플릿에서 실제로 쓸 때만 조회
        "nav_categories": Category.objects.all(),
    }
