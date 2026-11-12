"""상품 쓰기 로직 (등록/수정/삭제/찜/상태 변경/조회 기록).

뷰는 권한 확인과 응답만 하고, 데이터 변경은 여기 함수들을 거친다.
"""

import logging

from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.urls import reverse

from apps.core.storage import upload_image
from apps.notifications.models import Notification
from apps.notifications.services import notify

from .models import Product, ProductImage, RecentView, Wishlist

logger = logging.getLogger(__name__)

RECENT_VIEW_LIMIT = 50  # 사용자당 최근 본 상품 보관 개수
EDITABLE_FIELDS = ("title", "category", "condition", "price", "negotiable", "region", "content")


class ProductActionError(Exception):
    """사용자에게 그대로 보여줄 수 있는 상품 처리 오류."""


def _image_folder(product):
    return f"products/{product.seller_id}/{product.pk}"


def _save_images(product, files, start_order=0):
    """이미지를 저장소에 올리고 ProductImage 를 만든다. 실패하면 StorageError."""
    rows = []
    for offset, file in enumerate(files):
        url = upload_image(file, _image_folder(product))
        rows.append(ProductImage(product=product, image_url=url, order=start_order + offset))
    if rows:
        ProductImage.objects.bulk_create(rows)
    return rows


def _renumber_images(product):
    """삭제 후 순서를 0부터 다시 매긴다 (첫 번째 = 대표 사진)."""
    images = list(product.images.order_by("order", "id"))
    changed = []
    for index, image in enumerate(images):
        if image.order != index:
            image.order = index
            changed.append(image)
    if changed:
        ProductImage.objects.bulk_update(changed, ["order"])


def run_fraud_analysis(product):
    """AI 사기 탐지 (실패해도 상품 저장에는 영향 없음)."""
    try:
        from apps.ai.services.fraud import analyze_product

        return analyze_product(product)
    except Exception:  # noqa: BLE001 - AI/네트워크 오류는 로그만 남긴다
        logger.exception("사기 탐지 분석 실패 (product=%s)", product.pk)
        return None


def create_product(seller, data, images=()):
    """상품을 등록한다. data 는 EDITABLE_FIELDS 의 값 dict.

    이미지 업로드가 실패하면 StorageError 가 나고 상품도 저장되지 않는다.
    """
    with transaction.atomic():
        product = Product(seller=seller, **{k: v for k, v in data.items() if k in EDITABLE_FIELDS})
        if product.price == 0:
            product.negotiable = False
        product.save()
        _save_images(product, list(images))
    run_fraud_analysis(product)
    return product


def update_product(product, data, new_images=(), remove_images=()):
    """상품을 수정한다. 가격이 바뀌면 찜한 사람들에게 알림을 보낸다.

    remove_images: 지울 ProductImage 목록(또는 id 목록) — 이 상품의 이미지만 지운다.
    """
    # ModelForm 검증이 instance 를 미리 바꿔 두므로 이전 가격은 DB 에서 읽는다
    old_price = Product.objects.filter(pk=product.pk).values_list("price", flat=True).first()
    with transaction.atomic():
        for field in EDITABLE_FIELDS:
            if field in data:
                setattr(product, field, data[field])
        if product.price == 0:
            product.negotiable = False
        product.save()

        remove_ids = [getattr(img, "pk", img) for img in remove_images]
        if remove_ids:
            product.images.filter(pk__in=remove_ids).delete()
        new_images = list(new_images)
        if new_images:
            start = (product.images.aggregate(m=Max("order"))["m"] or -1) + 1
            _save_images(product, new_images, start_order=start)
        _renumber_images(product)

    if old_price is not None and old_price != product.price:
        notify_price_change(product, old_price)
    run_fraud_analysis(product)
    return product


def notify_price_change(product, old_price):
    """찜한 사용자(판매자 제외)에게 가격 변동 알림."""
    from apps.core.templatetags.poly_tags import price as fmt_price

    title = product.title if len(product.title) <= 30 else product.title[:29] + "…"
    direction = "내려갔어요" if product.price < old_price else "올랐어요"
    # '원'/'나눔' 모두 받침이 있어서 '으로'
    message = f"찜한 '{title}'의 가격이 {fmt_price(old_price)}에서 {fmt_price(product.price)}으로 {direction}"
    url = reverse("products:detail", args=[product.pk])
    wishers = (
        Wishlist.objects.filter(product=product)
        .exclude(user_id=product.seller_id)
        .select_related("user")
    )
    count = 0
    for wish in wishers:
        notify(wish.user, Notification.Kind.PRICE_CHANGE, message, url=url, collapse_key=f"price:{product.pk}")
        count += 1
    return count


def delete_product(product):
    """상품 삭제 (이미지/찜/채팅방은 CASCADE)."""
    product.delete()


def toggle_wishlist(user, product):
    """찜 토글 → 찜한 상태면 True. 본인 상품은 찜할 수 없다."""
    if product.seller_id == user.pk:
        raise ProductActionError("내 상품은 찜할 수 없어요.")
    deleted, _ = Wishlist.objects.filter(user=user, product=product).delete()
    if deleted:
        return False
    try:
        with transaction.atomic():
            Wishlist.objects.create(user=user, product=product)
    except IntegrityError:  # 동시에 두 번 눌린 경우
        pass
    return True


# 상세 화면 셀렉트에서 바꿀 수 있는 상태 (거래완료는 trades:complete 에서 구매자를 고른다)
DIRECT_STATUSES = (Product.Status.SELLING, Product.Status.RESERVED)


def change_status(product, status):
    """판매중 ↔ 예약중 변경. 거래완료로는 바로 바꿀 수 없다(ProductActionError).

    거래완료 상품을 다시 판매중/예약중으로 돌리면 구매자 지정이 해제된다.
    단, 이미 거래 후기가 있으면 되돌릴 수 없다(같은 상품으로 후기 중복 방지).
    반환: 실제로 바뀌었으면 True.
    """
    if status == Product.Status.SOLD:
        raise ProductActionError("거래완료는 구매자를 선택해서 처리해 주세요.")
    if status not in DIRECT_STATUSES:
        raise ProductActionError("올바르지 않은 상태예요.")
    if product.status == status:
        return False
    # 후기가 남은 거래를 되돌리면 같은 상품으로 후기를 여러 번 받을 수 있어서 막는다
    if product.status == Product.Status.SOLD and product.reviews.exists():
        raise ProductActionError("후기가 남은 거래는 되돌릴 수 없어요.")
    product.status = status
    fields = ["status", "updated_at"]
    if product.buyer_id:
        product.buyer = None
        fields.append("buyer")
    product.save(update_fields=fields)
    return True


def record_view(product, user=None, count=True):
    """조회수 증가(F 식) + 최근 본 상품 기록. 판매자 본인 조회는 세지 않는다."""
    is_owner = getattr(user, "pk", None) == product.seller_id
    if count and not is_owner:
        Product.objects.filter(pk=product.pk).update(view_count=F("view_count") + 1)
        product.view_count += 1
    if getattr(user, "is_authenticated", False) and not is_owner:
        RecentView.objects.update_or_create(user=user, product=product)
        _prune_recent_views(user)


def _prune_recent_views(user):
    stale = RecentView.objects.filter(user=user).order_by("-viewed_at").values_list("pk", flat=True)[
        RECENT_VIEW_LIMIT:
    ]
    stale_ids = list(stale)
    if stale_ids:
        RecentView.objects.filter(pk__in=stale_ids).delete()
