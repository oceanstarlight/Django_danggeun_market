from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.chat import services
from apps.chat.models import ChatMessage, ChatRoom
from apps.moderation.models import Block
from apps.products.models import Product, ProductImage

from .factories import make_product, make_user

PASSWORD = "pass-1234-word"


class ChatStartViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = make_user("판매자")
        cls.buyer = make_user("구매자")
        cls.product = make_product(cls.seller)
        cls.url = reverse("chat:start", args=[cls.product.pk])

    def test_login_required(self):
        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("accounts:login"), res["Location"])

    def test_get_shows_confirm_page(self):
        self.client.force_login(self.buyer)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "chat/start.html")
        self.assertContains(res, "채팅 시작하기")
        self.assertFalse(ChatRoom.objects.exists())

    def test_post_creates_room_and_redirects(self):
        self.client.force_login(self.buyer)
        res = self.client.post(self.url)
        room = ChatRoom.objects.get()
        self.assertRedirects(res, reverse("chat:room", args=[room.pk]))
        # 다시 눌러도 같은 방
        res = self.client.post(self.url)
        self.assertRedirects(res, reverse("chat:room", args=[room.pk]))
        self.assertEqual(ChatRoom.objects.count(), 1)

    def test_get_with_existing_room_redirects(self):
        room = ChatRoom.objects.create(product=self.product, seller=self.seller, buyer=self.buyer)
        self.client.force_login(self.buyer)
        self.assertRedirects(self.client.get(self.url), reverse("chat:room", args=[room.pk]))

    def test_own_product(self):
        self.client.force_login(self.seller)
        res = self.client.post(self.url)
        self.assertRedirects(res, reverse("chat:list"))
        self.assertFalse(ChatRoom.objects.exists())

    def test_blocked(self):
        Block.objects.create(blocker=self.seller, blocked=self.buyer)
        self.client.force_login(self.buyer)
        res = self.client.post(self.url, follow=True)
        self.assertRedirects(res, reverse("products:detail", args=[self.product.pk]), fetch_redirect_response=False)
        self.assertFalse(ChatRoom.objects.exists())
        self.assertContains(self.client.get(self.url), "채팅할 수 없어요")

    def test_missing_product_404(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.post(reverse("chat:start", args=[999999])).status_code, 404)


class ChatRoomViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = make_user("판매자")
        cls.buyer = make_user("구매자")
        cls.product = make_product(cls.seller)
        ProductImage.objects.create(product=cls.product, image_url="/media/products/a.jpg")
        cls.room = ChatRoom.objects.create(product=cls.product, seller=cls.seller, buyer=cls.buyer)
        cls.url = reverse("chat:room", args=[cls.room.pk])

    def test_non_member_403_and_missing_404(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse("chat:room", args=[999999])).status_code, 404)

    def test_anonymous_redirects_to_login(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)

    def test_entering_marks_partner_messages_read(self):
        services.send_message(self.room, self.buyer, "안녕하세요")
        mine = services.send_message(self.room, self.seller, "네 안녕하세요")
        self.client.force_login(self.seller)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "chat/room.html")
        self.assertFalse(ChatMessage.objects.filter(sender=self.buyer, is_read=False).exists())
        mine.refresh_from_db()
        self.assertFalse(mine.is_read)  # 내 메시지는 그대로

    def test_room_renders_product_bar_and_seller_actions(self):
        services.send_message(self.room, self.buyer, "구매 가능할까요?")
        self.client.force_login(self.seller)
        res = self.client.get(self.url)
        self.assertContains(res, self.product.title)
        self.assertContains(res, "450,000원")
        self.assertContains(res, "/media/products/a.jpg")
        self.assertContains(res, reverse("products:status_change", args=[self.product.pk]))
        self.assertContains(res, reverse("trades:complete", args=[self.product.pk]))
        self.assertContains(res, 'id="chat-negotiation-template"')
        self.assertContains(res, f'data-ws-path="/ws/chat/{self.room.pk}/"')

    def test_buyer_has_no_seller_actions(self):
        self.client.force_login(self.buyer)
        res = self.client.get(self.url)
        self.assertNotContains(res, reverse("trades:complete", args=[self.product.pk]))
        self.assertNotContains(res, 'id="chat-negotiation-template"')
        self.assertContains(res, "첫 메시지를 보내 보세요")

    def test_read_receipt_and_date_separator(self):
        msg = services.send_message(self.room, self.buyer, "읽어 주세요")
        services.mark_room_read(self.room, self.seller)
        self.client.force_login(self.buyer)
        res = self.client.get(self.url)
        html = res.content.decode()
        row_start = html.index(f'data-message-id="{msg.pk}"')
        snippet = html[row_start : row_start + 800]
        self.assertIn("data-read>읽음", snippet)  # hidden 이 없으면 '읽음' 표시
        today = timezone.localtime(msg.created_at).date()
        self.assertContains(res, f'data-date="{today:%Y-%m-%d}"', count=1)

    def test_content_is_escaped(self):
        services.send_message(self.room, self.buyer, "<script>alert(1)</script>")
        self.client.force_login(self.seller)
        res = self.client.get(self.url)
        self.assertNotContains(res, "<script>alert(1)</script>")
        self.assertContains(res, "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_negotiation_button_only_for_seller_on_buyer_messages(self):
        services.send_message(self.room, self.buyer, "조금만 깎아 주세요")
        services.send_message(self.room, self.seller, "얼마에 생각하세요? 깎")
        nego_url_prefix = "/ai/negotiate/"
        with mock.patch("apps.ai.services.negotiation.detect_negotiation", return_value=True):
            self.client.force_login(self.seller)
            seller_html = self.client.get(self.url).content.decode()
            self.client.force_login(self.buyer)
            buyer_html = self.client.get(self.url).content.decode()
        buyer_msg = ChatMessage.objects.get(sender=self.buyer)
        self.assertIn(f"{nego_url_prefix}{buyer_msg.pk}/", seller_html)
        seller_msg = ChatMessage.objects.get(sender=self.seller)
        self.assertNotIn(f"{nego_url_prefix}{seller_msg.pk}/", seller_html)
        self.assertNotIn('class="chat-nego"', buyer_html)

    def test_fraud_warning_only_under_incoming_messages(self):
        services.send_message(self.room, self.buyer, "선입금 먼저 해주세요")
        with mock.patch("apps.ai.services.fraud.check_text_rules", return_value=["선입금을 요구해요"]):
            self.client.force_login(self.seller)
            seller_res = self.client.get(self.url)
            self.client.force_login(self.buyer)
            buyer_res = self.client.get(self.url)
        self.assertContains(seller_res, "사기 의심 신호가 있어요")
        self.assertContains(seller_res, "선입금을 요구해요")
        self.assertNotContains(buyer_res, "사기 의심 신호가 있어요")

    def test_post_fallback_sends_message(self):
        self.client.force_login(self.buyer)
        res = self.client.post(self.url, {"content": "JS 없이 보내요"})
        self.assertRedirects(res, f"{self.url}#chat-bottom", fetch_redirect_response=False)
        self.assertTrue(ChatMessage.objects.filter(content="JS 없이 보내요").exists())

    def test_post_json_fallback(self):
        self.client.force_login(self.buyer)
        res = self.client.post(self.url, {"content": "fetch 로 보내요"}, HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"]["content"], "fetch 로 보내요")
        res = self.client.post(self.url, {"content": "  "}, HTTP_ACCEPT="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.json()["ok"])

    def test_post_blocked_shows_error(self):
        Block.objects.create(blocker=self.seller, blocked=self.buyer)
        self.client.force_login(self.buyer)
        res = self.client.post(self.url, {"content": "안녕하세요"}, follow=True)
        self.assertFalse(ChatMessage.objects.exists())
        self.assertContains(res, "메시지를 보낼 수 없어요")
        self.assertNotContains(res, 'id="chat-form"')  # 입력창 대신 안내

    def test_post_non_member_403(self):
        self.client.force_login(make_user())
        self.assertEqual(self.client.post(self.url, {"content": "hi"}).status_code, 403)

    def test_older_messages_fragment(self):
        for i in range(55):
            ChatMessage.objects.create(room=self.room, sender=self.buyer, content=f"메시지 {i}")
        self.client.force_login(self.seller)
        res = self.client.get(self.url)
        self.assertContains(res, 'id="chat-older"')
        first_shown = res.context["entries"][0]["message"]
        self.assertEqual(len(res.context["entries"]), 50)
        frag = self.client.get(self.url, {"before": first_shown.pk}, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(frag, "chat/partials/messages.html")
        self.assertTemplateNotUsed(frag, "base.html")
        self.assertEqual(len(frag.context["entries"]), 5)
        self.assertFalse(frag.context["has_more"])
        self.assertEqual(self.client.get(self.url, {"before": "x"}, HTTP_HX_REQUEST="true").status_code, 400)

    def test_after_fragment_marks_read(self):
        m1 = services.send_message(self.room, self.buyer, "하나")
        m2 = services.send_message(self.room, self.buyer, "둘")
        self.client.force_login(self.seller)
        res = self.client.get(self.url, {"after": m1.pk}, HTTP_X_CHAT_FRAGMENT="1")
        self.assertEqual([e["message"].pk for e in res.context["entries"]], [m2.pk])
        m2.refresh_from_db()
        self.assertTrue(m2.is_read)

    def test_room_query_count_is_bounded(self):
        """메시지가 늘어도 채팅방 쿼리 수는 그대로 (N+1 없음)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for i in range(10):
            services.send_message(self.room, self.buyer if i % 2 else self.seller, f"메시지 {i}")
        self.client.force_login(self.seller)
        self.client.get(self.url)
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url)
        for i in range(20):
            services.send_message(self.room, self.buyer if i % 2 else self.seller, f"더 {i}")
        services.mark_room_read(self.room, self.seller)
        with CaptureQueriesContext(connection) as big:
            self.client.get(self.url)
        self.assertEqual(len(small.captured_queries), len(big.captured_queries))


class ChatListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.me = make_user("나")
        cls.a = make_user("에이")
        cls.b = make_user("비")
        # 내가 구매자인 방 (a 의 상품)
        cls.buy_room = ChatRoom.objects.create(product=make_product(cls.a, title="자전거"), seller=cls.a, buyer=cls.me)
        # 내가 판매자인 방 (b 가 문의)
        my_product = make_product(cls.me, title="책상")
        cls.sell_room = ChatRoom.objects.create(product=my_product, seller=cls.me, buyer=cls.b)
        # 대화 없는 판매 방은 숨김
        cls.empty_sell_room = ChatRoom.objects.create(product=my_product, seller=cls.me, buyer=cls.a)

    def test_login_required(self):
        self.assertEqual(self.client.get(reverse("chat:list")).status_code, 302)

    def test_ordering_preview_and_unread(self):
        services.send_message(self.sell_room, self.b, "책상 아직 있나요?")
        services.send_message(self.buy_room, self.a, "네 자전거 있어요")
        services.send_message(self.buy_room, self.a, "언제 오실래요?")
        self.client.force_login(self.me)
        res = self.client.get(reverse("chat:list"))
        self.assertEqual(res.status_code, 200)
        rooms = list(res.context["page_obj"])
        self.assertEqual([r.pk for r in rooms], [self.buy_room.pk, self.sell_room.pk])
        self.assertEqual(rooms[0].unread, 2)
        self.assertEqual(rooms[0].last_message_content, "언제 오실래요?")
        self.assertEqual(rooms[0].partner, self.a)
        self.assertContains(res, "언제 오실래요?")
        self.assertContains(res, "안 읽은 메시지 2개")
        self.assertNotContains(res, reverse("chat:room", args=[self.empty_sell_room.pk]))

        # 내가 답장하면 순서가 바뀌고 '나:' 접두어
        services.send_message(self.sell_room, self.me, "네 있어요")
        res = self.client.get(reverse("chat:list"))
        rooms = list(res.context["page_obj"])
        self.assertEqual(rooms[0].pk, self.sell_room.pk)
        self.assertTrue(rooms[0].is_mine_last)

    def test_filters_and_counts(self):
        services.send_message(self.sell_room, self.b, "문의")
        self.client.force_login(self.me)
        res = self.client.get(reverse("chat:list"), {"filter": "selling"})
        self.assertEqual([r.pk for r in res.context["page_obj"]], [self.sell_room.pk])
        res = self.client.get(reverse("chat:list"), {"filter": "buying"})
        self.assertEqual([r.pk for r in res.context["page_obj"]], [self.buy_room.pk])
        res = self.client.get(reverse("chat:list"), {"filter": "unread"})
        self.assertEqual([r.pk for r in res.context["page_obj"]], [self.sell_room.pk])
        self.assertEqual(res.context["counts"], {"all": 2, "selling": 1, "buying": 1, "unread": 1})
        res = self.client.get(reverse("chat:list"), {"filter": "nope"})
        self.assertEqual(res.context["filter_key"], "all")

    def test_empty_state(self):
        self.client.force_login(make_user())
        res = self.client.get(reverse("chat:list"))
        self.assertContains(res, "아직 대화가 없어요")

    def test_no_n_plus_one(self):
        for i in range(5):
            seller = make_user()
            p = make_product(seller)
            ProductImage.objects.create(product=p, image_url=f"/media/p{i}.jpg")
            room = ChatRoom.objects.create(product=p, seller=seller, buyer=self.me)
            services.send_message(room, seller, "안녕하세요")
        self.client.force_login(self.me)
        self.client.get(reverse("chat:list"))
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as small:
            self.client.get(reverse("chat:list"))
        for i in range(5):
            seller = make_user()
            room = ChatRoom.objects.create(product=make_product(seller), seller=seller, buyer=self.me)
            services.send_message(room, seller, "또 안녕하세요")
        with CaptureQueriesContext(connection) as big:
            self.client.get(reverse("chat:list"))
        self.assertEqual(len(small.captured_queries), len(big.captured_queries))


class MarkReadViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = make_user()
        cls.buyer = make_user()
        cls.room = ChatRoom.objects.create(product=make_product(cls.seller), seller=cls.seller, buyer=cls.buyer)
        cls.url = reverse("chat:mark_read", args=[cls.room.pk])

    def test_post_only(self):
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_marks_read_json(self):
        msg = services.send_message(self.room, self.buyer, "hi")
        self.client.force_login(self.seller)
        res = self.client.post(self.url, HTTP_ACCEPT="application/json")
        self.assertEqual(res.json(), {"ok": True, "message_ids": [msg.pk]})
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)

    def test_redirect_and_permissions(self):
        self.client.force_login(self.seller)
        self.assertRedirects(self.client.post(self.url), reverse("chat:room", args=[self.room.pk]))
        self.client.force_login(make_user())
        self.assertEqual(self.client.post(self.url).status_code, 403)

    def test_csrf_enforced(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.seller)
        self.assertEqual(client.post(self.url).status_code, 403)


class SoldProductRoomTests(TestCase):
    def test_review_button_after_trade(self):
        seller, buyer = make_user(), make_user()
        product = make_product(seller)
        room = ChatRoom.objects.create(product=product, seller=seller, buyer=buyer)
        Product.objects.filter(pk=product.pk).update(status=Product.Status.SOLD, buyer=buyer)
        self.client.force_login(buyer)
        res = self.client.get(reverse("chat:room", args=[room.pk]))
        self.assertContains(res, reverse("trades:review_create", args=[product.pk]))
        self.assertContains(res, "후기 보내기")
