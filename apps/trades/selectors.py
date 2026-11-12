"""trades 조회 전용 함수."""

from django.db.models import Count, F, OuterRef, Subquery

from apps.chat.models import ChatMessage, ChatRoom


def chat_partners(product):
    """이 상품으로 판매자와 채팅한 구매자 채팅방 목록 (최근 대화 순).

    각 room 에 num_messages, last_message(내용 미리보기) 를 annotate 한다.
    """
    last_message = ChatMessage.objects.filter(room=OuterRef("pk")).order_by("-created_at", "-pk")
    return (
        ChatRoom.objects.filter(product=product, seller_id=product.seller_id)
        .exclude(buyer_id=product.seller_id)
        .select_related("buyer__profile__region")
        .annotate(
            num_messages=Count("messages"),
            last_message=Subquery(last_message.values("content")[:1]),
        )
        .order_by(F("last_message_at").desc(nulls_last=True), "-created_at")
    )
