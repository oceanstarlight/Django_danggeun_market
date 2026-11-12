from django.contrib import admin

from .costs import estimate_cost_usd
from .models import AIResultCache, AIUsageLog, FraudAnalysis


@admin.register(AIResultCache)
class AIResultCacheAdmin(admin.ModelAdmin):
    list_display = ("id", "feature", "model_name", "short_hash", "hit_count", "created_at")
    list_filter = ("feature", "model_name")
    search_fields = ("input_hash",)

    @admin.display(description="입력 해시")
    def short_hash(self, obj):
        return obj.input_hash[:12]


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = (
        "id", "feature", "user", "model_name", "cached", "success",
        "prompt_tokens", "output_tokens", "estimated_cost", "latency_ms", "created_at",
    )
    list_filter = ("feature", "cached", "success", "model_name")
    search_fields = ("user__username", "error")
    raw_id_fields = ("user",)
    date_hierarchy = "created_at"

    @admin.display(description="추정 비용(USD)")
    def estimated_cost(self, obj):
        cost = estimate_cost_usd(obj.prompt_tokens, obj.output_tokens)
        return "-" if cost is None else f"${cost:.6f}"


@admin.register(FraudAnalysis)
class FraudAnalysisAdmin(admin.ModelAdmin):
    list_display = ("product", "risk_level", "risk_score", "source", "analyzed_at")
    list_filter = ("risk_level", "source")
    search_fields = ("product__title",)
    raw_id_fields = ("product",)
