from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Category(models.Model):
    """상품 카테고리 (데이터 마이그레이션으로 시드)."""

    slug = models.SlugField("슬러그", max_length=30, unique=True)
    name = models.CharField("이름", max_length=30)
    icon = models.CharField("아이콘(이모지)", max_length=8, blank=True)
    order = models.PositiveSmallIntegerField("정렬 순서", default=0)

    class Meta:
        verbose_name = "카테고리"
        verbose_name_plural = "카테고리"
        ordering = ["order", "id"]

    def __str__(self):
        return self.name


class Product(TimeStampedModel):
    """판매 상품."""

    class Status(models.TextChoices):
        SELLING = "SELLING", "판매중"
        RESERVED = "RESERVED", "예약중"
        SOLD = "SOLD", "거래완료"

    class Condition(models.TextChoices):
        NEW = "NEW", "새상품(미개봉)"
        LIKE_NEW = "LIKE_NEW", "거의 새것"
        GOOD = "GOOD", "사용감 적음"
        FAIR = "FAIR", "사용감 있음"
        POOR = "POOR", "고장/부품용"

    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="products", verbose_name="판매자"
    )
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products", verbose_name="카테고리"
    )
    region = models.ForeignKey(
        "accounts.Region",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name="거래 동네",
    )
    title = models.CharField("제목", max_length=100)
    content = models.TextField("설명")
    price = models.PositiveIntegerField("가격", help_text="0원이면 나눔이에요.")
    negotiable = models.BooleanField("가격 제안 받기", default=False)
    condition = models.CharField("상품 상태", max_length=10, choices=Condition.choices, default=Condition.GOOD)
    status = models.CharField("판매 상태", max_length=10, choices=Status.choices, default=Status.SELLING)
    view_count = models.PositiveIntegerField("조회수", default=0)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchases",
        verbose_name="구매자",
    )

    class Meta:
        verbose_name = "상품"
        verbose_name_plural = "상품"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="product_status_created_idx"),
            models.Index(fields=["category"], name="product_category_idx"),
        ]

    def __str__(self):
        return self.title

    @property
    def is_free(self):
        return self.price == 0

    @property
    def thumbnail_url(self):
        """첫 번째 이미지 URL (없으면 None). prefetch_related('images') 와 함께 쓰면 쿼리 절약."""
        cache = getattr(self, "_prefetched_objects_cache", {})
        if "images" in cache:
            images = list(cache["images"])
            return images[0].image_url if images else None
        first = self.images.order_by("order", "id").first()
        return first.image_url if first else None

    @property
    def wish_count(self):
        """annotate(num_wishes=...) 가 있으면 사용, 없으면 count 쿼리."""
        annotated = getattr(self, "num_wishes", None)
        if annotated is not None:
            return annotated
        return self.wishlists.count()

    @property
    def chat_count(self):
        """annotate(num_chats=...) 가 있으면 사용, 없으면 count 쿼리."""
        annotated = getattr(self, "num_chats", None)
        if annotated is not None:
            return annotated
        return self.chat_rooms.count()


class ProductImage(models.Model):
    """상품 이미지 (Supabase/로컬 URL 저장)."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images", verbose_name="상품")
    # dev 에서는 "/media/..." 상대경로도 저장하므로 URLField 대신 CharField
    image_url = models.CharField("이미지 URL", max_length=500)
    order = models.PositiveSmallIntegerField("순서", default=0)

    class Meta:
        verbose_name = "상품 이미지"
        verbose_name_plural = "상품 이미지"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.product_id} #{self.order}"


class Wishlist(models.Model):
    """찜."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlists", verbose_name="사용자"
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlists", verbose_name="상품")
    created_at = models.DateTimeField("찜한 시각", auto_now_add=True)

    class Meta:
        verbose_name = "찜"
        verbose_name_plural = "찜"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="unique_wishlist"),
        ]

    def __str__(self):
        return f"{self.user} ♥ {self.product}"


class RecentView(models.Model):
    """최근 본 상품."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recent_views", verbose_name="사용자"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="recent_views", verbose_name="상품"
    )
    viewed_at = models.DateTimeField("본 시각", auto_now=True)

    class Meta:
        verbose_name = "최근 본 상품"
        verbose_name_plural = "최근 본 상품"
        ordering = ["-viewed_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="unique_recent_view"),
        ]

    def __str__(self):
        return f"{self.user} → {self.product}"
