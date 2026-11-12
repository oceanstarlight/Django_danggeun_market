"""신고 / 차단 뷰.

- 신고 폼은 일반 페이지와 HTMX 모달(조각) 둘 다 지원해요.
  HTMX GET/POST → moderation/partials/report_form.html (성공 시 report_done.html + 토스트)
- 차단 토글은 POST 전용. HTMX 요청이면 버튼 조각을, 아니면 next 로 리다이렉트해요.
"""

import json

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import login_required
from apps.core.templatetags.poly_tags import display_name
from apps.products.models import Product

from . import services
from .forms import ReportForm
from .models import Block

User = get_user_model()


def _toast(response, message, level="success"):
    response["HX-Trigger"] = json.dumps({"showToast": {"message": message, "level": level}})
    return response


def _safe_next(request, fallback):
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return target
    return resolve_url(fallback)


def _report(request, *, target_label, back_url, action_url, product=None, reported_user=None):
    """상품/사용자 신고 공통 처리."""
    htmx = bool(request.headers.get("HX-Request"))
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_report(
                request.user,
                reason=form.cleaned_data["reason"],
                detail=form.cleaned_data["detail"],
                product=product,
                reported_user=reported_user,
            )
        except services.ModerationError as exc:
            form.add_error(None, str(exc))
        else:
            done = "신고를 접수했어요. 운영팀이 꼼꼼히 확인할게요."
            if htmx:
                response = render(request, "moderation/partials/report_done.html", {"back_url": back_url})
                return _toast(response, done)
            messages.success(request, done)
            return redirect(back_url)

    context = {
        "form": form,
        "target_label": target_label,
        "back_url": back_url,
        "action_url": action_url,
        "product": product,
        "reported_user": reported_user,
    }
    template = "moderation/partials/report_form.html" if htmx else "moderation/report_form.html"
    return render(request, template, context)


@login_required
@require_http_methods(["GET", "POST"])
def report_product(request, pk):
    product = get_object_or_404(Product.objects.select_related("seller__profile"), pk=pk)
    if product.seller_id == request.user.pk:
        raise PermissionDenied("내 상품은 신고할 수 없어요.")
    return _report(
        request,
        target_label=product.title,
        back_url=resolve_url("products:detail", product.pk),
        action_url=resolve_url("moderation:report_product", product.pk),
        product=product,
    )


@login_required
@require_http_methods(["GET", "POST"])
def report_user(request, username):
    target = get_object_or_404(User.objects.select_related("profile"), username=username, is_active=True)
    if target.pk == request.user.pk:
        raise PermissionDenied("나 자신은 신고할 수 없어요.")
    return _report(
        request,
        target_label=f"{display_name(target)}님",
        back_url=resolve_url("accounts:seller_profile", target.username),
        action_url=resolve_url("moderation:report_user", target.username),
        reported_user=target,
    )


@login_required
@require_POST
def block_toggle(request, username):
    target = get_object_or_404(User.objects.select_related("profile"), username=username, is_active=True)
    if target.pk == request.user.pk:
        raise PermissionDenied("나 자신은 차단할 수 없어요.")

    now_blocked = services.toggle_block(request.user, target)
    name = display_name(target)
    if now_blocked:
        text = f"{name}님을 차단했어요. 서로의 상품과 채팅이 보이지 않아요."
    else:
        text = f"{name}님 차단을 해제했어요."

    if request.headers.get("HX-Request"):
        response = render(
            request,
            "moderation/partials/block_button.html",
            {"target": target, "is_blocked": now_blocked, "next": request.POST.get("next", "")},
        )
        return _toast(response, text, "success" if not now_blocked else "info")
    level = messages.INFO if now_blocked else messages.SUCCESS
    messages.add_message(request, level, text)
    return redirect(_safe_next(request, resolve_url("accounts:seller_profile", target.username)))


@login_required
@require_GET
def block_list(request):
    blocks = (
        Block.objects.filter(blocker=request.user)
        .select_related("blocked__profile__region")
        .order_by("-created_at")
    )
    page_obj = Paginator(blocks, 20).get_page(request.GET.get("page"))
    return render(request, "moderation/block_list.html", {"page_obj": page_obj})
