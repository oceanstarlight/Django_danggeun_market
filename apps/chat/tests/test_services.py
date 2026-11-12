from unittest import mock

from django.test import TestCase

from apps.chat import services
from apps.chat.models import ChatMessage, ChatRoom
from apps.moderation.models import Block
from apps.notifications.models import Notification
from apps.products.models import Product

from .factories import make_product, make_user


class GetOrCreateRoomTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = make_user("판매자")
        cls.buyer = make_user("구매자")
        cls.product = make_product(cls.seller)

    def test_creates_room_once(self):
        room, created = services.get_or_create_room(self.product, self.buyer)
        self.assertTrue(created)
        self.assertEqual(room.seller, self.seller)
        again, created_again = services.get_or_create_room(self.product, self.buyer)
        self.assertFalse(created_again)
        self.assertEqual(room.pk, again.pk)
        self.assertEqual(ChatRoom.objects.count(), 1)

    def test_own_product_rejected(self):
        with self.assertRaisesMessage(services.ChatError, "내 상품"):
            services.get_or_create_room(self.product, self.seller)

    def test_blocked_rejected_both_directions(self):
        Block.objects.create(blocker=self.seller, blocked=self.buyer)
        with self.assertRaises(services.ChatError):
            services.get_or_create_room(self.product, self.buyer)
        Block.objects.all().delete()
        Block.objects.create(blocker=self.buyer, blocked=self.seller)
        with self.assertRaises(services.ChatError):
            services.get_or_create_room(self.product, self.buyer)

    def test_sold_product_only_existing_room(self):
        room, _ = services.get_or_create_room(self.product, self.buyer)
        Product.objects.filter(pk=self.product.pk).update(status=Product.Status.SOLD)
        self.product.refresh_from_db()
        # 기존 방은 열 수 있어요
        self.assertEqual(services.get_or_create_room(self.product, self.buyer)[0].pk, room.pk)
        other = make_user()
        with self.assertRaisesMessage(services.ChatError, "거래가 끝난"):
            services.get_or_create_room(self.product, other)


class SendMessageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = make_user("판매자")
        cls.buyer = make_user("구매자")
        cls.product = make_product(cls.seller)
        cls.room = ChatRoom.objects.create(product=cls.product, seller=cls.seller, buyer=cls.buyer)

    def test_saves_message_and_updates_last_message_at(self):
        msg = services.send_message(self.room, self.buyer, "  안녕하세요!  ")
        self.assertEqual(msg.content, "안녕하세요!")
        self.room.refresh_from_db()
        self.assertEqual(self.room.last_message_at, msg.created_at)
        self.assertFalse(msg.is_read)

    def test_notifies_partner_with_collapse(self):
        services.send_message(self.room, self.buyer, "첫 메시지")
        services.send_message(self.room, self.buyer, "두 번째 메시지")
        notes = Notification.objects.filter(user=self.seller, kind=Notification.Kind.NEW_MESSAGE)
        self.assertEqual(notes.count(), 1)  # collapse_key 로 하나로 합쳐짐
        note = notes.get()
        self.assertIn("두 번째 메시지", note.message)
        self.assertIn("구매자", note.message)
        self.assertEqual(note.url, f"/chats/{self.room.pk}/")
        self.assertFalse(Notification.objects.filter(user=self.buyer).exists())

    def test_long_preview_truncated(self):
        services.send_message(self.room, self.seller, "가" * 300)
        note = Notification.objects.get(user=self.buyer)
        self.assertTrue(note.message.endswith("…"))
        self.assertLessEqual(len(note.message), 200)

    def test_validation(self):
        with self.assertRaises(services.ChatError):
            services.send_message(self.room, self.buyer, "   ")
        with self.assertRaises(services.ChatError):
            services.send_message(self.room, self.buyer, "a" * (services.MAX_MESSAGE_LENGTH + 1))
        with self.assertRaises(services.ChatError):
            services.send_message(self.room, make_user(), "끼어들기")
        self.assertFalse(ChatMessage.objects.exists())

    def test_blocked_cannot_send(self):
        Block.objects.create(blocker=self.seller, blocked=self.buyer)
        with self.assertRaisesMessage(services.ChatError, "차단"):
            services.send_message(self.room, self.buyer, "안녕하세요")
        with self.assertRaises(services.ChatError):
            services.send_message(self.room, self.seller, "안녕하세요")
        self.assertFalse(ChatMessage.objects.exists())


class ReadAndCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = make_user()
        cls.buyer = make_user()
        cls.room = ChatRoom.objects.create(product=make_product(cls.seller), seller=cls.seller, buyer=cls.buyer)

    def test_mark_room_read_only_partner_messages(self):
        m1 = services.send_message(self.room, self.buyer, "1")
        m2 = services.send_message(self.room, self.buyer, "2")
        mine = services.send_message(self.room, self.seller, "3")
        self.assertEqual(services.unread_chat_count(self.seller), 2)
        self.assertEqual(self.room.unread_count_for(self.seller), 2)
        ids = services.mark_room_read(self.room, self.seller)
        self.assertCountEqual(ids, [m1.pk, m2.pk])
        m1.refresh_from_db()
        mine.refresh_from_db()
        self.assertTrue(m1.is_read)
        self.assertIsNotNone(m1.read_at)
        self.assertFalse(mine.is_read)
        self.assertEqual(services.unread_chat_count(self.seller), 0)
        self.assertEqual(services.unread_chat_count(self.buyer), 1)
        # 두 번째 호출은 바뀌는 게 없어요
        self.assertEqual(services.mark_room_read(self.room, self.seller), [])

    def test_mark_read_non_member_noop(self):
        services.send_message(self.room, self.buyer, "1")
        self.assertEqual(services.mark_room_read(self.room, make_user()), [])

    def test_unread_count_anonymous(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(services.unread_chat_count(AnonymousUser()), 0)


class SerializeTests(TestCase):
    def test_payload_shape_and_flags(self):
        seller, buyer = make_user(), make_user("협상왕")
        room = ChatRoom.objects.create(product=make_product(seller), seller=seller, buyer=buyer)
        msg = services.send_message(room, buyer, "만원 깎아주실 수 있나요?")
        with mock.patch("apps.ai.services.negotiation.detect_negotiation", return_value=True), mock.patch(
            "apps.ai.services.fraud.check_text_rules", return_value=["선입금 요구"]
        ):
            payload = services.serialize_message(msg)
        self.assertEqual(
            set(payload),
            {"id", "content", "sender_id", "sender_name", "created_at", "is_read", "is_negotiation", "fraud_warnings"},
        )
        self.assertEqual(payload["sender_name"], "협상왕")
        self.assertTrue(payload["is_negotiation"])
        self.assertEqual(payload["fraud_warnings"], ["선입금 요구"])

    def test_flags_survive_ai_errors(self):
        with mock.patch("apps.ai.services.negotiation.detect_negotiation", side_effect=RuntimeError), mock.patch(
            "apps.ai.services.fraud.check_text_rules", side_effect=RuntimeError
        ), self.assertLogs("apps.chat.services", level="ERROR"):
            flags = services.message_flags("hello")
        self.assertEqual(flags, {"is_negotiation": False, "fraud_warnings": []})
