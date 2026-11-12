from django.conf import settings
from django.db import models


class Notification(models.Model):
    """사용자 알림."""

    class Kind(models.TextChoices):
        PRICE_CHANGE = "PRICE_CHANGE", "가격 변동"
        NEW_MESSAGE = "NEW_MESSAGE", "새 메시지"
        REVIEW = "REVIEW", "거래 후기"
        STATUS_CHANGE = "STATUS_CHANGE", "거래 상태"
        SYSTEM = "SYSTEM", "알림"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications", verbose_name="사용자"
    )
    kind = models.CharField("종류", max_length=20, choices=Kind.choices, default=Kind.SYSTEM)
    message = models.CharField("내용", max_length=200)
    url = models.CharField("이동 URL", max_length=300, blank=True)
    is_read = models.BooleanField("읽음", default=False)
    created_at = models.DateTimeField("생성일", auto_now_add=True)

    class Meta:
        verbose_name = "알림"
        verbose_name_plural = "알림"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"], name="notif_user_read_idx"),
        ]

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.user}: {self.message}"

    # 종류별 아이콘(components/icon.html name)과 색 클래스 (Tailwind 가 스캔하도록 전체 이름을 적어 둔다)
    _ICONS = {
        Kind.PRICE_CHANGE: ("tag", "notif-icon-PRICE_CHANGE"),
        Kind.NEW_MESSAGE: ("chat", "notif-icon-NEW_MESSAGE"),
        Kind.REVIEW: ("star-fill", "notif-icon-REVIEW"),
        Kind.STATUS_CHANGE: ("check", "notif-icon-STATUS_CHANGE"),
    }

    @property
    def icon_name(self):
        return self._ICONS.get(self.kind, ("bell", ""))[0]

    @property
    def icon_class(self):
        return self._ICONS.get(self.kind, ("bell", ""))[1]
