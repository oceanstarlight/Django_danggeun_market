"""폴리마켓 공용 템플릿 필터/태그.

사용: {% load poly_tags %}
  {{ product.price|price }}          → "15,000원" / "나눔"
  {{ product.created_at|timeago }}   → "3분 전"
  {{ user|display_name }}            → 닉네임 우선
  {% querystring page=2 %}           → "?q=...&page=2"
  {{ product.status|status_class }}  → "badge-selling"
"""

from datetime import datetime

from django import template
from django.utils import timezone

register = template.Library()


@register.filter
def price(value):
    """정수 가격을 '15,000원' 형태로. 0 은 '나눔'."""
    if value is None or value == "":
        return ""
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return value
    if amount == 0:
        return "나눔"
    return f"{amount:,}원"


@register.filter
def timeago(value, now=None):
    """한국어 상대 시간. 7일이 넘으면 '2026.10.01' 형식."""
    if not value:
        return ""
    if not isinstance(value, datetime):
        # date 객체 등은 날짜로만 표시
        try:
            return value.strftime("%Y.%m.%d")
        except AttributeError:
            return value
    now = now or timezone.now()
    if timezone.is_naive(value) and timezone.is_aware(now):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    diff = now - value
    seconds = int(diff.total_seconds())
    if seconds < 60:
        return "방금 전"
    if seconds < 3600:
        return f"{seconds // 60}분 전"
    if seconds < 86400:
        return f"{seconds // 3600}시간 전"
    local_value = timezone.localtime(value) if timezone.is_aware(value) else value
    local_now = timezone.localtime(now) if timezone.is_aware(now) else now
    day_diff = (local_now.date() - local_value.date()).days
    if day_diff <= 1:
        return "어제"
    if day_diff < 7:
        return f"{day_diff}일 전"
    return local_value.strftime("%Y.%m.%d")


@register.filter
def display_name(user):
    """프로필 닉네임이 있으면 닉네임, 없으면 username."""
    if not user:
        return ""
    if not getattr(user, "is_authenticated", True) and not getattr(user, "pk", None):
        return "알 수 없음"
    try:
        nickname = user.profile.nickname
    except Exception:  # noqa: BLE001 - 프로필이 없는 사용자(관리자 등)
        nickname = ""
    return nickname or getattr(user, "username", "") or str(user)


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    """현재 GET 파라미터를 유지하면서 일부만 바꾼 쿼리스트링('?a=1&b=2')을 돌려준다.

    값이 None 이거나 "" 이면 해당 키를 제거한다.
    예: <a href="{% querystring page=page_obj.next_page_number %}">
    """
    request = context.get("request")
    params = request.GET.copy() if request is not None else None
    if params is None:
        from django.http import QueryDict

        params = QueryDict(mutable=True)
    for key, value in kwargs.items():
        if value is None or value == "":
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else "?"


_STATUS_CLASSES = {
    "SELLING": "badge-selling",
    "RESERVED": "badge-reserved",
    "SOLD": "badge-sold",
}


@register.filter
def status_class(status):
    """Product.status 값 → 배지 CSS 클래스."""
    return _STATUS_CLASSES.get(str(status or "").upper(), "badge-neutral")

