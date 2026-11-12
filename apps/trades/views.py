"""거래완료 처리 · 거래 후기 작성 뷰."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import login_required
from apps.products.models import Product

from . import selectors, services
from .forms import ReviewForm

User = get_user_model()

# 구매자 선택지에서 '채팅 밖에서 거래했어요' 값
NO_BUYER = "none"


def _get_product(product_id):
    return get_object_or_404(
        Product.objects.select_related("seller__profile", "buyer__profile", "category", "region").prefetch_related(
            "images"
        ),
        pk=product_id,
    )


@login_required
@require_http_methods(["GET", "POST"])
def complete(request, product_id):
    """판매자가 채팅한 이웃 중 구매자를 골라 거래완료로 바꾼다."""
    product = _get_product(product_id)
    if product.seller_id != request.user.pk:
        raise PermissionDenied("내 상품만 거래완료로 바꿀 수 있어요.")
    if product.status == Product.Status.SOLD:
        messages.info(request, "이미 거래완료된 상품이에요.")
        return redirect("products:detail", pk=product.pk)

    partners = list(selectors.chat_partners(product))
    partner_ids = {room.buyer_id for room in partners}
    error = None

    if request.method == "POST":
        choice = request.POST.get("buyer", "").strip()
        buyer = None
        if not choice:
            error = "거래한 이웃을 선택해 주세요."
        elif choice != NO_BUYER:
            buyer_id = int(choice) if choice.isdigit() else None
            if buyer_id not in partner_ids:
                error = "이 상품으로 채팅한 이웃 중에서 선택해 주세요."
            else:
                buyer = next(room.buyer for room in partners if room.buyer_id == buyer_id)
        if error is None:
            try:
                services.complete_trade(product, request.user, buyer)
            except services.TradeError as exc:
                error = str(exc)
            else:
                if buyer is not None:
                    messages.success(request, "거래완료로 바꿨어요. 거래 후기를 남겨 주세요.")
                    return redirect("trades:review_create", product_id=product.pk)
                messages.success(request, "거래완료로 바꿨어요.")
                return redirect("products:detail", pk=product.pk)
        selected = choice
    else:
        # 채팅방의 '거래완료' 버튼에서 ?buyer=<id> 로 미리 선택해 올 수 있다
        selected = request.GET.get("buyer", "")
        if not (selected.isdigit() and int(selected) in partner_ids):
            selected = str(partners[0].buyer_id) if len(partners) == 1 else ""

    status = 400 if error else 200
    return render(
        request,
        "trades/complete.html",
        {
            "product": product,
            "partners": partners,
            "selected": selected,
            "no_buyer": NO_BUYER,
            "error": error,
        },
        status=status,
    )


@login_required
@require_http_methods(["GET", "POST"])
def review_create(request, product_id):
    """거래 당사자가 상대에게 후기(별점 + 매너 태그 + 내용)를 남긴다."""
    product = _get_product(product_id)
    if not services.is_participant(product, request.user):
        raise PermissionDenied("거래한 당사자만 후기를 남길 수 있어요.")

    reason = services.review_block_reason(product, request.user)
    if reason:
        messages.info(request, reason)
        return redirect("products:detail", pk=product.pk)

    reviewee = services.review_target(product, request.user)
    reviewee_is_seller = reviewee.pk == product.seller_id
    form = ReviewForm(request.POST or None, reviewee_is_seller=reviewee_is_seller)

    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            try:
                services.create_review(
                    product,
                    request.user,
                    rating=data["rating"],
                    manner_tags=data["manner_tags"],
                    content=data["content"],
                )
            except services.TradeError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "후기를 남겼어요. 따뜻한 거래 고마워요!")
                return redirect("products:detail", pk=product.pk)
        messages.error(request, "입력한 내용을 다시 확인해 주세요.")

    return render(
        request,
        "trades/review_form.html",
        {
            "product": product,
            "form": form,
            "reviewee": reviewee,
            "reviewee_is_seller": reviewee_is_seller,
            "rating_labels": services.RATING_LABELS,
            "rating_deltas": services.RATING_DELTA,
        },
        status=400 if form.is_bound and form.errors else 200,
    )
