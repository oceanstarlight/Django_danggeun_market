from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class AIFeature(models.TextChoices):
    """AI 기능 구분 (캐시/로그 공용)."""

    DESCRIPTION = "DESCRIPTION", "상품 설명 생성"
    VISION = "VISION", "사진 인식"
    FRAUD = "FRAUD", "사기 탐지"
    NEGOTIATION = "NEGOTIATION", "가격 협상 초안"


class AIResultCache(models.Model):
    """같은 입력에 대한 AI 응답 캐시."""

    Feature = AIFeature

    feature = models.CharField("기능", max_length=20, choices=AIFeature.choices)
    input_hash = models.CharField("입력 해시", max_length=64)
    model_name = models.CharField("모델", max_length=100)
    response = models.JSONField("응답")
    hit_count = models.PositiveIntegerField("캐시 적중 수", default=0)
    created_at = models.DateTimeField("생성일", auto_now_add=True)

    class Meta:
        verbose_name = "AI 결과 캐시"
        verbose_name_plural = "AI 결과 캐시"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["feature", "input_hash", "model_name"], name="unique_ai_cache_entry"
            ),
        ]

    def __str__(self):
        return f"{self.feature} {self.input_hash[:10]}… ({self.hit_count}회)"


class AIUsageLog(models.Model):
    """AI 호출 기록 (캐시 적중 포함)."""

    Feature = AIFeature

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
        verbose_name="사용자",
    )
    feature = models.CharField("기능", max_length=20, choices=AIFeature.choices)
    model_name = models.CharField("모델", max_length=100)
    cached = models.BooleanField("캐시 사용", default=False)
    success = models.BooleanField("성공", default=True)
    prompt_tokens = models.PositiveIntegerField("입력 토큰", null=True, blank=True)
    output_tokens = models.PositiveIntegerField("출력 토큰", null=True, blank=True)
    latency_ms = models.PositiveIntegerField("지연(ms)", null=True, blank=True)
    error = models.TextField("오류", blank=True)
    created_at = models.DateTimeField("호출 시각", auto_now_add=True)

    class Meta:
        verbose_name = "AI 사용 기록"
        verbose_name_plural = "AI 사용 기록"
        ordering = ["-created_at"]

    def __str__(self):
        flag = "캐시" if self.cached else ("성공" if self.success else "실패")
        return f"{self.feature} · {flag} · {self.created_at:%Y-%m-%d %H:%M}"


class FraudAnalysis(models.Model):
    """상품 사기 위험 분석 결과 (상품당 1개, content_hash 같으면 재사용)."""

    class RiskLevel(models.TextChoices):
        LOW = "LOW", "낮음"
        MEDIUM = "MEDIUM", "주의"
        HIGH = "HIGH", "위험"

    class Source(models.TextChoices):
        RULE = "RULE", "규칙"
        AI = "AI", "AI"
        RULE_AI = "RULE_AI", "규칙+AI"

    product = models.OneToOneField(
        "products.Product", on_delete=models.CASCADE, related_name="fraud_analysis", verbose_name="상품"
    )
    content_hash = models.CharField("내용 해시", max_length=64)
    risk_level = models.CharField("위험도", max_length=10, choices=RiskLevel.choices, default=RiskLevel.LOW)
    risk_score = models.PositiveSmallIntegerField(
        "위험 점수", default=0, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    reasons = models.JSONField("판단 근거", default=list, blank=True)
    rule_hits = models.JSONField("규칙 매칭", default=list, blank=True)
    source = models.CharField("판단 방식", max_length=10, choices=Source.choices, default=Source.RULE)
    analyzed_at = models.DateTimeField("분석 시각", auto_now=True)

    class Meta:
        verbose_name = "사기 분석"
        verbose_name_plural = "사기 분석"

    def __str__(self):
        return f"{self.product} - {self.get_risk_level_display()}({self.risk_score})"

    @property
    def is_warning(self):
        """배너를 보여줘야 하는지 (LOW 는 숨김)."""
        return self.risk_level != self.RiskLevel.LOW
