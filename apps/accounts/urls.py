from django.urls import path

from . import views

app_name = "accounts"

# config/urls.py 에서 prefix 없이 include 하므로 경로에 prefix 를 직접 적는다.
urlpatterns = [
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/signup/check/", views.check_duplicate, name="check_duplicate"),  # HTMX 중복 확인
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),  # POST
    path("accounts/me/", views.mypage, name="mypage"),
    path("accounts/me/edit/", views.profile_edit, name="profile_edit"),
    path("users/<str:username>/", views.seller_profile, name="seller_profile"),
]
