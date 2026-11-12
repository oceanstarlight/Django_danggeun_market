from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Report(TimeStampedModel):
    """상품/사용자 신고."""

    class Reason(models.TextChoices):
        FRAUD = "FRAUD", "사기 의심"
        PROHIBITED = "PROHIBITED", "판매 금지 물품"
        ABUSE = "ABUSE", "욕설/비매너"
        SPAM = "SPAM", "광고/도배"
        ETC = "ETC", "기타"

    class Status(models.TextChoices):
        PENDING = "PENDING", "접수"
        REVIEWED = "REVIEWED", "검토 완료"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports_made", verbose_name="신고자"
    )
    product = models.ForeignKey(
        "products.Product",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reports",
        verbose_name="신고 상품",
    )
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reports_received",
        verbose_name="신고 대상",
    )
    reason = models.CharField("사유", max_length=20, choices=Reason.choices)
    detail = models.TextField("상세 내용", blank=True)
    status = models.CharField("처리 상태", max_length=20, choices=Status.choices, default=Status.PENDING)

    class Meta:
        verbose_name = "신고"
        verbose_name_plural = "신고"
        ordering = ["-created_at"]

    def __str__(self):
        target = self.product or self.reported_user
        return f"{self.get_reason_display()} - {target}"


class Block(models.Model):
    """사용자 차단."""

    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocking", verbose_name="차단한 사람"
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="blocked_by", verbose_name="차단된 사람"
    )
    created_at = models.DateTimeField("차단일", auto_now_add=True)

    class Meta:
        verbose_name = "차단"
        verbose_name_plural = "차단"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["blocker", "blocked"], name="unique_block"),
        ]

    def __str__(self):
        return f"{self.blocker} ⛔ {self.blocked}"
