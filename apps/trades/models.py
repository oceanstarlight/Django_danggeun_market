from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import TimeStampedModel


class Review(TimeStampedModel):
    """거래 후기 / 매너 평가 (구매자↔판매자 양방향, 상품당 1회)."""

    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="reviews", verbose_name="상품"
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews_written",
        verbose_name="작성자",
    )
    reviewee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews_received",
        verbose_name="받는 사람",
    )
    rating = models.PositiveSmallIntegerField(
        "별점", validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    manner_tags = models.JSONField("매너 태그", default=list, blank=True)
    content = models.TextField("후기", blank=True)

    class Meta:
        verbose_name = "거래 후기"
        verbose_name_plural = "거래 후기"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["product", "reviewer"], name="unique_review_product_reviewer"),
        ]

    def __str__(self):
        return f"{self.reviewer} → {self.reviewee} ({self.rating}점)"
