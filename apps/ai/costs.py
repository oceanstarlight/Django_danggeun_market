"""AI 호출 비용 추정 (토큰 사용량 × 단가).

단가는 gemini-3.5-flash-lite 표준 유료 티어 공개가 기준(USD / 1M 토큰, 2026-11 확인).
실제 청구 단가는 Google AI Studio 콘솔 기준이며, settings 로 덮어쓸 수 있다.
"""

from django.conf import settings

DEFAULT_INPUT_PER_MTOK = 0.30
DEFAULT_OUTPUT_PER_MTOK = 2.50
DEFAULT_KRW_PER_USD = 1400


def estimate_cost_usd(prompt_tokens, output_tokens) -> float | None:
    """토큰 수 → 추정 비용(USD). 토큰 정보가 없으면 None (캐시 적중 = 0)."""
    if prompt_tokens is None and output_tokens is None:
        return None
    rate_in = getattr(settings, "AI_PRICE_INPUT_PER_MTOK", DEFAULT_INPUT_PER_MTOK)
    rate_out = getattr(settings, "AI_PRICE_OUTPUT_PER_MTOK", DEFAULT_OUTPUT_PER_MTOK)
    return ((prompt_tokens or 0) * rate_in + (output_tokens or 0) * rate_out) / 1_000_000


def usd_to_krw(usd: float | None) -> float | None:
    if usd is None:
        return None
    return usd * getattr(settings, "AI_KRW_PER_USD", DEFAULT_KRW_PER_USD)
