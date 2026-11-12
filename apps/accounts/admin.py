from django.contrib import admin

from .models import Profile, Region


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("id", "code", "sido", "sigungu", "dong")
    list_filter = ("sido",)
    search_fields = ("code", "sido", "sigungu", "dong")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("nickname", "user", "region", "manner_temperature", "created_at")
    list_select_related = ("user", "region")
    search_fields = ("nickname", "user__username", "phone")
    autocomplete_fields = ("region",)
