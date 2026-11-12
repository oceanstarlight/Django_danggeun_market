"""GeminiClient 예외 변환 · JSON 파싱 · cached_call 캐시/로그."""

from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from apps.ai import client as ai_client
from apps.ai.cache import cached_call, make_input_hash
from apps.ai.client import AIServiceError, AIUnavailableError, GeminiClient, parse_json_text
from apps.ai.models import AIFeature, AIResultCache, AIUsageLog

from .helpers import usage


def fake_response(text='{"a": 1}', prompt=10, output=5, thoughts=None, finish="STOP"):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=prompt, candidates_token_count=output,
                                       thoughts_token_count=thoughts, total_token_count=prompt + output),
        model_version="gemini-test",
        candidates=[SimpleNamespace(finish_reason=finish)],
    )


class APIErr(Exception):
    def __init__(self, code):
        super().__init__(f"api error {code}")
        self.code = code


class ReadTimeout(Exception):
    pass


def client_with(*effects):
    """SDK 를 흉내낸 GeminiClient (generate_content 가 effects 를 차례로 반환/발생)."""
    gc = GeminiClient(api_key="test-key", model="gemini-test")
    sdk = mock.Mock()
    sdk.models.generate_content.side_effect = list(effects)
    gc._sdk = sdk
    return gc, sdk


@override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-test")
class GeminiClientTests(TestCase):
    def test_success_returns_dict_and_usage(self):
        gc, sdk = client_with(fake_response('{"title": "아이폰"}', prompt=30, output=12, thoughts=3))
        data, use = gc.generate_json("prompt", images=[(b"img", "image/jpeg")], schema={"type": "OBJECT"})
        self.assertEqual(data, {"title": "아이폰"})
        self.assertEqual(use.prompt_tokens, 30)
        self.assertEqual(use.output_tokens, 15)  # thinking 토큰 포함
        self.assertIsNotNone(use.latency_ms)
        config = sdk.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(len(sdk.models.generate_content.call_args.kwargs["contents"]), 2)

    def test_missing_key_raises_unavailable(self):
        with self.assertRaises(AIUnavailableError):
            GeminiClient(api_key="")

    def test_invalid_json_raises_friendly_error(self):
        gc, _ = client_with(fake_response("이건 JSON 이 아니에요"))
        with self.assertRaises(AIServiceError) as ctx:
            gc.generate_json("p")
        self.assertIn("이해하지 못했어요", ctx.exception.user_message)

    def test_fenced_json_is_recovered(self):
        self.assertEqual(parse_json_text('```json\n{"x": 2}\n```'), {"x": 2})
        self.assertEqual(parse_json_text('결과: {"x": 3} 입니다'), {"x": 3})
        with self.assertRaises(AIServiceError):
            parse_json_text("[1, 2]")

    def test_empty_blocked_response(self):
        gc, _ = client_with(fake_response(text="", finish="SAFETY"))
        with self.assertRaises(AIServiceError) as ctx:
            gc.generate_json("p")
        self.assertIn("답하기 어렵", ctx.exception.user_message)

    def test_timeout_is_converted(self):
        gc, sdk = client_with(ReadTimeout("read timed out"))
        with self.assertRaises(AIServiceError) as ctx:
            gc.generate_json("p")
        self.assertIn("늦어지고", ctx.exception.user_message)
        self.assertEqual(sdk.models.generate_content.call_count, 1)  # 타임아웃은 재시도 안 함

    @mock.patch("apps.ai.client.time.sleep")
    def test_retry_once_on_server_error(self, _sleep):
        gc, sdk = client_with(APIErr(503), fake_response('{"ok": true}'))
        data, _ = gc.generate_json("p")
        self.assertEqual(data, {"ok": True})
        self.assertEqual(sdk.models.generate_content.call_count, 2)

    @mock.patch("apps.ai.client.time.sleep")
    def test_rate_limit_message_after_retry(self, _sleep):
        gc, _ = client_with(APIErr(429), APIErr(429))
        with self.assertRaises(AIServiceError) as ctx:
            gc.generate_json("p")
        self.assertIn("요청이 많아", ctx.exception.user_message)

    def test_auth_error_is_unavailable(self):
        gc, _ = client_with(APIErr(403))
        with self.assertRaises(AIUnavailableError):
            gc.generate_json("p")

    def test_get_client_blocked_during_tests(self):
        with self.assertRaises(AIUnavailableError):
            ai_client.get_client()


@override_settings(GEMINI_MODEL="gemini-test")
class CachedCallTests(TestCase):
    def test_miss_then_hit(self):
        fn = mock.Mock(return_value=({"v": 1}, usage(prompt=100, output=50)))
        first = cached_call(AIFeature.DESCRIPTION, ["v1", "prompt", b"img"], fn)
        second = cached_call(AIFeature.DESCRIPTION, ["v1", "prompt", b"img"], fn)
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(second.data, {"v": 1})
        self.assertEqual(fn.call_count, 1)
        entry = AIResultCache.objects.get()
        self.assertEqual(entry.hit_count, 1)
        self.assertEqual(len(entry.input_hash), 64)
        logs = list(AIUsageLog.objects.order_by("pk"))
        self.assertEqual([log.cached for log in logs], [False, True])
        self.assertEqual(logs[0].prompt_tokens, 100)
        self.assertIsNone(logs[1].prompt_tokens)

    def test_different_input_or_model_misses(self):
        fn = mock.Mock(return_value=({"v": 1}, usage()))
        cached_call(AIFeature.DESCRIPTION, ["a"], fn)
        cached_call(AIFeature.DESCRIPTION, ["b"], fn)
        cached_call(AIFeature.VISION, ["a"], fn)
        cached_call(AIFeature.DESCRIPTION, ["a"], fn, model_name="other-model")
        self.assertEqual(fn.call_count, 4)
        self.assertEqual(AIResultCache.objects.count(), 4)

    def test_hash_separates_part_boundaries(self):
        self.assertNotEqual(
            make_input_hash("F", "m", ["ab", "c"]), make_input_hash("F", "m", ["a", "bc"])
        )

    def test_refresh_bypasses_and_overwrites(self):
        fn = mock.Mock(side_effect=[({"v": 1}, usage()), ({"v": 2}, usage())])
        cached_call(AIFeature.NEGOTIATION, ["x"], fn)
        fresh = cached_call(AIFeature.NEGOTIATION, ["x"], fn, refresh=True)
        self.assertEqual(fresh.data, {"v": 2})
        self.assertEqual(AIResultCache.objects.get().response, {"v": 2})

    def test_failure_is_logged_and_not_cached(self):
        fn = mock.Mock(side_effect=AIServiceError("잠시 후 다시", detail="boom"))
        with self.assertRaises(AIServiceError):
            cached_call(AIFeature.FRAUD, ["x"], fn)
        self.assertFalse(AIResultCache.objects.exists())
        log = AIUsageLog.objects.get()
        self.assertFalse(log.success)
        self.assertEqual(log.error, "boom")
