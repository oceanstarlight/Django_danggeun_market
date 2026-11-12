from django.contrib import admin

from .models import ChatMessage, ChatRoom


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    raw_id_fields = ("sender",)


@admin.register(ChatRoom)
class ChatRoomAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "seller", "buyer", "last_message_at", "created_at")
    list_select_related = ("product", "seller", "buyer")
    search_fields = ("product__title", "seller__username", "buyer__username")
    raw_id_fields = ("product", "seller", "buyer")
    inlines = [ChatMessageInline]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "room", "sender", "short_content", "is_read", "created_at")
    list_filter = ("is_read",)
    search_fields = ("content", "sender__username")
    raw_id_fields = ("room", "sender")

    @admin.display(description="내용")
    def short_content(self, obj):
        return obj.content[:40]
