"""채팅 WebSocket consumer.

클라이언트 → 서버
  {"type": "message", "content": "..."}   메시지 보내기
  {"type": "read"}                         지금 보고 있으니 상대 메시지 읽음 처리
서버 → 클라이언트
  {"type": "message", "message": {id, content, sender_id, sender_name, created_at, is_negotiation, ...}}
  {"type": "read", "reader_id": 3, "message_ids": [..]}
  {"type": "error", "message": "..."}
"""

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from . import services
from .models import ChatRoom

# 닫기 코드 (4000번대 = 애플리케이션 정의)
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


class ChatConsumer(JsonWebsocketConsumer):
    """방 하나에 대한 실시간 채팅. 동기 consumer 라 ORM/서비스를 그대로 쓴다."""

    room = None
    group_name = None

    def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            self.close(code=CLOSE_UNAUTHENTICATED)
            return
        room_id = self.scope["url_route"]["kwargs"]["room_id"]
        room = ChatRoom.objects.filter(pk=room_id).first()
        if room is None:
            self.close(code=CLOSE_NOT_FOUND)
            return
        if not room.has_member(user):
            self.close(code=CLOSE_FORBIDDEN)
            return

        self.room = room
        self.group_name = services.room_group_name(room.pk)
        async_to_sync(self.channel_layer.group_add)(self.group_name, self.channel_name)
        self.accept()
        # (재)연결 시점에도 읽음 처리
        self._mark_read()

    def disconnect(self, code):
        if self.group_name:
            async_to_sync(self.channel_layer.group_discard)(self.group_name, self.channel_name)

    def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            return self._error("잘못된 요청이에요.")
        kind = content.get("type")
        if kind == "message":
            self._send_message(content.get("content"))
        elif kind == "read":
            self._mark_read()
        else:
            self._error("알 수 없는 요청이에요.")

    # ───────── 처리 ─────────

    def _send_message(self, text):
        user = self.scope["user"]
        if not isinstance(text, str):
            return self._error("메시지를 입력해 주세요.")
        # 방 정보(참여자)는 바뀌지 않지만 상품 삭제 등으로 방이 사라졌을 수 있다
        room = ChatRoom.objects.select_related("seller", "buyer").filter(pk=self.room.pk).first()
        if room is None:
            self._error("채팅방이 사라졌어요.")
            self.close(code=CLOSE_NOT_FOUND)
            return
        try:
            message = services.send_message(room, user, text)
        except services.ChatError as exc:
            return self._error(str(exc))
        services.broadcast_message(message)

    def _mark_read(self):
        ids = services.mark_room_read(self.room, self.scope["user"])
        services.broadcast_read(self.room.pk, self.scope["user"].pk, ids)

    def _error(self, message):
        self.send_json({"type": "error", "message": message})

    # ───────── 그룹 이벤트 핸들러 ─────────

    def chat_message(self, event):
        self.send_json({"type": "message", "message": event["message"]})

    def chat_read(self, event):
        self.send_json(
            {"type": "read", "reader_id": event["reader_id"], "message_ids": event["message_ids"]}
        )
