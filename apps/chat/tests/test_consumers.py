"""ChatConsumer WebSocket 테스트 (channels.testing.WebsocketCommunicator)."""

from unittest import mock

from asgiref.sync import sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from apps.chat import consumers, services
from apps.chat.models import ChatMessage, ChatRoom
from apps.chat.routing import websocket_urlpatterns
from apps.moderation.models import Block
from apps.notifications.models import Notification

from .factories import make_product, make_user

application = URLRouter(websocket_urlpatterns)


class ChatConsumerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.seller = make_user("판매자")
        cls.buyer = make_user("구매자")
        cls.product = make_product(cls.seller)
        cls.room = ChatRoom.objects.create(product=cls.product, seller=cls.seller, buyer=cls.buyer)

    def _communicator(self, user, room_id=None):
        comm = WebsocketCommunicator(application, f"/ws/chat/{room_id or self.room.pk}/")
        comm.scope["user"] = user
        return comm

    async def _connect(self, user):
        comm = self._communicator(user)
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        return comm

    async def test_rejects_anonymous_non_member_and_missing_room(self):
        comm = self._communicator(AnonymousUser())
        connected, code = await comm.connect()
        self.assertFalse(connected)
        self.assertEqual(code, consumers.CLOSE_UNAUTHENTICATED)

        stranger = await sync_to_async(make_user)()
        comm = self._communicator(stranger)
        connected, code = await comm.connect()
        self.assertFalse(connected)
        self.assertEqual(code, consumers.CLOSE_FORBIDDEN)

        comm = self._communicator(self.buyer, room_id=999999)
        connected, code = await comm.connect()
        self.assertFalse(connected)
        self.assertEqual(code, consumers.CLOSE_NOT_FOUND)

    async def test_message_broadcast_to_both_members(self):
        buyer_ws = await self._connect(self.buyer)
        seller_ws = await self._connect(self.seller)
        with mock.patch("apps.ai.services.negotiation.detect_negotiation", return_value=True):
            await buyer_ws.send_json_to({"type": "message", "content": "  만원만 깎아 주세요  "})
            to_buyer = await buyer_ws.receive_json_from()
            to_seller = await seller_ws.receive_json_from()
        self.assertEqual(to_buyer, to_seller)
        self.assertEqual(to_seller["type"], "message")
        payload = to_seller["message"]
        for key in ("id", "content", "sender_id", "sender_name", "created_at", "is_negotiation"):
            self.assertIn(key, payload)
        self.assertEqual(payload["content"], "만원만 깎아 주세요")
        self.assertEqual(payload["sender_id"], self.buyer.pk)
        self.assertEqual(payload["sender_name"], "구매자")
        self.assertTrue(payload["is_negotiation"])

        msg = await sync_to_async(ChatMessage.objects.get)(pk=payload["id"])
        self.assertEqual(msg.room_id, self.room.pk)
        room = await sync_to_async(ChatRoom.objects.get)(pk=self.room.pk)
        self.assertEqual(room.last_message_at, msg.created_at)
        notified = await sync_to_async(
            Notification.objects.filter(user=self.seller, kind=Notification.Kind.NEW_MESSAGE).count
        )()
        self.assertEqual(notified, 1)
        await buyer_ws.disconnect()
        await seller_ws.disconnect()

    async def test_read_event_reaches_sender(self):
        buyer_ws = await self._connect(self.buyer)
        seller_ws = await self._connect(self.seller)
        await buyer_ws.send_json_to({"type": "message", "content": "읽어 주세요"})
        payload = (await buyer_ws.receive_json_from())["message"]
        await seller_ws.receive_json_from()
        self.assertFalse(payload["is_read"])

        await seller_ws.send_json_to({"type": "read"})
        event = await buyer_ws.receive_json_from()
        self.assertEqual(event, {"type": "read", "reader_id": self.seller.pk, "message_ids": [payload["id"]]})
        self.assertEqual((await seller_ws.receive_json_from())["type"], "read")  # 본인에게도 전달(무시용)
        msg = await sync_to_async(ChatMessage.objects.get)(pk=payload["id"])
        self.assertTrue(msg.is_read)

        # 이미 다 읽었으면 이벤트 없음
        await seller_ws.send_json_to({"type": "read"})
        self.assertTrue(await buyer_ws.receive_nothing(timeout=0.2))
        await buyer_ws.disconnect()
        await seller_ws.disconnect()

    async def test_connect_marks_unread_as_read_and_notifies(self):
        msg = await sync_to_async(services.send_message)(self.room, self.buyer, "먼저 보낸 메시지")
        buyer_ws = await self._connect(self.buyer)
        seller_ws = await self._connect(self.seller)  # 입장 = 읽음
        event = await buyer_ws.receive_json_from()
        self.assertEqual(event["type"], "read")
        self.assertEqual(event["message_ids"], [msg.pk])
        await buyer_ws.disconnect()
        await seller_ws.disconnect()

    async def test_blocked_sender_gets_error_only(self):
        await sync_to_async(Block.objects.create)(blocker=self.seller, blocked=self.buyer)
        buyer_ws = await self._connect(self.buyer)
        seller_ws = await self._connect(self.seller)
        await buyer_ws.send_json_to({"type": "message", "content": "안녕하세요"})
        error = await buyer_ws.receive_json_from()
        self.assertEqual(error["type"], "error")
        self.assertIn("차단", error["message"])
        self.assertTrue(await seller_ws.receive_nothing(timeout=0.2))
        self.assertFalse(await sync_to_async(ChatMessage.objects.exists)())
        await buyer_ws.disconnect()
        await seller_ws.disconnect()

    async def test_invalid_payloads(self):
        ws = await self._connect(self.buyer)
        await ws.send_json_to({"type": "message", "content": "   "})
        self.assertEqual((await ws.receive_json_from())["type"], "error")
        await ws.send_json_to({"type": "message", "content": 123})
        self.assertEqual((await ws.receive_json_from())["type"], "error")
        await ws.send_json_to({"type": "dance"})
        self.assertEqual((await ws.receive_json_from())["type"], "error")
        await ws.send_json_to(["not", "a", "dict"])
        self.assertEqual((await ws.receive_json_from())["type"], "error")
        self.assertFalse(await sync_to_async(ChatMessage.objects.exists)())
        await ws.disconnect()

    async def test_http_fallback_broadcasts_to_socket(self):
        seller_ws = await self._connect(self.seller)
        msg = await sync_to_async(services.send_message)(self.room, self.buyer, "HTTP 로 보냈어요")
        await sync_to_async(services.broadcast_message)(msg)
        event = await seller_ws.receive_json_from()
        self.assertEqual(event["message"]["id"], msg.pk)
        await seller_ws.disconnect()

    async def test_fraud_warnings_in_payload(self):
        ws = await self._connect(self.seller)
        with mock.patch("apps.ai.services.fraud.check_text_rules", return_value=["외부 메신저 유도"]):
            await ws.send_json_to({"type": "message", "content": "카톡으로 연락 주세요"})
            payload = (await ws.receive_json_from())["message"]
        self.assertEqual(payload["fraud_warnings"], ["외부 메신저 유도"])
        await ws.disconnect()
