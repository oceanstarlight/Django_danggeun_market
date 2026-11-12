from django.contrib import admin

from .models import Block, Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("id", "reporter", "product", "reported_user", "reason", "status", "created_at")
    list_filter = ("reason", "status")
    search_fields = ("reporter__username", "reported_user__username", "product__title", "detail")
    raw_id_fields = ("reporter", "product", "reported_user")
    actions = ["mark_reviewed"]

    @admin.action(description="선택한 신고를 검토 완료로 표시")
    def mark_reviewed(self, request, queryset):
        queryset.update(status=Report.Status.REVIEWED)


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked", "created_at")
    search_fields = ("blocker__username", "blocked__username")
    raw_id_fields = ("blocker", "blocked")
