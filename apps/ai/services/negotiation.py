"""(4) 가격 협상: 키워드 감지(AI 없음) + 판매자용 답장 초안 3개 생성(Gemini)."""

from __future__ import annotations

import re

from apps.ai import client as ai_client
from apps.ai.cache import AIResult, cached_call
from apps.ai.client import AIServiceError, MSG_INVALID
from apps.ai.models import AIFeature
from apps.ai.prompts import negotiation as P

HISTORY_SIZE = 10

# 금액 표현: "35만원", "35만 5천원", "2.5만", "355,000원", "25000원", "5천원"
_PRICE_EXPR = r"(?:(?<!\d)만\s*원|\d+(?:\.\d+)?\s*만\s*(?:\d\s*천)?\s*원?|\d{1,3}(?:,\d{3})+\s*원?|\d{4,}\s*원?|\d\s*천\s*원)"

NEGOTIATION_RE = re.compile(
    r"깎|네고|nego|에누리|할인|디씨|\bdc\b|싸게|저렴하게|"
    r"가격\s*(?:좀\s*)?(?:조정|조절|협상|협의|제안|내려|낮춰)|얼마까지|"
    r"(?:조금|좀|살짝)\s*(?:만\s*)?(?:빼|내려|낮춰)|빼\s*(?:주|줄|줘)|"
    rf"{_PRICE_EXPR}\s*(?:에|으로|로|까지|이면|면)?\s*(?:는|도)?\s*"
    r"(?:가능|안\s*될|안\s*되|되나|될까|돼요|되요|되나요|어때|어떠|해\s*주|해주|주실|팔아|파실|구매|살게|살\s*수)",
    re.IGNORECASE,
)

_MAN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*만\s*(?:(\d)\s*천)?")
_COMMA_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{4,})\s*원?")
_CHEON_RE = re.compile(r"(?<![\d만])(\d)\s*천\s*원")


def detect_negotiation(text: str) -> bool:
    """메시지가 가격 협상 요청인지 키워드/금액 패턴으로 판별 (AI 호출 없음)."""
    if not text or not text.strip():
        return False
    return bool(NEGOTIATION_RE.search(text))


def extract_offer_price(text: str) -> int | None:
    """메시지 속 첫 금액을 원 단위 정수로 (없으면 None)."""
    text = text or ""
    candidates = []
    for match in _MAN_RE.finditer(text):
        value = float(match.group(1)) * 10_000 + int(match.group(2) or 0) * 1_000
        candidates.append((match.start(), int(value)))
    for match in _COMMA_RE.finditer(text):
        candidates.append((match.start(), int(match.group(1).replace(",", ""))))
    for match in _CHEON_RE.finditer(text):
        candidates.append((match.start(), int(match.group(1)) * 1_000))
    candidates = [c for c in candidates if c[1] > 0]
    if not candidates:
        return None
    return min(candidates)[1]


def _history(message) -> list[tuple[str, str]]:
    """대상 메시지 직전까지 최근 대화 (오래된 → 최신)."""
    room = message.room
    qs = (
        room.messages.filter(created_at__lte=message.created_at)
        .exclude(pk=message.pk)
        .only("sender_id", "content", "created_at")
        .order_by("-created_at", "-pk")[:HISTORY_SIZE]
    )
    rows = list(qs)[::-1]
    return [("판매자" if m.sender_id == room.seller_id else "구매자", m.content[:300]) for m in rows]


def normalize(data: dict, *, list_price: int) -> dict:
    """drafts 를 톤 순서대로 3개로 정리. 금액은 판매가를 넘지 않게."""
    raw = data.get("drafts") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raise AIServiceError(MSG_INVALID, detail=f"drafts missing: {data!r}"[:300])
    by_tone: dict[str, dict] = {}
    leftovers = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text") or "").split())[:200]
        if not text:
            continue
        try:
            price = int(item["price"]) if item.get("price") is not None else None
        except (TypeError, ValueError):
            price = None
        if price is not None and (price <= 0 or price > list_price):
            price = None
        draft = {"tone": item.get("tone"), "text": text, "price": price}
        if draft["tone"] in P.TONES and draft["tone"] not in by_tone:
            by_tone[draft["tone"]] = draft
        else:
            leftovers.append(draft)
    drafts = []
    for tone in P.TONES:
        draft = by_tone.get(tone) or (leftovers.pop(0) if leftovers else None)
        if draft:
            drafts.append({**draft, "tone": tone})
    if not drafts:
        raise AIServiceError(MSG_INVALID, detail="no usable drafts")
    return {"drafts": drafts}


def generate_drafts(message, *, user=None, regenerate: bool = False) -> AIResult:
    """구매자 메시지에 대한 판매자 답장 초안 3개.

    반환: AIResult(data={"drafts": [{tone, text, price}], "offered_price": int|None}, cached, usage)
    """
    product = message.room.product
    offered = extract_offer_price(message.content)
    prompt = P.build_prompt(
        title=product.title,
        price=product.price,
        negotiable=product.negotiable,
        condition_label=product.get_condition_display(),
        status_label=product.get_status_display(),
        offered_price=offered,
        history=_history(message),
        target=message.content[:500],
    )
    temperature = 0.9 if regenerate else 0.6

    def call():
        data, usage = ai_client.get_client().generate_json(
            prompt, schema=P.SCHEMA, temperature=temperature, system=P.SYSTEM, max_output_tokens=768
        )
        return normalize(data, list_price=product.price), usage

    result = cached_call(AIFeature.NEGOTIATION, [P.VERSION, P.SYSTEM, prompt], call, user=user, refresh=regenerate)
    result.data = {**result.data, "offered_price": offered}
    return result
