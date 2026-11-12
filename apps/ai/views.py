"""AI 기능 뷰 (요청 파싱 · 권한 · 응답만; AI 호출은 apps.ai.services 를 통해서).

모든 결과는 HTML 조각(partial)으로 돌려준다.
- 실패하면 ai/partials/error.html 로 친절한 안내 (HTMX 요청이면 200 으로 줘야 화면에 들어감)
- 상품 폼(describe/recognize)은 static/js/ai.js 가 fetch 로 호출하고, 협상/사기 재분석은 HTMX
"""

from __future__ import annotations

import json
import logging
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.chat.models import ChatMessage
from apps.products.models import Category, Product

from .client import AIServiceError, AIUnavailableError
from .images import AIInputError, prepare_uploaded_images
from .services import description, fraud, negotiation, vision

logger = logging.getLogger(__name__)


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _flag(request, name: str) -> bool:
    return request.POST.get(name, "").lower() in {"1", "true", "on", "yes"}


def _error(request, exc: AIServiceError, *, hint: str = ""):
    """실패 안내 조각. HTMX 는 4xx/5xx 를 화면에 넣지 않으므로 200 으로 돌려준다."""
    if isinstance(exc, AIInputError):
        status, title = 400, "입력을 확인해 주세요"
    elif isinstance(exc, AIUnavailableError):
        status, title = 503, "AI 도우미를 쓸 수 없어요"
    else:
        status, title = 502, "AI 도우미가 잠시 쉬고 있어요"
    context = {"title": title, "message": exc.user_message, "hint": hint}
    return render(request, "ai/partials/error.html", context, status=200 if _is_htmx(request) else status)


def _category_from(value: str | None):
    """폼의 category 값(pk 또는 slug) → Category | None."""
    value = (value or "").strip()
    if not value:
        return None
    lookup = {"pk": int(value)} if value.isdigit() else {"slug": value}
    return Category.objects.filter(**lookup).first()


# ───────────────────────── (1) 상품 설명 생성 ─────────────────────────


@login_required
@require_POST
def describe(request):
    """사진 1~2장 + 키워드(+카테고리) → 판매글 초안 카드."""
    hint = "AI 없이도 직접 입력해서 등록할 수 있어요."
    try:
        images = prepare_uploaded_images(request.FILES.getlist("images"), max_count=2, required=False)
        result = description.generate_description(
            images,
            request.POST.get("keywords", ""),
            _category_from(request.POST.get("category")),
            user=request.user,
            regenerate=_flag(request, "regenerate"),
        )
    except AIServiceError as exc:
        return _error(request, exc, hint=hint)
    context = {"result": result.data, "cached": result.cached, "uid": secrets.token_hex(4)}
    return render(request, "ai/partials/description_result.html", context)


# ───────────────────────── (2) 사진 인식 ─────────────────────────


@login_required
@require_POST
def recognize(request):
    """사진 → 카테고리/상태/제목 추천 카드."""
    try:
        images = prepare_uploaded_images(request.FILES.getlist("images"), max_count=2, required=True)
        result = vision.recognize_product(images, user=request.user, regenerate=_flag(request, "regenerate"))
    except AIServiceError as exc:
        return _error(request, exc, hint="카테고리와 상품 상태는 직접 골라도 돼요.")
    context = {
        "result": result.data,
        "cached": result.cached,
        "uid": secrets.token_hex(4),
        "low_confidence": result.data["confidence"] < 0.5,
    }
    return render(request, "ai/partials/recognize_result.html", context)


# ───────────────────────── (4) 가격 협상 답장 초안 ─────────────────────────


@login_required
@require_POST
def negotiate(request, message_id):
    """판매자만: 구매자 협상 메시지 → 답장 초안 3개."""
    message = get_object_or_404(
        ChatMessage.objects.select_related("room", "room__product"), pk=message_id
    )
    room = message.room
    if not room.has_member(request.user):
        raise Http404("채팅방을 찾을 수 없어요.")
    if request.user.pk != room.seller_id:
        raise PermissionDenied("판매자만 답장 초안을 만들 수 있어요.")
    if message.sender_id == room.seller_id:
        return _error(request, AIInputError("구매자가 보낸 메시지에만 답장 초안을 만들 수 있어요."))
    try:
        result = negotiation.generate_drafts(message, user=request.user, regenerate=_flag(request, "regenerate"))
    except AIServiceError as exc:
        return _error(request, exc, hint="직접 답장을 보내도 괜찮아요.")
    context = {
        "message": message,
        "drafts": result.data["drafts"],
        "offered_price": result.data.get("offered_price"),
        "cached": result.cached,
    }
    return render(request, "ai/partials/negotiation_drafts.html", context)


# ───────────────────────── (3) 사기 탐지 재분석 ─────────────────────────


@login_required
@require_POST
def fraud_refresh(request, product_id):
    """판매자/스태프: 상품 사기 위험 다시 분석."""
    product = get_object_or_404(Product.objects.select_related("seller", "category"), pk=product_id)
    if not (request.user.pk == product.seller_id or request.user.is_staff):
        raise PermissionDenied("판매자만 다시 분석할 수 있어요.")

    analysis = fraud.analyze_product(product, force=True, user=request.user)
    if analysis is None or not analysis.is_warning:
        text, level = "다시 확인해 보니 의심 신호가 없어요.", "success"
    elif analysis.source == analysis.Source.RULE:
        text, level = "규칙 검사로 다시 확인했어요. AI 분석은 잠시 후 다시 시도해 주세요.", "warning"
    else:
        text, level = "다시 분석했어요. 표시된 문구를 확인해 주세요.", "info"

    if _is_htmx(request):
        response = render(
            request, "ai/partials/fraud_banner.html", {"analysis": analysis, "product": product}
        )
        response["HX-Trigger"] = json.dumps({"showToast": {"message": text, "level": level}})  # 헤더는 ASCII 로
        return response
    getattr(messages, level)(request, text)
    return redirect("products:detail", pk=product.pk)
