"""거래완료 · 거래 후기 · 매너온도 서비스.

뷰는 이 함수들만 호출한다. 사용자에게 보여줄 수 있는 오류는 TradeError 로 올린다.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.models import Profile
from apps.chat.models import ChatRoom
from apps.core.templatetags.poly_tags import display_name
from apps.moderation.services import is_blocked_between
from apps.notifications.models import Notification
from apps.notifications.services import notify
from apps.products.models import Product

from .models import Review

# ───────── 매너 태그 ─────────
# 받는 사람이 판매자인지/구매자인지에 따라 고를 수 있는 태그가 조금 다르다.
GOOD_TAGS_FOR_SELLER = [
    "친절해요",
    "시간 약속을 잘 지켜요",
    "응답이 빨라요",
    "상품 상태가 설명과 같아요",
    "가격이 합리적이에요",
]
GOOD_TAGS_FOR_BUYER = [
    "친절해요",
    "시간 약속을 잘 지켜요",
    "응답이 빨라요",
    "거래를 깔끔하게 마무리했어요",
]
BAD_TAGS_FOR_SELLER = [
    "불친절해요",
    "약속 시간을 안 지켰어요",
    "응답이 느려요",
    "상품 상태가 설명과 달라요",
]
BAD_TAGS_FOR_BUYER = [
    "불친절해요",
    "약속 시간을 안 지켰어요",
    "응답이 느려요",
    "무리하게 가격을 깎았어요",
]

# 별점 → 매너온도 변화량
RATING_DELTA = {
    5: Decimal("0.5"),
    4: Decimal("0.2"),
    3: Decimal("0"),
    2: Decimal("-0.3"),
    1: Decimal("-0.6"),
}
RATING_LABELS = {
    5: "최고예요",
    4: "좋아요",
    3: "보통이에요",
    2: "별로예요",
    1: "아쉬워요",
}
MIN_TEMPERATURE = Decimal("0")
MAX_TEMPERATURE = Decimal("99")
REVIEW_MAX_LENGTH = 500


class TradeError(Exception):
    """사용자에게 그대로 보여줄 수 있는 거래 오류."""


def manner_tag_choices(reviewee_is_seller: bool) -> tuple[list[str], list[str]]:
    """(좋았던 점, 아쉬웠던 점) 태그 목록."""
    if reviewee_is_seller:
        return GOOD_TAGS_FOR_SELLER, BAD_TAGS_FOR_SELLER
    return GOOD_TAGS_FOR_BUYER, BAD_TAGS_FOR_BUYER


# ───────── 거래완료 ─────────
def complete_trade(product, seller, buyer=None) -> Product:
    """상품을 거래완료로 바꾸고 구매자를 지정한다.

    buyer 는 이 상품으로 판매자와 채팅한 사용자여야 한다.
    buyer=None 이면 '채팅 밖에서 거래' — 구매자 없이 거래완료(후기 없음).
    구매자에게 STATUS_CHANGE 알림을 보낸다.
    """
    if product.seller_id != seller.pk:
        raise TradeError("내 상품만 거래완료로 바꿀 수 있어요.")
    if buyer is not None:
        if buyer.pk == seller.pk:
            raise TradeError("나 자신을 구매자로 선택할 수 없어요.")
        if not ChatRoom.objects.filter(product=product, seller=seller, buyer=buyer).exists():
            raise TradeError("이 상품으로 채팅한 이웃 중에서 선택해 주세요.")
        if is_blocked_between(seller, buyer):
            raise TradeError("차단 관계인 이웃은 구매자로 선택할 수 없어요.")

    with transaction.atomic():
        # 동시에 두 번 눌러도 한 번만 처리되도록 행 잠금
        locked = Product.objects.select_for_update().get(pk=product.pk)
        if locked.status == Product.Status.SOLD:
            raise TradeError("이미 거래완료된 상품이에요.")
        locked.status = Product.Status.SOLD
        locked.buyer = buyer
        locked.save(update_fields=["status", "buyer", "updated_at"])

    product.status = locked.status
    product.buyer = buyer
    product.updated_at = locked.updated_at

    if buyer is not None:
        notify(
            buyer,
            Notification.Kind.STATUS_CHANGE,
            f"'{product.title}' 거래가 완료됐어요. 거래 후기를 남겨 주세요.",
            url=reverse("trades:review_create", args=[product.pk]),
        )
    return product


# ───────── 후기 ─────────
def review_target(product, user):
    """user 가 이 상품 거래에서 후기를 남길 상대. 참여자가 아니면 None."""
    if not getattr(user, "pk", None) or not product.buyer_id:
        return None
    if user.pk == product.seller_id:
        return product.buyer
    if user.pk == product.buyer_id:
        return product.seller
    return None


def is_participant(product, user) -> bool:
    """거래 당사자(판매자 또는 지정된 구매자)인지."""
    return bool(getattr(user, "pk", None)) and user.pk in (product.seller_id, product.buyer_id)


def review_block_reason(product, user):
    """후기를 쓸 수 없는 이유(문구). 쓸 수 있으면 None."""
    if product.status != Product.Status.SOLD or not product.buyer_id:
        return "거래완료된 상품에만 후기를 남길 수 있어요."
    target = review_target(product, user)
    if target is None:
        return "거래한 당사자만 후기를 남길 수 있어요."
    # 차단 이후에는 서로 더 이상 상호작용하지 않는다 (후기·매너온도 반영 포함)
    if is_blocked_between(user, target):
        return "차단 관계인 이웃에게는 후기를 남길 수 없어요."
    if Review.objects.filter(product=product, reviewer=user).exists():
        return "이미 이 거래의 후기를 남겼어요."
    return None


def create_review(product, reviewer, rating, manner_tags=(), content="") -> Review:
    """거래 후기를 남기고 상대 매너온도에 반영한 뒤 REVIEW 알림을 보낸다."""
    reason = review_block_reason(product, reviewer)
    if reason:
        raise TradeError(reason)
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise TradeError("별점을 선택해 주세요.") from None
    if rating not in RATING_DELTA:
        raise TradeError("별점은 1점부터 5점까지 선택할 수 있어요.")

    reviewee = review_target(product, reviewer)
    good, bad = manner_tag_choices(reviewee_is_seller=reviewee.pk == product.seller_id)
    allowed = set(good) | set(bad)
    tags = []
    for tag in manner_tags or ():
        if tag not in allowed:
            raise TradeError("선택할 수 없는 매너 태그가 있어요.")
        if tag not in tags:  # 중복 제거, 순서 유지
            tags.append(tag)
    content = (content or "").strip()
    if len(content) > REVIEW_MAX_LENGTH:
        raise TradeError(f"후기는 {REVIEW_MAX_LENGTH}자까지 쓸 수 있어요.")

    try:
        with transaction.atomic():
            review = Review.objects.create(
                product=product,
                reviewer=reviewer,
                reviewee=reviewee,
                rating=rating,
                manner_tags=tags,
                content=content,
            )
            apply_manner_rating(reviewee, rating)
    except IntegrityError:  # 동시에 두 번 제출
        raise TradeError("이미 이 거래의 후기를 남겼어요.") from None

    notify(
        reviewee,
        Notification.Kind.REVIEW,
        f"{display_name(reviewer)}님이 '{product.title}' 거래 후기를 남겼어요.",
        url=reverse("accounts:mypage") + "?tab=reviews",
    )
    return review


def clamp_temperature(value) -> Decimal:
    """매너온도를 0~99 범위, 소수점 한 자리로 맞춘다."""
    value = Decimal(value).quantize(Decimal("0.1"))
    return max(MIN_TEMPERATURE, min(MAX_TEMPERATURE, value))


def apply_manner_rating(user, rating):
    """별점에 따라 user 의 매너온도를 올리거나 내린다. 새 온도(프로필 없으면 None)."""
    delta = RATING_DELTA.get(int(rating), Decimal("0"))
    with transaction.atomic():
        profile = Profile.objects.select_for_update().filter(user=user).first()
        if profile is None:  # 관리자 계정 등 프로필 없는 사용자
            return None
        profile.manner_temperature = clamp_temperature(profile.manner_temperature + delta)
        profile.save(update_fields=["manner_temperature"])
    # 이미 불러온 user.profile 캐시도 맞춰 둔다
    cached = user._state.fields_cache.get("profile")
    if cached is not None:
        cached.manner_temperature = profile.manner_temperature
    return profile.manner_temperature
