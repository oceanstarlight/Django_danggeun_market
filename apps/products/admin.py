from django.contrib import admin

from .models import Category, Product, ProductImage, RecentView, Wishlist


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("order", "icon", "name", "slug")
    list_display_links = ("name",)
    search_fields = ("name", "slug")
    ordering = ("order",)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "seller", "category", "price", "status", "view_count", "created_at")
    list_filter = ("status", "condition", "category")
    list_select_related = ("seller", "category")
    search_fields = ("title", "content", "seller__username")
    raw_id_fields = ("seller", "buyer")
    inlines = [ProductImageInline]


@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "order", "image_url")
    search_fields = ("product__title",)
    raw_id_fields = ("product",)


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "created_at")
    search_fields = ("user__username", "product__title")
    raw_id_fields = ("user", "product")


@admin.register(RecentView)
class RecentViewAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "viewed_at")
    search_fields = ("user__username", "product__title")
    raw_id_fields = ("user", "product")
