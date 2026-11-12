from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "reviewer", "reviewee", "rating", "created_at")
    list_filter = ("rating",)
    search_fields = ("product__title", "reviewer__username", "reviewee__username", "content")
    raw_id_fields = ("product", "reviewer", "reviewee")
