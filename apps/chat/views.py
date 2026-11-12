"""채팅 뷰 (목록 · 채팅방 · 채팅 시작 · 읽음 처리).

실시간 송수신은 WebSocket(consumers.ChatConsumer)이 담당하고,
여기서는 화면 렌더링과 JS 없이도 동작하는 POST 대체 경로를 제공한다.
"""

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import login_required
from apps.moderation.services import has_blocked, is_blocked_between
from apps.products.models import Product

from . import selectors, services

LIST_PAGE_SIZE = 20


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _wants_html_fragment(request):
    return request.headers.get("X-Chat-Fragment") == "1"


def _wants_json(request):
    return "application/json" in request.headers.get("Accept", "")


def build_entries(chat_messages, viewer, room, flags_by_id=None):
    """템플릿용 메시지 항목: 날짜 구분선 · 아바타 표시 · 협상 버튼 · 사기 경고 여부를 미리 계산."""
    viewer_is_seller = viewer.pk == room.seller_id
    entries = []
    prev_date = None
    prev_sender = None
    for m in chat_messages:
        local_date = timezone.localtime(m.created_at).date()
        mine = m.sender_id == viewer.pk
        date_sep = local_date if local_date != prev_date else None
        flags = (flags_by_id or {}).get(m.pk) or (services.message_flags(m.content) if not mine else None)
        entries.append(
            {
                "message": m,
                "mine": mine,
                "date_sep": date_sep,
                # 상대 메시지 묶음의 첫 메시지에만 아바타
                "show_avatar": not mine and (date_sep is not None or prev_sender != m.sender_id),
                # 판매자 화면 + 구매자 메시지 + 협상 문구 → AI 답장 초안 버튼
                "show_negotiation": bool(
                    flags and viewer_is_seller and m.sender_id == room.buyer_id and flags["is_negotiation"]
                ),
                # 상대 메시지에만 사기 의심 경고
                "fraud_warnings": (flags["fraud_warnings"] if flags else []),
            }
        )
        prev_date = local_date
        prev_sender = m.sender_id
    return entries


# ───────────────────────── 목록 ─────────────────────────


@login_required
@require_GET
def chat_list(request):
    """내 채팅 목록 (마지막 메시지 순). ?filter=all|selling|buying|unread"""
    filter_key = request.GET.get("filter", "all")
    if filter_key not in selectors.LIST_FILTERS:
        filter_key = "all"
    rooms = selectors.rooms_for_user(request.user, filter_key)
    page_obj = Paginator(rooms, LIST_PAGE_SIZE).get_page(request.GET.get("page"))
    for room in page_obj:
        room.partner = room.other_user(request.user)
        room.is_mine_last = room.last_message_sender_id == request.user.pk
    counts = selectors.list_counts(request.user)
    labels = {"all": "전체", "selling": "판매", "buying": "구매", "unread": "안 읽음"}
    tabs = [(key, labels[key], counts[key]) for key in selectors.LIST_FILTERS]
    return render(
        request,
        "chat/list.html",
        {"page_obj": page_obj, "filter_key": filter_key, "tabs": tabs, "counts": counts},
    )


# ───────────────────────── 채팅방 ─────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def chat_room(request, room_id):
    """채팅방. GET: 화면(+입장 시 읽음 처리) / POST: JS 없이 메시지 보내기."""
    room = selectors.get_room_for_member(room_id, request.user)
    room_url = reverse("chat:room", args=[room.pk])

    if request.method == "POST":
        try:
            message = services.send_message(room, request.user, request.POST.get("content", ""))
        except services.ChatError as exc:
            if _wants_json(request):
                return JsonResponse({"ok": False, "error": str(exc)}, status=400)
            messages.error(request, str(exc))
        else:
            payload = services.broadcast_message(message)
            if _wants_json(request):
                return JsonResponse({"ok": True, "message": payload})
        return redirect(f"{room_url}#chat-bottom")

    # 메시지 조각 (HTMX/JS): ?before=<id> 이전 대화 더 불러오기 · ?after=<id> 재연결 후 놓친 메시지
    before, after = request.GET.get("before"), request.GET.get("after")
    if (before or after) and (_is_htmx(request) or _wants_html_fragment(request)):
        try:
            before_id = int(before) if before else None
            after_id = int(after) if after else None
        except ValueError:
            return HttpResponse(status=400)
        if after_id is not None:
            chunk, has_more = selectors.room_messages_after(room, after_id), False
            # 놓친 사이에 온 상대 메시지도 지금 보고 있으니 읽음 처리
            read_ids = services.mark_room_read(room, request.user)
            services.broadcast_read(room.pk, request.user.pk, read_ids)
        else:
            chunk, has_more = selectors.room_messages(room, before_id=before_id)
        return render(
            request,
            "chat/partials/messages.html",
            {"room": room, "entries": build_entries(chunk, request.user, room), "has_more": has_more},
        )

    # 입장 = 상대 메시지 읽음 처리 + 상대 화면에 '읽음' 알림
    read_ids = services.mark_room_read(room, request.user)
    services.broadcast_read(room.pk, request.user.pk, read_ids)

    chunk, has_more = selectors.room_messages(room)
    partner = room.other_user(request.user)
    product = room.product
    is_seller = request.user.pk == room.seller_id
    blocked = is_blocked_between(request.user, partner)

    context = {
        "room": room,
        "product": product,
        "partner": partner,
        "is_seller": is_seller,
        "entries": build_entries(chunk, request.user, room),
        "has_more": has_more,
        "blocked": blocked,
        "i_blocked": blocked and has_blocked(request.user, partner),
        "status_choices": Product.Status.choices,
        "ws_path": f"/ws/chat/{room.pk}/",
        "negotiate_url_template": reverse("ai:negotiate", args=[0]),
        "negotiation_template_message": {"id": 0, "pk": 0},
        "max_length": services.MAX_MESSAGE_LENGTH,
        "time_zone": settings.TIME_ZONE,
        # 거래완료 후 이 방 상대와 거래했다면 후기 버튼
        "traded_here": product.status == Product.Status.SOLD and product.buyer_id == room.buyer_id,
    }
    return render(request, "chat/room.html", context)


# ───────────────────────── 채팅 시작 ─────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def chat_start(request, product_id):
    """상품 판매자와 채팅 시작. 이미 방이 있으면 그 방으로 이동. GET 은 확인 화면."""
    product = get_object_or_404(
        Product.objects.select_related("seller", "seller__profile", "region").prefetch_related("images"),
        pk=product_id,
    )
    detail_url = reverse("products:detail", args=[product.pk])

    if product.seller_id == request.user.pk:
        messages.info(request, "내 상품이에요. 채팅 목록에서 이웃의 메시지를 확인해 주세요.")
        return redirect("chat:list")

    existing = product.chat_rooms.filter(buyer=request.user).first()
    if request.method == "GET" and not existing:
        blocked = is_blocked_between(request.user, product.seller)
        return render(request, "chat/start.html", {"product": product, "blocked": blocked})

    try:
        room, _created = services.get_or_create_room(product, request.user)
    except services.ChatError as exc:
        messages.error(request, str(exc))
        return redirect(detail_url)
    return redirect("chat:room", room.pk)


# ───────────────────────── 읽음 처리 ─────────────────────────


@login_required
@require_POST
def mark_read(request, room_id):
    """상대 메시지 읽음 처리 (WebSocket 이 끊겼을 때 JS 대체 경로)."""
    room = selectors.get_room_for_member(room_id, request.user)
    read_ids = services.mark_room_read(room, request.user)
    services.broadcast_read(room.pk, request.user.pk, read_ids)
    if _is_htmx(request) or _wants_json(request):
        return JsonResponse({"ok": True, "message_ids": read_ids})
    return redirect("chat:room", room.pk)
