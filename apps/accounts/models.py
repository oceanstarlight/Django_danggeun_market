from decimal import Decimal

from django.conf import settings
from django.db import models


class Region(models.Model):
    """동네 (시/도 · 시/군/구 · 동)."""

    sido = models.CharField("시/도", max_length=20)
    sigungu = models.CharField("시/군/구", max_length=20)
    dong = models.CharField("동", max_length=20)

    class Meta:
        verbose_name = "동네"
        verbose_name_plural = "동네"
        ordering = ["sido", "sigungu", "dong"]
        constraints = [
            models.UniqueConstraint(fields=["sido", "sigungu", "dong"], name="unique_region"),
        ]

    def __str__(self):
        return self.name

    @property
    def name(self):
        return f"{self.sido} {self.sigungu} {self.dong}"

    @property
    def short_name(self):
        """카드 등 좁은 곳에 쓰는 짧은 이름 (예: '역삼동')."""
        return self.dong


class Profile(models.Model):
    """사용자 프로필 (User 와 1:1)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile", verbose_name="사용자"
    )
    nickname = models.CharField("닉네임", max_length=20, unique=True)
    birth_date = models.DateField("생년월일", null=True, blank=True)
    phone = models.CharField("휴대폰", max_length=20, unique=True, null=True, blank=True)
    region = models.ForeignKey(
        Region, on_delete=models.SET_NULL, null=True, blank=True, related_name="profiles", verbose_name="동네"
    )
    bio = models.TextField("소개", blank=True)
    # dev 에서는 "/media/..." 상대경로도 저장하므로 URLField 대신 CharField
    avatar_url = models.CharField("프로필 사진", max_length=500, blank=True)
    manner_temperature = models.DecimalField(
        "매너온도", max_digits=4, decimal_places=1, default=Decimal("36.5")
    )
    created_at = models.DateTimeField("가입일", auto_now_add=True)

    class Meta:
        verbose_name = "프로필"
        verbose_name_plural = "프로필"

    def __str__(self):
        return f"{self.nickname} ({self.user.username})"
