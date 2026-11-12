from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class ChatRoom(TimeStampedModel):
    """상품 하나에 대해 판매자-구매자 1:1 채팅방."""

    product = models.ForeignKey(
        "products.Product", on_delete=models.CASCADE, related_name="chat_rooms", verbose_name="상품"
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="selling_chat_rooms",
        verbose_name="판매자",
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="buying_chat_rooms",
        verbose_name="구매자",
    )
    last_message_at = models.DateTimeField("마지막 메시지 시각", null=True, blank=True)

    class Meta:
        verbose_name = "채팅방"
        verbose_name_plural = "채팅방"
        ordering = ["-last_message_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["product", "buyer"], name="unique_chatroom_product_buyer"),
        ]

    def __str__(self):
        return f"[{self.product}] {self.seller} ↔ {self.buyer}"

    def has_member(self, user):
        return user.pk in (self.seller_id, self.buyer_id)

    def other_user(self, user):
        """대화 상대를 반환한다."""
        return self.buyer if user.pk == self.seller_id else self.seller

    def unread_count_for(self, user):
        """user 입장에서 안 읽은(상대가 보낸) 메시지 수."""
        return self.messages.filter(is_read=False).exclude(sender=user).count()


class ChatMessage(models.Model):
    """채팅 메시지 (읽음 여부 포함)."""

    room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name="messages", verbose_name="채팅방")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages", verbose_name="보낸 사람"
    )
    content = models.TextField("내용")
    created_at = models.DateTimeField("보낸 시각", auto_now_add=True)
    is_read = models.BooleanField("읽음", default=False)
    read_at = models.DateTimeField("읽은 시각", null=True, blank=True)

    class Meta:
        verbose_name = "채팅 메시지"
        verbose_name_plural = "채팅 메시지"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["room", "created_at"], name="chatmsg_room_created_idx"),
            models.Index(fields=["room", "is_read"], name="chatmsg_room_read_idx"),
        ]

    def __str__(self):
        return f"{self.sender}: {self.content[:30]}"
