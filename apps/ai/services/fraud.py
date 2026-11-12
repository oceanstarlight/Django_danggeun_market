"""(3) 사기 탐지: 규칙(정규식, AI 호출 없음) + Gemini 판단 → FraudAnalysis.

- check_text_rules(text): 채팅 메시지/판매글 공용 규칙 검사 → 사용자용 설명 목록
- analyze_product(product): 규칙 + 가격 이상치 + AI → FraudAnalysis 저장
  (content_hash 가 같고 AI 판단까지 끝난 분석이 있으면 재분석하지 않는다 = 캐싱)
"""

from __future__ import annotations

import hashlib
import logging
import re
import statistics
from dataclasses import dataclass

from apps.ai import client as ai_client
from apps.ai.cache import cached_call
from apps.ai.client import MSG_INVALID, AIServiceError, AIUnavailableError
from apps.ai.models import AIFeature, FraudAnalysis
from apps.ai.prompts import fraud as P

logger = logging.getLogger(__name__)

# 상품 저장 요청 안에서 호출되므로 짧게 한 번만 시도한다.
# 실패하면 RULE 로 저장되고, 다음 저장/'다시 분석하기' 때 AI 를 다시 시도한다.
FRAUD_AI_TIMEOUT = 8
FRAUD_AI_RETRIES = 0

LEVEL_MEDIUM = 30
LEVEL_HIGH = 70


@dataclass(frozen=True)
class Rule:
    code: str
    message: str  # 사용자에게 보여줄 설명 (해요체)
    weight: int
    pattern: re.Pattern | None = None  # 가격 규칙처럼 텍스트 패턴이 없는 규칙은 None
    negatable: bool = False  # True 면 바로 뒤 부정 표현("카톡은 안 해요")이 붙은 매치는 무시


# 매치 직후 몇 글자 안에 부정 표현이 있으면 '하지 않는다'는 뜻으로 본다
NEGATION_WINDOW = 10
NEGATION_RE = re.compile(
    r"안\s*(?:해|하|함|합|써|쓰|씁|돼|되|됨|됩|받|보내|드려|드립)|않|아니|아닙|없이|없어|없습|불가|금지|사절|노노|"
    r"(?<![a-z])x(?![a-z])|❌|✕",
    re.IGNORECASE,
)
# 공백으로 띄운 숫자 묶음은 근처에 이 단어가 있을 때만 계좌로 본다 (사이즈/치수 오탐 방지)
ACCOUNT_CONTEXT_RE = re.compile(r"계좌|입금|송금|이체|은행|뱅크|예금주")
ACCOUNT_CONTEXT_WINDOW = 15
# 아주 긴 글로 CPU 를 오래 잡지 않게 검사 길이 제한
MAX_RULE_TEXT = 5000


def _re(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


PHONE_RE = _re(r"(?<!\d)01[016789][\s.\-]?\d{3,4}[\s.\-]?\d{4}(?!\d)")
ACCOUNT_RE = _re(r"(?<![\d\-])\d{2,6}[\-\s]\d{2,6}[\-\s]\d{2,8}(?:[\-\s]\d{1,3})?(?![\d\-])")
BANKS = (
    r"국민|신한|우리|하나|농협|기업|카카오\s*뱅크|카뱅|토스\s*뱅크|케이\s*뱅크|새마을|우체국|수협|"
    r"신협|SC제일|씨티|부산|대구|경남|광주|전북|제주"
)
BANK_ACCOUNT_RE = _re(rf"(?:{BANKS})\s*(?:은행)?\s*[:：]?\s*\d[\d\s\-]{{8,30}}\d")

TEXT_RULES: tuple[Rule, ...] = (
    Rule("prepay", "입금을 먼저 요구하는 문구가 있어요", 40, _re(
        r"선\s*입금|선\s*결제|먼저\s*(입금|송금|결제)|입금\s*(먼저|부터)|"
        r"입금\s*(확인\s*)?(후|하시면|해\s*주시면|되면)\s*(바로\s*)?(발송|배송|보내|택배)|"
        r"(계약금|예약금)\s*(먼저|부터|입금)"
    ), negatable=True),
    Rule("messenger", "카톡·텔레그램 등 외부 메신저로 대화를 유도해요", 30, _re(
        r"카톡|카카오\s*톡|kakao\s*talk|오픈\s*채팅|오픈\s*톡|open\.kakao|텔레그램|telegram|t\.me/|"
        r"텔레\s*(아이디|id)|라인\s*(아이디|id|으로\s*연락|추가)|line\s*(id|아이디)|위챗|wechat|왓츠앱|whatsapp"
    ), negatable=True),
    Rule("fake_safe_pay", "안전결제 링크를 사칭하는 수법과 비슷해요", 40, _re(
        r"안전\s*(결제|거래|송금)\s*(링크|사이트|주소|url|페이지)|결제\s*(링크|url)|에스크로|"
        r"(네이버|번개|중고나라|토스|카카오)\s*(페이)?\s*안전\s*(결제|거래)"
    ), negatable=True),
    Rule("personal_info", "신분증·인증번호 같은 개인정보를 요구해요", 40, _re(
        r"(주민\s*(등록)?\s*번호|신분증|인증\s*번호|보안\s*카드|카드\s*번호|여권|계좌\s*비밀번호|otp)"
        r"[^.\n]{0,12}(보내|알려|주세요|필요|요청|찍어|부탁)"
    )),
    Rule("rush_deposit", "빠른 입금을 재촉해요", 20, _re(
        r"(오늘|지금|바로|빨리|급히|서둘러)\s*(안에|중에|까지)?\s*(입금|송금)|선착순\s*입금"
    )),
    Rule("parcel_only", "직거래 없이 택배거래만 고집해요", 15, _re(
        r"택배\s*(거래)?\s*(만|온리|only)|직거래\s*(는\s*)?(불가|안\s*돼|안\s*됩|어려|x\b|힘들)|비대면\s*(거래)?\s*만"
    )),
    Rule("cannot_meet", "만날 수 없다는 이유로 비대면 거래를 유도해요", 15, _re(
        r"(해외|외국|출장|군\s*복무|군대|지방)[^.\n]{0,10}(있어서|중이라|이라서|라서)[^.\n]{0,20}(택배|송금|입금)"
    )),
    Rule("external_url", "외부 링크가 포함돼 있어요", 15, _re(
        r"https?://|www\.|\b[a-z0-9\-]+\.(?:com|net|kr|io|me|ly|xyz|shop|site|link|top|info)\b"
    )),
)

RULE_PHONE = Rule("phone", "개인 연락처로 외부 연락을 유도해요", 20, PHONE_RE)
RULE_ACCOUNT = Rule("account", "계좌번호로 보이는 숫자가 있어요", 35, ACCOUNT_RE)

PREMIUM_RE = _re(
    r"아이폰|iphone|맥북|macbook|아이패드|ipad|갤럭시\s*(s\d|z|폴드|플립|탭)|에어팟|airpods|애플\s*워치|"
    r"플스\s*5|ps5|닌텐도\s*스위치|스위치\s*oled|롤렉스|rolex|샤넬|chanel|루이비통|구찌|에르메스|다이슨|dyson"
)
ACCESSORY_RE = _re(
    r"케이스|필름|케이블|충전기|박스만|공박스|부품|고장|파손|스트랩|거치대|커버|파우치|"
    r"필터|펜슬|컨트롤러|듀얼센스|조이콘|칩|타이틀|게임\s*팩|립스틱|립밤|향수|화장품|지갑|키링|"
    r"공기계|한쪽|유닛|팁|헤드|브러시|리모컨|어댑터|배터리"
)
PREMIUM_LOW_PRICE = 50_000
# 오래된 모델·소품도 많아서 단독으로는 경고(30점)에 닿지 않게 25점
RULE_PREMIUM_CHEAP = Rule("premium_cheap", "고가 상품인데 가격이 비정상적으로 낮아요", 25, PREMIUM_RE)
RULE_BELOW_MARKET = Rule("below_market", "같은 카테고리 시세보다 지나치게 싸요", 25)


def _account_matches(text: str) -> bool:
    """전화번호를 지운 뒤 은행명+숫자, 또는 10~14자리 숫자 묶음이 있으면 계좌로 본다.

    하이픈 없이 공백으로만 띄운 숫자("250 260 270 280")는 근처에 계좌/입금 같은 말이 있을 때만.
    """
    if BANK_ACCOUNT_RE.search(text):
        return True
    without_phone = PHONE_RE.sub(" ", text)
    for match in ACCOUNT_RE.finditer(without_phone):
        digits = re.sub(r"\D", "", match.group())
        if not 10 <= len(digits) <= 14:
            continue
        if "-" in match.group():
            return True
        around = without_phone[max(0, match.start() - ACCOUNT_CONTEXT_WINDOW): match.end() + ACCOUNT_CONTEXT_WINDOW]
        if ACCOUNT_CONTEXT_RE.search(around):
            return True
    return False


def _rule_matches(rule: Rule, text: str) -> bool:
    """규칙 패턴 매치 여부. negatable 규칙은 바로 뒤에 부정 표현이 붙은 매치를 건너뛴다."""
    if not rule.negatable:
        return bool(rule.pattern.search(text))
    for match in rule.pattern.finditer(text):
        if not NEGATION_RE.search(text, match.end(), match.end() + NEGATION_WINDOW):
            return True
    return False


def match_text_rules(text: str) -> list[Rule]:
    """텍스트 규칙 검사 → 걸린 Rule 목록 (순서 = 심각도 순)."""
    text = (text or "")[:MAX_RULE_TEXT]
    if not text.strip():
        return []
    hits = [rule for rule in TEXT_RULES if _rule_matches(rule, text)]
    if _account_matches(text):
        hits.insert(1, RULE_ACCOUNT)
    if PHONE_RE.search(text):
        hits.append(RULE_PHONE)
    return hits


def check_text_rules(text: str) -> list[str]:
    """규칙 기반 위험 문구 검사 (AI 호출 없음). 사용자에게 보여줄 설명 목록을 반환."""
    return [rule.message for rule in match_text_rules(text)]


# ───────────────────────── 상품 분석 ─────────────────────────


def _category_median(product) -> tuple[int | None, int]:
    """같은 카테고리 최근 상품(나눔 제외) 가격 중앙값과 표본 수."""
    from apps.products.models import Product

    prices = list(
        Product.objects.filter(category_id=product.category_id, price__gt=0)
        .exclude(pk=product.pk)
        .order_by("-created_at")
        .values_list("price", flat=True)[:200]
    )
    if len(prices) < 5:
        return None, len(prices)
    return int(statistics.median(prices)), len(prices)


def price_rules(product) -> tuple[list[Rule], str]:
    """가격 이상치 규칙 + AI 에 줄 가격 참고 문장."""
    hits: list[Rule] = []
    price = product.price or 0
    text = f"{product.title} {product.content}"
    if 0 < price < PREMIUM_LOW_PRICE and PREMIUM_RE.search(product.title or "") and not ACCESSORY_RE.search(text):
        hits.append(RULE_PREMIUM_CHEAP)
    median, samples = _category_median(product)
    if median is None:
        context = f"같은 카테고리 비교 데이터가 부족해요({samples}개)."
    else:
        ratio = price / median if median else 1
        context = f"같은 카테고리 최근 {samples}개 가격 중앙값 {median:,}원, 이 상품은 중앙값의 {ratio:.0%}."
        if 0 < price < median * 0.15:
            hits.append(RULE_BELOW_MARKET)
    return hits, context


def content_hash(product) -> str:
    """분석에 쓰이는 필드 + 프롬프트 버전의 해시 (같으면 재분석 불필요)."""
    raw = "\x1f".join(
        [P.VERSION, product.title or "", product.content or "", str(product.price), str(product.category_id),
         product.condition or ""]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def level_for(score: int) -> str:
    if score >= LEVEL_HIGH:
        return FraudAnalysis.RiskLevel.HIGH
    if score >= LEVEL_MEDIUM:
        return FraudAnalysis.RiskLevel.MEDIUM
    return FraudAnalysis.RiskLevel.LOW


def combine_scores(rule_score: int, ai_score: int | None) -> int:
    """규칙 점수와 AI 점수 결합.

    - AI 가 없으면 규칙 점수 그대로
    - AI 점수는 하한(AI 가 본 맥락 신호), 규칙은 절반 가중으로 끌어올림
    - 규칙이 강하게(70+) 걸리면 AI 가 낮게 봐도 규칙 점수 유지
    """
    if ai_score is None:
        return rule_score
    score = max(ai_score, round((rule_score + ai_score) / 2))
    if rule_score >= LEVEL_HIGH:
        score = max(score, rule_score)
    return min(100, max(0, score))


def _parse_ai(data) -> dict:
    """AI 응답 검사·정리 → {"risk_score": 0~100, "reasons": [...]}. 형식이 틀리면 AIServiceError."""
    if not isinstance(data, dict):
        raise AIServiceError(MSG_INVALID, detail=f"fraud not dict: {data!r}"[:300])
    raw_score, reasons = data.get("risk_score"), data.get("reasons")
    if isinstance(raw_score, bool) or not isinstance(reasons, list):
        raise AIServiceError(MSG_INVALID, detail=f"fraud bad shape: {data!r}"[:300])
    try:
        score = int(round(float(raw_score)))
    except (TypeError, ValueError) as exc:
        raise AIServiceError(MSG_INVALID, detail=f"fraud bad score: {raw_score!r}"[:300]) from exc
    if not 0 <= score <= 100:
        raise AIServiceError(MSG_INVALID, detail=f"fraud score out of range: {score}")
    cleaned = [" ".join(str(r).split())[:80] for r in reasons if str(r).strip()]
    return {"risk_score": score, "reasons": cleaned[:3]}


def _ai_judgement(product, rule_hits: list[str], price_context: str, *, user=None, refresh=False):
    """Gemini 판단 → {"risk_score", "reasons"} 또는 None(AI 불가/실패)."""
    prompt = P.build_prompt(
        title=product.title,
        content=product.content,
        price=product.price,
        category_name=getattr(product.category, "name", ""),
        condition_label=product.get_condition_display(),
        rule_hits=rule_hits,
        price_context=price_context,
    )

    def call():
        return ai_client.get_client(timeout=FRAUD_AI_TIMEOUT, max_retries=FRAUD_AI_RETRIES).generate_json(
            prompt, schema=P.SCHEMA, temperature=0.1, system=P.SYSTEM, max_output_tokens=512
        )

    try:
        # 형식이 틀린 응답은 캐시하지 않는다 (_parse_ai 가 AIServiceError)
        result = cached_call(
            AIFeature.FRAUD, [P.VERSION, P.SYSTEM, prompt], call, user=user, refresh=refresh, validate=_parse_ai
        )
    except AIServiceError as exc:
        log = logger.debug if isinstance(exc, AIUnavailableError) else logger.info
        log("사기 탐지 AI 생략 (product=%s): %s", product.pk, exc.detail)
        return None
    return _parse_ai(result.data)


def analyze_product(product, *, force: bool = False, user=None) -> FraudAnalysis | None:
    """상품 사기 위험 분석 → FraudAnalysis (상품당 1개, 갱신).

    force=True 면 내용이 같아도 AI 까지 다시 분석한다 ('다시 분석' 버튼).
    """
    if product is None or product.pk is None:
        return None
    digest = content_hash(product)
    existing = FraudAnalysis.objects.filter(product=product).first()
    # 같은 내용 + AI 판단까지 끝난 결과면 그대로 재사용 (RULE 만 있으면 AI 를 다시 시도)
    if existing and not force and existing.content_hash == digest and existing.source != FraudAnalysis.Source.RULE:
        return existing

    text_hits = match_text_rules(f"{product.title}\n{product.content}")
    extra_hits, price_context = price_rules(product)
    rules = text_hits + extra_hits
    rule_messages = [rule.message for rule in rules]
    rule_score = min(100, sum(rule.weight for rule in rules))

    ai = _ai_judgement(product, rule_messages, price_context, user=user or product.seller, refresh=force)
    score = combine_scores(rule_score, ai["risk_score"] if ai else None)
    level = level_for(score)

    if ai is None:
        source = FraudAnalysis.Source.RULE
        reasons = rule_messages[:3]
    else:
        source = FraudAnalysis.Source.RULE_AI if rules else FraudAnalysis.Source.AI
        reasons = ai["reasons"] or rule_messages[:3]

    analysis, _created = FraudAnalysis.objects.update_or_create(
        product=product,
        defaults={
            "content_hash": digest,
            "risk_level": level,
            "risk_score": score,
            "reasons": reasons,
            "rule_hits": rule_messages,
            "source": source,
        },
    )
    return analysis
