"""알림 목록 · nav 드롭다운/배지(HTMX) · 모두 읽음 · 알림 열기."""

import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from apps.accounts.decorators import login_required

from . import selectors, services
from .models import Notification

PAGE_SIZE = 20


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _safe_url(request, url, fallback):
    """같은 사이트 경로일 때만 그대로 쓰고, 아니면 fallback."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return fallback


def _render_dropdown(request, toast=None):
    """드롭다운 패널 + (OOB) nav 배지를 함께 돌려준다."""
    unread = services.unread_count(request.user)
    response = render(
        request,
        "notifications/partials/dropdown.html",
        {
            "notifications": selectors.recent_notifications(request.user),
            "unread": unread,
            "oob_badge": True,
            "count": unread,
        },
    )
    if toast:
        response["HX-Trigger"] = json.dumps({"showToast": {"message": toast, "level": "success"}})  # ASCII 이스케이프 (헤더는 latin-1)
    return response


@login_required
@require_GET
def notification_list(request):
    """알림 전체/안 읽음 목록 (페이지네이션)."""
    current = "unread" if request.GET.get("filter") == "unread" else "all"
    qs = selectors.notifications_for(request.user, unread_only=current == "unread")
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "notifications/notification_list.html",
        {
            "page_obj": page_obj,
            "counts": selectors.notification_counts(request.user),
            "current_filter": current,
        },
    )


@never_cache
@login_required
@require_GET
def dropdown(request):
    """nav 알림 드롭다운 내용 (최근 10개). HTMX 가 아니면 목록 페이지로."""
    if not _is_htmx(request):
        return redirect("notifications:list")
    return _render_dropdown(request)


@login_required
@require_POST
def read_all(request):
    """모든 알림 읽음 처리. 드롭다운(HTMX)에서는 패널을 다시 그려준다."""
    changed = services.mark_all_read(request.user)
    message = "알림을 모두 읽었어요." if changed else "새 알림이 없어요."
    if _is_htmx(request):
        return _render_dropdown(request, toast=message)
    messages.success(request, message)
    return redirect(_safe_url(request, request.POST.get("next"), reverse("notifications:list")))


@login_required
@require_GET
def go(request, pk):
    """알림을 읽음 처리하고 알림의 URL 로 이동한다 (내 알림만, 아니면 404)."""
    notification = get_object_or_404(Notification, pk=pk, user=request.user)
    services.mark_read(notification)
    return redirect(_safe_url(request, notification.url, reverse("notifications:list")))


@never_cache
@require_GET
def badge(request):
    """nav 배지 (30초 polling). 로그인이 풀렸으면 로그인으로 보내지 않고 비워 둔다."""
    if not request.user.is_authenticated:
        return HttpResponse("")
    return render(request, "notifications/partials/badge.html", {"count": services.unread_count(request.user)})
