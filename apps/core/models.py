from django.db import models


class TimeStampedModel(models.Model):
    """생성/수정 시각을 자동으로 기록하는 추상 모델."""

    created_at = models.DateTimeField("생성일", auto_now_add=True)
    updated_at = models.DateTimeField("수정일", auto_now=True)

    class Meta:
        abstract = True
