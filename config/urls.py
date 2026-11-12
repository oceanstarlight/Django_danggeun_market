"""루트 URL 설정. 각 앱은 namespace(app_name)로 include 한다."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    # accounts 는 /accounts/... 와 /users/<username>/ 두 prefix 를 쓰므로 루트에 include
    # (prefix 는 apps/accounts/urls.py 안에 직접 적혀 있음)
    path("", include("apps.accounts.urls")),
    path("products/", include("apps.products.urls")),
    path("chats/", include("apps.chat.urls")),
    path("trades/", include("apps.trades.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("moderation/", include("apps.moderation.urls")),
    path("ai/", include("apps.ai.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
