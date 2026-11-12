"""(4) 가격 협상: 키워드 감지(AI 없음) + 판매자용 답장 초안 3개 생성(Gemini)."""

from __future__ import annotations

import re

from apps.ai import client as ai_client
from apps.ai.cache import AIResult, cached_call
from apps.ai.client import AIServiceError, MSG_INVALID
from apps.ai.models import AIFeature
from apps.ai.prompts import negotiation as P

HISTORY_SIZE = 10

# 감지/추출에 쓰는 최대 글자 수 (긴 메시지로 CPU 를 오래 잡지 않게)
MAX_SCAN_CHARS = 500

# 숫자 덩어리의 '맨 앞'에서만 매치가 시작되게 하는 가드.
# 이게 없으면 긴 숫자열의 모든 위치에서 재시도해 시간이 제곱으로 늘어난다.
_NUM_START = r"(?<![\d.,])"

# 금액 표현: "35만원", "35만 5천원", "2.5만", "355,000원", "25000원", "5천원"
_PRICE_EXPR = (
    r"(?:(?<!\d)만\s*원"
    rf"|{_NUM_START}\d+(?:\.\d+)?\s*만\s*(?:\d\s*천)?\s*원?"
    rf"|{_NUM_START}\d{{1,3}}(?:,\d{{3}})+\s*원?"
    rf"|{_NUM_START}\d{{4,}}\s*원?"
    rf"|{_NUM_START}\d\s*천\s*원)"
)

NEGOTIATION_RE = re.compile(
    r"깎|네고|nego|에누리|할인|디씨|\bdc\b|싸게|저렴하게|"
    r"가격\s*(?:좀\s*)?(?:조정|조절|협상|협의|제안|내려|낮춰)|얼마까지|"
    r"(?:조금|좀|살짝)\s*(?:만\s*)?(?:빼|내려|낮춰)|빼\s*(?:주|줄|줘)|"
    rf"{_PRICE_EXPR}\s*(?:에|으로|로|까지|이면|면)?\s*(?:는|도)?\s*"
    r"(?:가능|안\s*될|안\s*되|되나|될까|돼요|되요|되나요|어때|어떠|해\s*주|해주|주실|팔아|파실|구매|살게|살\s*수)",
    re.IGNORECASE,
)

_MAN_RE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*만\s*(?:(\d)\s*천)?")
_COMMA_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{4,})\s*원?")
_CHEON_RE = re.compile(r"(?<![\d만])(\d)\s*천\s*원")
# 금액 바로 뒤에 오면 '제시가'가 아니라 '깎아 달라는 금액'으로 본다. 예) "2만원 빼서", "5천원만 빼주세요"
_DISCOUNT_AFTER_RE = re.compile(r"\s*원?\s*(?:만|정도|쯤|만큼)?\s*(?:빼|깎|할인|에누리|디씨|dc|내려|낮춰)", re.IGNORECASE)


def detect_negotiation(text: str) -> bool:
    """메시지가 가격 협상 요청인지 키워드/금액 패턴으로 판별 (AI 호출 없음)."""
    text = (text or "")[:MAX_SCAN_CHARS]
    if not text.strip():
        return False
    return bool(NEGOTIATION_RE.search(text))


def _amounts(text: str) -> list[tuple[int, int, int]]:
    """메시지 속 금액 후보 (시작 위치, 끝 위치, 원 단위 값)."""
    found = []
    for match in _MAN_RE.finditer(text):
        value = float(match.group(1)) * 10_000 + int(match.group(2) or 0) * 1_000
        found.append((match.start(), match.end(), int(value)))
    for match in _COMMA_RE.finditer(text):
        found.append((match.start(), match.end(), int(match.group(1).replace(",", ""))))
    for match in _CHEON_RE.finditer(text):
        found.append((match.start(), match.end(), int(match.group(1)) * 1_000))
    return sorted(c for c in found if c[2] > 0)


def extract_offer_price(text: str, list_price: int | None = None) -> int | None:
    """구매자가 제시한 가격을 원 단위 정수로 추정 (없으면 None).

    "2만원 빼 주세요"처럼 할인액이면 판매가에서 뺀 값을 쓰고, 판매가를 모르면 None.
    판매가 이상인 금액은 제시가로 보지 않는다.
    """
    text = (text or "")[:MAX_SCAN_CHARS]
    candidates = _amounts(text)
    if not candidates:
        return None
    start, end, value = candidates[0]
    if _DISCOUNT_AFTER_RE.match(text, end):
        if not list_price:
            return None
        value = list_price - value
    if value <= 0 or (list_price and value >= list_price):
        return None
    return value


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
    offered = extract_offer_price(message.content, list_price=product.price)
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
