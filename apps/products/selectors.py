"""상품 조회 로직 (읽기 전용). 뷰와 다른 앱(마이페이지 등)에서 함께 쓴다."""

from dataclasses import dataclass

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Subquery

from apps.accounts import regions as region_lookup
from apps.accounts.models import Region
from apps.moderation.services import blocked_user_ids

from .models import Category, Product, ProductImage, RecentView, Wishlist

PAGE_SIZE = 20

SORT_ORDERINGS = {
    "latest": ("-created_at", "-id"),
    "price_asc": ("price", "-created_at"),
    "price_desc": ("-price", "-created_at"),
    "popular": ("-num_wishes", "-num_chats", "-view_count", "-created_at"),
}


def with_card_data(queryset):
    """상품 카드 렌더에 필요한 관계/집계를 한 번에 붙인다 (N+1 방지).

    components/product_card.html 이 쓰는 region · thumbnail_url · wish_count · chat_count 를 커버한다.
    """
    return (
        queryset.select_related("region", "category")
        .prefetch_related(Prefetch("images", queryset=ProductImage.objects.order_by("order", "id")))
        .annotate(
            num_wishes=Count("wishlists", distinct=True),
            num_chats=Count("chat_rooms", distinct=True),
        )
    )


def visible_products(user=None):
    """차단 관계(내가 차단/나를 차단) 사용자의 상품을 뺀 전체 상품."""
    qs = Product.objects.all()
    blocked = blocked_user_ids(user) if user is not None else set()
    if blocked:
        qs = qs.exclude(seller_id__in=blocked)
    return qs


def user_region(user):
    """로그인 사용자의 동네 (없으면 None)."""
    if not getattr(user, "is_authenticated", False):
        return None
    try:
        return user.profile.region
    except Exception:  # noqa: BLE001 - 프로필 없는 사용자(관리자 등)
        return None


def resolve_region(user, value):
    """region 파라미터(me|all|<id>|"") → (선택 값, Region|None).

    값이 없으면 내 동네가 있을 때 'me', 없으면 'all' 이 기본이다.
    """
    mine = user_region(user)
    value = (value or "").strip()
    if not value:
        value = "me" if mine else "all"
    if value == "me":
        return ("me", mine) if mine else ("all", None)
    if value == "all":
        return "all", None
    region = region_lookup.region_by_pk(value)  # '²' 같은 유니코드 숫자 · 음수 등은 None
    if region is not None:
        if mine and region.pk == mine.pk:
            return "me", mine
        return str(region.pk), region
    return "all", None


@dataclass(frozen=True)
class RegionFilter:
    """목록의 동네 필터.

    value: "me"(내 동네) | "all"(전체) | "<pk>"(특정 읍/면/동) | "sido"(시/도 전체) | "sigungu"(시/군/구 전체)
    """

    value: str = "all"
    region: Region | None = None
    sido: str = ""
    sigungu: str = ""

    @property
    def is_all(self):
        return self.value == "all"

    @property
    def label(self):
        """화면에 보여줄 이름 (예: '강원특별자치도 춘천시 전체')."""
        if self.region is not None:
            return self.region.name
        if self.sigungu:
            return f"{self.sido} {self.sigungu} 전체"
        if self.sido:
            return f"{self.sido} 전체"
        return "전체 지역"

    @property
    def selection(self):
        """3단 select 에 미리 골라 둘 (sido, sigungu, Region|None)."""
        if self.region is not None:
            return self.region.sido, self.region.sigungu, self.region
        return self.sido, self.sigungu, None

    def query_params(self):
        """이 필터를 유지하는 GET 파라미터 (내 동네는 기본값이라 비움)."""
        if self.value == "me":
            return {}
        if self.region is not None:
            return {"region": str(self.region.pk)}
        if self.sido:
            params = {"sido": self.sido}
            if self.sigungu:
                params["sigungu"] = self.sigungu
            return params
        return {"region": "all"}


def resolve_region_filter(user, *, region="", sido=None, sigungu=""):
    """GET 파라미터 → RegionFilter.

    - sido 파라미터가 있으면(3단 select 로 제출) 고른 단계까지만 거른다:
      region(pk)이 그 시/도·시/군/구에 속하면 그 동, 아니면 시/군/구 전체, 아니면 시/도 전체, 시/도가 비면 전체.
      (위 단계를 바꾸면 아래 단계 값이 남아 있어도 무시돼요)
    - sido 가 없으면 예전 규칙 그대로: region = me | all | <pk> | ""(내 동네가 있으면 me, 없으면 all)
    """
    mine = user_region(user)
    if sido is not None:
        # NUL·비문자열은 빈 값으로 (PostgreSQL 은 NUL 이 든 문자열로 쿼리하면 에러)
        sido = region_lookup.clean_param(sido)
        sigungu = region_lookup.clean_param(sigungu)
        # select 목록과 같은 기준(코드 있는 행 + 내 동네)으로 확인해야 화면과 실제 필터가 어긋나지 않아요
        if not region_lookup.sido_exists(sido, keep=mine):
            return RegionFilter("all")
        if not region_lookup.sigungu_exists(sido, sigungu, keep=mine):
            return RegionFilter("sido", sido=sido)
        picked = region_lookup.region_by_pk(region)
        if picked is not None and (picked.sido, picked.sigungu) == (sido, sigungu):
            if mine and picked.pk == mine.pk:
                return RegionFilter("me", region=mine)
            return RegionFilter(str(picked.pk), region=picked)
        return RegionFilter("sigungu", sido=sido, sigungu=sigungu)
    value, picked = resolve_region(user, region)
    return RegionFilter(value, region=picked)


def search_products(user, *, q="", category=None, region=None, sido="", sigungu="", status="all", sort="latest"):
    """목록/검색 쿼리셋. category 는 Category, region 은 Region 또는 None.

    region 이 없을 때 sido(+sigungu)를 주면 그 시/도(시/군/구) 전체에서 찾는다.
    """
    qs = visible_products(user)
    for term in (q or "").split()[:5]:
        qs = qs.filter(Q(title__icontains=term) | Q(content__icontains=term))
    if category is not None:
        qs = qs.filter(category=category)
    if region is not None:
        qs = qs.filter(region=region)
    elif sido:
        qs = qs.filter(region__sido=sido)
        if sigungu:
            qs = qs.filter(region__sigungu=sigungu)
    if status == "selling":
        qs = qs.filter(status=Product.Status.SELLING)
    qs = with_card_data(qs)
    return qs.order_by(*SORT_ORDERINGS.get(sort, SORT_ORDERINGS["latest"]))


def category_by_slug(slug):
    if not slug:
        return None
    return Category.objects.filter(slug=slug).first()


def popular_products(user, limit=10):
    """인기 상품 TOP (판매중, 찜·채팅·조회 순). 사기 위험 '높음' 상품은 추천에서 뺀다."""
    qs = (
        visible_products(user)
        .filter(status=Product.Status.SELLING)
        .exclude(fraud_analysis__risk_level="HIGH")
    )
    qs = with_card_data(qs)
    return list(qs.order_by(*SORT_ORDERINGS["popular"])[:limit])


def latest_products(user, region=None, limit=10):
    """최신 상품 (region 이 있으면 그 동네만). 거래완료는 제외."""
    qs = visible_products(user).exclude(status=Product.Status.SOLD)
    if region is not None:
        qs = qs.filter(region=region)
    return list(with_card_data(qs).order_by("-created_at", "-id")[:limit])


def recent_viewed_products(user, limit=10):
    """최근 본 상품 (차단 관계 상품 제외)."""
    if not getattr(user, "is_authenticated", False):
        return []
    blocked = blocked_user_ids(user)
    views = (
        RecentView.objects.filter(user=user)
        .exclude(product__seller_id__in=blocked)
        .select_related("product", "product__region")
        .prefetch_related(Prefetch("product__images", queryset=ProductImage.objects.order_by("order", "id")))
        .order_by("-viewed_at")[:limit]
    )
    return [v.product for v in views]


def wishlisted_products(user):
    """내가 찜한 상품 (최근 찜한 순). 마이페이지 찜 탭용."""
    mine = Wishlist.objects.filter(user=user, product=OuterRef("pk"))
    # wishlists 로 직접 filter 하면 num_wishes 집계가 내 찜 1건으로 줄어들어서 서브쿼리로 거른다
    qs = visible_products(user).filter(Exists(mine)).annotate(wished_at=Subquery(mine.values("created_at")[:1]))
    return with_card_data(qs).order_by("-wished_at")


def get_product_for_detail(pk, user=None):
    """상세 화면용 상품. 판매자 프로필/사기 분석/이미지를 한 번에 가져온다."""
    qs = (
        Product.objects.select_related(
            "seller", "seller__profile", "seller__profile__region", "category", "region", "buyer", "fraud_analysis"
        )
        .prefetch_related(Prefetch("images", queryset=ProductImage.objects.order_by("order", "id")))
        .annotate(
            num_wishes=Count("wishlists", distinct=True),
            num_chats=Count("chat_rooms", distinct=True),
        )
    )
    if getattr(user, "is_authenticated", False):
        qs = qs.annotate(is_wished=Exists(Wishlist.objects.filter(user=user, product=OuterRef("pk"))))
    return qs.filter(pk=pk).first()


def seller_other_products(product, user=None, limit=6):
    """같은 판매자의 다른 상품 (거래완료 제외)."""
    qs = (
        visible_products(user)
        .filter(seller_id=product.seller_id)
        .exclude(pk=product.pk)
        .exclude(status=Product.Status.SOLD)
    )
    return list(with_card_data(qs).order_by("-created_at")[:limit])


def seller_stats(seller):
    """판매자 카드에 보여줄 거래 수치."""
    counts = Product.objects.filter(seller=seller).aggregate(
        total=Count("id"), sold=Count("id", filter=Q(status=Product.Status.SOLD))
    )
    return counts


def is_wished(user, product):
    if not getattr(user, "is_authenticated", False):
        return False
    annotated = getattr(product, "is_wished", None)
    if annotated is not None:
        return bool(annotated)
    return Wishlist.objects.filter(user=user, product=product).exists()


def user_chat_room(user, product):
    """구매자 입장에서 이 상품에 대한 내 채팅방 (없으면 None)."""
    if not getattr(user, "is_authenticated", False) or user.pk == product.seller_id:
        return None
    from apps.chat.models import ChatRoom

    return ChatRoom.objects.filter(product=product, buyer=user).only("id").first()
