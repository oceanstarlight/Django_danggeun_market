from django.urls import path

from apps.products import views as product_views

from . import views

app_name = "core"

urlpatterns = [
    # 홈 화면 뷰는 products 앱이 소유
    path("", product_views.home, name="home"),
    path("state/", views.health, name="health"),
    # 개발용 스타일가이드: 뷰가 DEBUG=False 면 404 를 돌려준다
    path("dev/styleguide/", views.styleguide, name="styleguide"),
]
