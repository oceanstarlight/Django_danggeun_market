"""HTMX 요청까지 고려한 로그인 필수 데코레이터."""

from functools import wraps
from urllib.parse import urlparse

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse
from django.shortcuts import resolve_url
from django.conf import settings
from django.utils.http import urlencode


def login_required(view_func):
    """비로그인 시 일반 요청은 로그인 페이지로, HTMX 요청은 HX-Redirect 로 보낸다."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        if request.headers.get("HX-Request"):
            # 조각 요청이면 사용자가 보고 있던 페이지로 돌아오게
            current = request.headers.get("HX-Current-URL", "")
            parsed = urlparse(current)
            next_url = (parsed.path + (f"?{parsed.query}" if parsed.query else "")) if parsed.path else request.path
            response = HttpResponse(status=200)
            response["HX-Redirect"] = f"{resolve_url(settings.LOGIN_URL)}?{urlencode({'next': next_url})}"
            return response
        return redirect_to_login(request.get_full_path())

    return wrapper
