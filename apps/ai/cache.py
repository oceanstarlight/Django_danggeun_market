"""AI 결과 캐시 + 사용량 기록.

같은 기능 · 같은 모델 · 같은 입력(프롬프트 버전/텍스트/이미지 바이트)이면
sha256 해시가 같으므로 AIResultCache 에 저장된 응답을 재사용한다 (비용 0, 지연 ~0).
모든 호출(캐시 적중 포함)은 AIUsageLog 에 한 줄씩 남는다.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F

from .client import AIServiceError, AIUsage
from .models import AIResultCache, AIUsageLog

logger = logging.getLogger(__name__)


@dataclass
class AIResult:
    """cached_call 결과."""

    data: dict
    cached: bool = False
    usage: AIUsage = field(default_factory=AIUsage)


def _to_bytes(part) -> bytes:
    if isinstance(part, bytes):
        return part
    if isinstance(part, (bytearray, memoryview)):
        return bytes(part)
    return str(part).encode("utf-8")


def make_input_hash(feature: str, model_name: str, payload_parts) -> str:
    """sha256(feature + model + 각 조각). 조각 경계가 섞이지 않게 길이를 함께 넣는다."""
    digest = hashlib.sha256()
    for part in (feature, model_name, *payload_parts):
        data = _to_bytes(part)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _user_or_none(user):
    return user if getattr(user, "is_authenticated", False) else None


def log_usage(feature, *, user=None, model_name="", cached=False, success=True, usage: AIUsage | None = None,
              error="") -> AIUsageLog | None:
    """AIUsageLog 한 줄 기록. 로그 실패가 기능을 막지 않도록 예외는 삼킨다."""
    usage = usage or AIUsage()
    try:
        return AIUsageLog.objects.create(
            user=_user_or_none(user),
            feature=feature,
            model_name=model_name or usage.model or settings.GEMINI_MODEL,
            cached=cached,
            success=success,
            prompt_tokens=usage.prompt_tokens,
            output_tokens=usage.output_tokens,
            latency_ms=usage.latency_ms,
            error=error[:1000],
        )
    except Exception:  # noqa: BLE001
        logger.exception("AIUsageLog 기록 실패")
        return None


def cached_call(feature, payload_parts, fn, *, user=None, model_name: str | None = None,
                refresh: bool = False, validate=None) -> AIResult:
    """캐시를 확인하고 없으면 fn() 을 호출해 저장한다.

    feature: AIFeature 값 · payload_parts: 해시에 들어갈 str/bytes 목록
    fn: 인자 없는 함수 → (dict, AIUsage). AIServiceError 를 던질 수 있다.
    refresh=True 면 캐시를 건너뛰고 새로 생성해서 덮어쓴다 ('다시 생성').
    validate: dict 를 받아 형식이 틀리면 AIServiceError 를 던지는 함수(선택).
      잘못된 응답은 캐시에 저장하지 않고, 예전에 저장된 잘못된 캐시는 무시한다.
    """
    model_name = model_name or settings.GEMINI_MODEL
    input_hash = make_input_hash(feature, model_name, payload_parts)
    lookup = {"feature": feature, "input_hash": input_hash, "model_name": model_name}

    if not refresh:
        hit = AIResultCache.objects.filter(**lookup).only("pk", "response").first()
        if hit is not None and validate is not None:
            try:
                validate(hit.response)
            except AIServiceError:
                hit = None  # 형식이 틀린 옛 캐시 → 새로 호출해서 덮어쓴다
        if hit is not None:
            AIResultCache.objects.filter(pk=hit.pk).update(hit_count=F("hit_count") + 1)
            usage = AIUsage(model=model_name, latency_ms=0)
            log_usage(feature, user=user, model_name=model_name, cached=True, usage=usage)
            return AIResult(data=hit.response, cached=True, usage=usage)

    try:
        data, usage = fn()
        if validate is not None:
            validate(data)
    except AIServiceError as exc:
        log_usage(feature, user=user, model_name=model_name, success=False, error=exc.detail)
        raise

    _store(lookup, data)
    log_usage(feature, user=user, model_name=model_name, usage=usage)
    return AIResult(data=data, cached=False, usage=usage)


def _store(lookup: dict, data: dict) -> None:
    """캐시 저장 (동시 요청으로 같은 키가 생겨도 안전하게 덮어쓰기)."""
    try:
        with transaction.atomic():
            AIResultCache.objects.update_or_create(**lookup, defaults={"response": data})
    except IntegrityError:
        AIResultCache.objects.filter(**lookup).update(response=data)
    except Exception:  # noqa: BLE001 - 캐시 저장 실패는 기능에 영향 없음
        logger.exception("AIResultCache 저장 실패")
