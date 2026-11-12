"""Gemini API 클라이언트 (google-genai SDK 래퍼).

- 모든 AI 호출은 apps/ai/services/* → 이 모듈을 거친다. (뷰에서 SDK 직접 호출 금지)
- 응답은 항상 JSON(response_mime_type + response_schema)으로 받는다.
- SDK/네트워크 예외는 사용자에게 보여줄 수 있는 한국어 메시지를 가진 AIServiceError 로 바꾼다.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

# 사용자에게 보여줄 기본 문구
MSG_UNAVAILABLE = "지금은 AI 기능을 쓸 수 없어요. 직접 입력해 주세요."
MSG_TIMEOUT = "AI 응답이 늦어지고 있어요. 잠시 후 다시 시도해 주세요."
MSG_RATE_LIMIT = "AI 요청이 많아 잠시 쉬고 있어요. 조금 뒤에 다시 시도해 주세요."
MSG_SERVER = "AI 서버가 잠시 불안정해요. 잠시 후 다시 시도해 주세요."
MSG_BAD_REQUEST = "AI가 이 요청을 처리하지 못했어요. 사진이나 입력을 바꿔서 다시 시도해 주세요."
MSG_INVALID = "AI 응답을 이해하지 못했어요. 다시 시도해 주세요."
MSG_BLOCKED = "AI가 이 내용에는 답하기 어렵대요. 내용을 바꿔서 다시 시도해 주세요."
MSG_NETWORK = "AI 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요."


class AIServiceError(Exception):
    """AI 호출 실패. user_message 는 화면에 그대로 보여줘도 되는 문구."""

    def __init__(self, user_message: str = MSG_SERVER, *, detail: str = ""):
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.detail = detail or user_message


class AIUnavailableError(AIServiceError):
    """API 키가 없거나(또는 테스트 실행 중이라) AI 를 쓸 수 없음."""

    def __init__(self, user_message: str = MSG_UNAVAILABLE, *, detail: str = ""):
        super().__init__(user_message, detail=detail or "AI unavailable")


@dataclass
class AIUsage:
    """호출 1회의 토큰/지연 정보 (AIUsageLog 에 기록)."""

    model: str = ""
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# 재시도할 HTTP 상태 (요청 한도 초과 / 일시적 서버 오류)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class GeminiClient:
    """Gemini generate_content 를 JSON 전용으로 감싼 얇은 클라이언트."""

    def __init__(self, api_key: str | None = None, model: str | None = None, timeout: float | None = None,
                 max_retries: int = 1):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL
        self.timeout = timeout or getattr(settings, "AI_TIMEOUT_SECONDS", 30)
        self.max_retries = max_retries
        if not self.api_key:
            raise AIUnavailableError(detail="GEMINI_API_KEY is empty")
        self._sdk = None  # 지연 생성

    # ── SDK 준비 ─────────────────────────────────────
    def _client(self):
        if self._sdk is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:  # pragma: no cover - requirements 에 포함
                raise AIUnavailableError(detail=f"google-genai 미설치: {exc}") from exc
            self._sdk = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
            )
        return self._sdk

    # ── 공개 API ─────────────────────────────────────
    def generate_json(self, prompt: str, images=(), schema: dict | None = None, temperature: float = 0.4,
                      *, system: str | None = None, max_output_tokens: int = 2048) -> tuple[dict, AIUsage]:
        """프롬프트(+이미지)를 보내고 JSON dict 와 사용량을 돌려준다.

        images: [(bytes, mime_type), ...]
        실패하면 AIServiceError (user_message 포함).
        """
        from google.genai import types

        contents = [types.Part.from_bytes(data=data, mime_type=mime) for data, mime in images]
        contents.append(prompt)
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )

        started = time.monotonic()
        attempt = 0
        while True:
            try:
                response = self._client().models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                break
            except Exception as exc:  # noqa: BLE001 - SDK/HTTP 예외를 모두 사용자 메시지로 변환
                error = self._convert_error(exc)
                retryable = getattr(error, "_retryable", False)
                if retryable and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(0.6 * attempt)
                    continue
                logger.warning("Gemini 호출 실패: %s", error.detail)
                raise error from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        usage = self._usage(response, latency_ms)
        data = self._parse(response)
        return data, usage

    # ── 내부 도우미 ───────────────────────────────────
    def _usage(self, response, latency_ms: int) -> AIUsage:
        meta = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(meta, "prompt_token_count", None)
        output = getattr(meta, "candidates_token_count", None)
        thoughts = getattr(meta, "thoughts_token_count", None)
        if output is not None or thoughts is not None:
            # thinking 토큰도 출력 단가로 과금되므로 합산
            output = (output or 0) + (thoughts or 0)
        return AIUsage(
            model=getattr(response, "model_version", None) or self.model,
            prompt_tokens=prompt_tokens,
            output_tokens=output,
            total_tokens=getattr(meta, "total_token_count", None),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _parse(response) -> dict:
        """응답 텍스트 → dict. 코드펜스/앞뒤 잡음이 있어도 최대한 복구한다."""
        text = None
        try:
            text = response.text
        except Exception:  # noqa: BLE001 - 차단된 응답은 .text 접근 시 예외가 날 수 있음
            text = None
        if not text:
            reason = ""
            try:
                reason = str(response.candidates[0].finish_reason)
            except Exception:  # noqa: BLE001
                pass
            if "SAFETY" in reason or "BLOCK" in reason or "PROHIBITED" in reason:
                raise AIServiceError(MSG_BLOCKED, detail=f"blocked: {reason}")
            raise AIServiceError(MSG_INVALID, detail=f"empty response ({reason or 'no candidates'})")
        return parse_json_text(text)

    @staticmethod
    def _convert_error(exc: Exception) -> AIServiceError:
        """SDK/네트워크 예외 → AIServiceError (재시도 가능 여부 표시)."""
        if isinstance(exc, AIServiceError):
            return exc
        name = type(exc).__name__
        code = getattr(exc, "code", None)
        error: AIServiceError
        if "Timeout" in name or isinstance(exc, TimeoutError):
            error = AIServiceError(MSG_TIMEOUT, detail=f"timeout: {exc}")
        elif isinstance(code, int):
            if code in (401, 403):
                error = AIUnavailableError(detail=f"auth error {code}: {exc}")
            elif code == 429:
                error = AIServiceError(MSG_RATE_LIMIT, detail=f"429: {exc}")
            elif code >= 500:
                error = AIServiceError(MSG_SERVER, detail=f"{code}: {exc}")
            else:
                error = AIServiceError(MSG_BAD_REQUEST, detail=f"{code}: {exc}")
            error._retryable = code in RETRYABLE_STATUS
            return error
        elif "Connect" in name or "Network" in name or isinstance(exc, ConnectionError):
            error = AIServiceError(MSG_NETWORK, detail=f"network: {exc}")
        else:
            error = AIServiceError(MSG_SERVER, detail=f"{name}: {exc}")
        error._retryable = False
        return error


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_text(text: str) -> dict:
    """JSON 문자열을 dict 로. 실패하면 AIServiceError(MSG_INVALID)."""
    cleaned = _FENCE_RE.sub("", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 앞뒤에 설명이 붙은 경우 첫 { ~ 마지막 } 만 다시 시도
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise AIServiceError(MSG_INVALID, detail=f"invalid json: {text[:200]}") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            raise AIServiceError(MSG_INVALID, detail=f"invalid json: {text[:200]}") from None
    if not isinstance(data, dict):
        raise AIServiceError(MSG_INVALID, detail=f"json is not an object: {type(data).__name__}")
    return data


def _live_calls_blocked() -> bool:
    """테스트 실행 중에는 실제 API 를 부르지 않는다 (RUN_LIVE_AI=1 이면 허용).

    Django 테스트 러너는 django.core.mail.outbox 를 만든다 → 이를 테스트 신호로 사용.
    """
    from django.core import mail

    return hasattr(mail, "outbox") and os.getenv("RUN_LIVE_AI") != "1"


_client_cache: dict[tuple, GeminiClient] = {}


def get_client(timeout: float | None = None, max_retries: int = 1) -> GeminiClient:
    """서비스가 쓰는 클라이언트 팩토리 (테스트에서는 이 함수를 mock 한다)."""
    if _live_calls_blocked():
        raise AIUnavailableError(detail="live AI calls are disabled during tests")
    key = (settings.GEMINI_API_KEY, settings.GEMINI_MODEL, timeout, max_retries)
    client = _client_cache.get(key)
    if client is None:
        client = GeminiClient(timeout=timeout, max_retries=max_retries)
        _client_cache[key] = client
    return client


def is_available() -> bool:
    """AI 기능을 쓸 수 있는지 (템플릿에서 버튼 비활성화 등에 사용)."""
    return bool(settings.GEMINI_API_KEY)
