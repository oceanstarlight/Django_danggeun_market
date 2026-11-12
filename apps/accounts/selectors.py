"""accounts 조회 로직 (마이페이지 · 판매자 프로필 · 중복 확인)."""

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, OuterRef, Q, Subquery

from apps.products.models import Product, RecentView, Wishlist
from apps.products.selectors import with_card_data
from apps.trades.models import Review

from .models import Profile

User = get_user_model()

ON_SALE = (Product.Status.SELLING, Product.Status.RESERVED)

# 마이페이지 탭 (key, 라벨). 순서대로 노출돼요.
MYPAGE_TABS = (
    ("selling", "판매중"),
    ("sold", "거래완료"),
    ("bought", "구매내역"),
    ("wishlist", "찜한 상품"),
    ("recent", "최근 본"),
    ("reviews", "받은 후기"),
)
SELLER_TABS = (
    ("selling", "판매 상품"),
    ("sold", "거래완료"),
    ("reviews", "받은 후기"),
)


# ───────── 중복 확인 ─────────
def is_username_taken(username: str) -> bool:
    return User.objects.filter(username__iexact=username).exists()


def is_nickname_taken(nickname: str, exclude_user_id: int | None = None) -> bool:
    qs = Profile.objects.filter(nickname__iexact=nickname)
    if exclude_user_id:
        qs = qs.exclude(user_id=exclude_user_id)
    return qs.exists()


def is_phone_taken(phone: str) -> bool:
    return Profile.objects.filter(phone=phone).exists()


# ───────── 상품 카드용 기본 쿼리 ─────────
def product_cards():
    """product_card 컴포넌트가 N+1 없이 렌더되도록 준비한 QuerySet (products 셀렉터 재사용)."""
    return with_card_data(Product.objects.all())


def selling_products(user):
    return product_cards().filter(seller=user, status__in=ON_SALE).order_by("-created_at")


def sold_products(user):
    return product_cards().filter(seller=user, status=Product.Status.SOLD).order_by("-updated_at")


def bought_products(user, exclude_seller_ids=()):
    return (
        product_cards()
        .filter(buyer=user)
        .exclude(seller_id__in=exclude_seller_ids)
        .order_by("-updated_at")
    )


def wishlist_products(user, exclude_seller_ids=()):
    """찜한 순서(최근 찜 먼저). 차단 관계 사용자의 상품은 숨겨요."""
    wished = Wishlist.objects.filter(user=user, product=OuterRef("pk")).values("created_at")[:1]
    return (
        product_cards()
        .filter(pk__in=Wishlist.objects.filter(user=user).values("product"))
        .exclude(seller_id__in=exclude_seller_ids)
        .annotate(wished_at=Subquery(wished))
        .order_by("-wished_at")
    )


def recent_products(user, exclude_seller_ids=()):
    """최근 본 순서. 차단 관계 사용자의 상품은 숨겨요."""
    viewed = RecentView.objects.filter(user=user, product=OuterRef("pk")).values("viewed_at")[:1]
    return (
        product_cards()
        .filter(pk__in=RecentView.objects.filter(user=user).values("product"))
        .exclude(seller_id__in=exclude_seller_ids)
        .annotate(viewed_at=Subquery(viewed))
        .order_by("-viewed_at")
    )


# ───────── 후기 ─────────
def received_reviews(user):
    return (
        Review.objects.filter(reviewee=user)
        .select_related("reviewer__profile", "product")
        .order_by("-created_at")
    )


def review_summary(user, top_tags: int = 5) -> dict:
    """받은 후기 요약: 평균 별점, 별 개수, 후기 수, 많이 받은 매너 태그."""
    qs = Review.objects.filter(reviewee=user)
    agg = qs.aggregate(avg=Avg("rating"), count=Count("pk"))
    counter = Counter()
    for tags in qs.values_list("manner_tags", flat=True):
        if isinstance(tags, list):
            counter.update(str(t) for t in tags if t)
    avg = agg["avg"]
    avg = round(Decimal(str(avg)), 1) if avg is not None else None
    return {
        "count": agg["count"] or 0,
        "avg": avg,
        # 별 아이콘 개수 (반올림)
        "stars": int(avg.quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if avg is not None else 0,
        "tags": counter.most_common(top_tags),
    }


# ───────── 탭 개수 ─────────
def product_counts(user) -> dict:
    """판매중/거래완료 개수 (쿼리 1번)."""
    return Product.objects.filter(seller=user).aggregate(
        selling=Count("pk", filter=Q(status__in=ON_SALE)),
        sold=Count("pk", filter=Q(status=Product.Status.SOLD)),
    )


def mypage_counts(user, exclude_seller_ids=()) -> dict:
    counts = product_counts(user)
    counts["bought"] = Product.objects.filter(buyer=user).exclude(seller_id__in=exclude_seller_ids).count()
    counts["wishlist"] = (
        Wishlist.objects.filter(user=user).exclude(product__seller_id__in=exclude_seller_ids).count()
    )
    counts["recent"] = (
        RecentView.objects.filter(user=user).exclude(product__seller_id__in=exclude_seller_ids).count()
    )
    counts["reviews"] = Review.objects.filter(reviewee=user).count()
    return counts


def build_tabs(tab_defs, counts: dict, active: str) -> list[dict]:
    """템플릿에서 쓰기 쉬운 탭 목록."""
    return [
        {"key": key, "label": label, "count": counts.get(key, 0), "active": key == active}
        for key, label in tab_defs
    ]


def public_user(username: str):
    """판매자 프로필 대상 사용자 (없거나 비활성이면 None)."""
    return (
        User.objects.select_related("profile__region")
        .filter(username=username, is_active=True)
        .first()
    )
