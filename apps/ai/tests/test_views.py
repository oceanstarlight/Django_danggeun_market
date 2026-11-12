"""AI 뷰: 로그인/POST 전용 · 권한(403/404) · partial 응답 · 실패 안내."""

import json
import os
import unittest

from django.test import TestCase
from django.urls import reverse

from apps.ai.client import AIServiceError
from apps.ai.models import AIUsageLog, FraudAnalysis
from apps.chat.models import ChatMessage, ChatRoom

from .helpers import AIDataMixin, fake_gemini, make_upload

HX = {"HTTP_HX_REQUEST": "true"}


class DescribeViewTests(AIDataMixin, TestCase):
    url = reverse("ai:describe")
    OK = {"title": "아이패드 에어 5세대", "content": "상태 좋아요.\n\n[구매 시기]에 샀어요.", "suggested_tags": ["아이패드"]}

    def test_login_required_and_post_only(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_success_renders_result_partial(self):
        self.client.force_login(self.seller)
        with fake_gemini(self.OK) as client:
            response = self.client.post(self.url, {
                "images": [make_upload("a.png"), make_upload("b.png", (0, 0, 200)), make_upload("c.png")],
                "keywords": "아이패드 에어 64GB",
                "category": str(self.digital.pk),
            })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ai/partials/description_result.html")
        self.assertContains(response, "아이패드 에어 5세대")
        self.assertContains(response, 'data-ai-apply="description"')
        self.assertContains(response, 'type="application/json"')
        self.assertEqual(len(client.generate_json.call_args.kwargs["images"]), 2)  # 앞 2장만
        log = AIUsageLog.objects.get()
        self.assertEqual(log.user, self.seller)
        self.assertTrue(log.success)

    def test_category_slug_also_accepted(self):
        self.client.force_login(self.seller)
        with fake_gemini(self.OK) as client:
            self.client.post(self.url, {"keywords": "책", "category": "books"})
        self.assertIn("도서", client.generate_json.call_args.args[0])

    def test_no_input_returns_400_error_partial(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 400)
        self.assertTemplateUsed(response, "ai/partials/error.html")
        self.assertContains(response, "사진을 올리거나 키워드를 입력해 주세요", status_code=400)

    def test_invalid_image_is_friendly(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.seller)
        bad = SimpleUploadedFile("x.png", b"not image", content_type="image/png")
        response = self.client.post(self.url, {"images": [bad]})
        self.assertContains(response, "사진 파일을 읽지 못했어요", status_code=400)

    def test_ai_failure_htmx_gets_200_error_partial(self):
        self.client.force_login(self.seller)
        with fake_gemini(side_effect=AIServiceError("AI 서버가 잠시 불안정해요.", detail="503")):
            response = self.client.post(self.url, {"keywords": "아이패드"}, **HX)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI 서버가 잠시 불안정해요.")
        self.assertContains(response, "직접 입력해서 등록할 수 있어요")
        self.assertFalse(AIUsageLog.objects.get().success)

    def test_ai_unavailable_returns_503_for_fetch(self):
        # 테스트 중에는 실제 get_client 가 AIUnavailableError → 키 없음과 같은 경로
        self.client.force_login(self.seller)
        response = self.client.post(self.url, {"keywords": "아이패드"})
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "AI 기능을 쓸 수 없어요", status_code=503)


class RecognizeViewTests(AIDataMixin, TestCase):
    url = reverse("ai:recognize")

    def test_requires_image(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url, {})
        self.assertContains(response, "사진을 1장 이상", status_code=400)

    def test_success_and_low_confidence_warning(self):
        self.client.force_login(self.seller)
        data = {"category_slug": "digital", "title": "아이폰 13", "condition": "GOOD", "confidence": 0.35, "notes": "흐릿해요."}
        with fake_gemini(data):
            response = self.client.post(self.url, {"images": [make_upload()]})
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ai/partials/recognize_result.html")
        self.assertContains(response, "디지털기기")
        self.assertContains(response, "확신도가 낮아요")
        self.assertContains(response, 'value="35"')


class NegotiateViewTests(AIDataMixin, TestCase):
    DRAFTS = {"drafts": [
        {"tone": "정중한 거절", "text": "죄송해요, 가격은 그대로 받고 싶어요.", "price": 450000},
        {"tone": "소폭 양보", "text": "43만원까지 가능해요.", "price": 430000},
        {"tone": "역제안", "text": "42만원에 오늘 직거래 어떠세요?", "price": 420000},
    ]}

    def setUp(self):
        self.product = self.make_product()
        self.room = ChatRoom.objects.create(product=self.product, seller=self.seller, buyer=self.buyer)
        self.buyer_msg = ChatMessage.objects.create(room=self.room, sender=self.buyer, content="40만원에 될까요?")
        self.seller_msg = ChatMessage.objects.create(room=self.room, sender=self.seller, content="음 생각해 볼게요")
        self.url = reverse("ai:negotiate", args=[self.buyer_msg.pk])

    def test_permissions(self):
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(self.url).status_code, 404)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(reverse("ai:negotiate", args=[999999])).status_code, 404)

    def test_seller_own_message_rejected(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("ai:negotiate", args=[self.seller_msg.pk]), **HX)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "구매자가 보낸 메시지에만")

    def test_seller_gets_three_drafts(self):
        self.client.force_login(self.seller)
        with fake_gemini(self.DRAFTS):
            response = self.client.post(self.url, **HX)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ai/partials/negotiation_drafts.html")
        self.assertContains(response, 'data-ai-fill="#chat-input"', count=3)
        self.assertContains(response, "제시가 400,000원")
        self.assertContains(response, "43만원까지 가능해요.")

    def test_regenerate_flag(self):
        self.client.force_login(self.seller)
        with fake_gemini(self.DRAFTS, self.DRAFTS) as client:
            self.client.post(self.url, **HX)
            self.client.post(self.url, {"regenerate": "1"}, **HX)
        self.assertEqual(client.generate_json.call_count, 2)

    def test_button_partial_contract(self):
        from django.template.loader import render_to_string

        html = render_to_string("ai/partials/negotiation_button.html", {"message": {"id": 0, "pk": 0}})
        self.assertIn('hx-post="/ai/negotiate/0/"', html)
        self.assertIn('hx-target="next div"', html)


class FraudRefreshViewTests(AIDataMixin, TestCase):
    SCAM = {"content": "선입금 후 발송해요. 카톡 scam77 로 연락주세요.", "title": "아이폰 15 미개봉", "price": 200000}

    def setUp(self):
        self.product = self.make_product(**self.SCAM)
        self.url = reverse("ai:fraud_refresh", args=[self.product.pk])

    def test_permissions(self):
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(reverse("ai:fraud_refresh", args=[999999])).status_code, 404)

    def test_seller_refresh_redirects_with_message(self):
        self.client.force_login(self.seller)
        with fake_gemini({"risk_score": 90, "risk_level": "HIGH", "reasons": ["선입금을 요구해요"]}):
            response = self.client.post(self.url, follow=True)
        self.assertRedirects(response, reverse("products:detail", args=[self.product.pk]))
        analysis = FraudAnalysis.objects.get(product=self.product)
        self.assertEqual(analysis.risk_level, "HIGH")
        self.assertContains(response, "다시 분석했어요")
        self.assertContains(response, "판매글에서 의심 신호가 감지됐어요")
        self.assertContains(response, "다시 분석하기")

    def test_staff_htmx_gets_banner_and_toast(self):
        self.client.force_login(self.staff)
        with fake_gemini(side_effect=AIServiceError("x")):
            response = self.client.post(self.url, **HX)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ai/partials/fraud_banner.html")
        self.assertContains(response, 'id="fraud-banner"')
        self.assertContains(response, "입금을 먼저 요구하는")
        toast = json.loads(response["HX-Trigger"])["showToast"]
        self.assertEqual(toast["level"], "warning")  # AI 실패 → 규칙만

    def test_low_risk_htmx_clears_banner(self):
        product = self.make_product()
        self.client.force_login(self.seller)
        with fake_gemini({"risk_score": 3, "risk_level": "LOW", "reasons": []}):
            response = self.client.post(reverse("ai:fraud_refresh", args=[product.pk]), **HX)
        self.assertContains(response, 'id="fraud-banner"')
        self.assertNotContains(response, "alert")
        self.assertEqual(json.loads(response["HX-Trigger"])["showToast"]["level"], "success")


class FraudBannerTemplateTests(AIDataMixin, TestCase):
    def test_visitor_sees_warning_without_refresh_button(self):
        product = self.make_product()
        FraudAnalysis.objects.create(product=product, content_hash="x" * 64, risk_level="MEDIUM", risk_score=45,
                                     reasons=["외부 메신저로 연락을 유도해요"], rule_hits=["외부 메신저"])
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertContains(response, "의심 신호가 감지됐어요")
        self.assertContains(response, "외부 메신저로 연락을 유도해요")
        self.assertContains(response, "alert-warning")
        self.assertNotContains(response, reverse("ai:fraud_refresh", args=[product.pk]))

    def test_low_hidden(self):
        product = self.make_product()
        FraudAnalysis.objects.create(product=product, content_hash="x" * 64, risk_level="LOW", risk_score=5)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertNotContains(response, "의심 신호가 감지됐어요")


class ProductFormPanelTests(AIDataMixin, TestCase):
    def test_panel_rendered_in_product_form(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("products:create"))
        self.assertTemplateUsed(response, "ai/partials/product_form_ai_panel.html")
        self.assertContains(response, 'data-describe-url="/ai/describe/"')
        self.assertContains(response, 'data-recognize-url="/ai/recognize/"')
        self.assertContains(response, "js/ai.js")
        self.assertNotContains(response, 'name="keywords"')  # 상품 폼에 섞여 전송되지 않게


@unittest.skipUnless(os.getenv("RUN_LIVE_AI") == "1", "RUN_LIVE_AI=1 일 때만 실제 Gemini 호출")
class LiveSmokeTests(AIDataMixin, TestCase):
    """실제 API 스모크 (기본 skip). GEMINI_API_KEY 필요."""

    def test_live_description(self):
        from apps.ai.services import description

        result = description.generate_description([], "에어팟 프로 2세대, 6개월 사용, 케이스 포함", self.digital)
        self.assertTrue(result.data["title"])
        self.assertTrue(result.data["content"])
