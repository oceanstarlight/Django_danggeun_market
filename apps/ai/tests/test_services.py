"""4개 AI 서비스: 규칙 · 정규화 · 캐싱 (Gemini 는 mock)."""

from django.test import TestCase

from apps.ai.client import AIServiceError, AIUnavailableError
from apps.ai.images import AIInputError, normalize_image, prepare_uploaded_images
from apps.ai.models import AIResultCache, AIUsageLog, FraudAnalysis
from apps.ai.services import description, fraud, negotiation, vision
from apps.chat.models import ChatMessage, ChatRoom
from apps.products.models import Category, Product

from .helpers import AIDataMixin, fake_gemini, make_png_bytes, make_upload


class ImageTests(TestCase):
    def test_normalize_to_jpeg(self):
        data, mime = normalize_image(make_png_bytes(size=(2000, 1000)))
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(data.startswith(b"\xff\xd8"))

    def test_rejects_non_image(self):
        with self.assertRaises(AIInputError):
            normalize_image(b"not an image")

    def test_prepare_takes_first_two(self):
        files = [make_upload(f"{i}.png") for i in range(3)]
        self.assertEqual(len(prepare_uploaded_images(files)), 2)
        with self.assertRaises(AIInputError):
            prepare_uploaded_images([])
        self.assertEqual(prepare_uploaded_images([], required=False), [])


# ───────────────────────── (1) 설명 생성 ─────────────────────────


class DescriptionServiceTests(AIDataMixin, TestCase):
    IMG = [(b"jpeg-bytes", "image/jpeg")]
    OK = {"title": "  아이패드   에어 5세대 ", "content": "좋아요.\n\n\n\n상태 좋아요.", "suggested_tags": ["#아이패드", "아이 패드", "아이패드"]}

    def test_generate_and_normalize(self):
        with fake_gemini(self.OK) as client:
            result = description.generate_description(self.IMG, "아이패드 에어", self.digital, user=self.seller)
        self.assertEqual(result.data["title"], "아이패드 에어 5세대")
        self.assertEqual(result.data["content"], "좋아요.\n\n상태 좋아요.")
        self.assertEqual(result.data["suggested_tags"], ["아이패드"])
        kwargs = client.generate_json.call_args.kwargs
        self.assertIn("디지털기기", client.generate_json.call_args.args[0])
        self.assertEqual(kwargs["images"], self.IMG)
        self.assertIsNotNone(kwargs["schema"])
        self.assertEqual(AIUsageLog.objects.get().user, self.seller)

    def test_same_input_uses_cache(self):
        with fake_gemini(self.OK) as client:
            description.generate_description(self.IMG, "아이패드", None)
            again = description.generate_description(self.IMG, "아이패드", None)
        self.assertTrue(again.cached)
        self.assertEqual(client.generate_json.call_count, 1)

    def test_regenerate_calls_again(self):
        with fake_gemini(self.OK, self.OK) as client:
            description.generate_description(self.IMG, "아이패드", None)
            description.generate_description(self.IMG, "아이패드", None, regenerate=True)
        self.assertEqual(client.generate_json.call_count, 2)
        self.assertGreater(client.generate_json.call_args.kwargs["temperature"], 0.8)

    def test_missing_fields_is_error(self):
        with fake_gemini({"title": "", "content": ""}):
            with self.assertRaises(AIServiceError):
                description.generate_description(self.IMG, "", None)
        self.assertFalse(AIResultCache.objects.exists())

    def test_input_validation(self):
        with self.assertRaises(AIInputError):
            description.generate_description([], "", None)
        with self.assertRaises(AIInputError):
            description.generate_description([], "가" * 201, None)


# ───────────────────────── (2) 사진 인식 ─────────────────────────


class VisionServiceTests(AIDataMixin, TestCase):
    IMG = [(b"jpeg-bytes", "image/jpeg")]

    def test_recognize_maps_category_and_condition(self):
        data = {"category_slug": "books", "title": "파이썬 책", "condition": "LIKE_NEW", "confidence": 0.93, "notes": "깨끗해요."}
        with fake_gemini(data) as client:
            result = vision.recognize_product(self.IMG)
        books = Category.objects.get(slug="books")
        self.assertEqual(result.data["category_id"], books.pk)
        self.assertEqual(result.data["category_name"], books.name)
        self.assertEqual(result.data["condition_label"], Product.Condition.LIKE_NEW.label)
        self.assertEqual(result.data["confidence_percent"], 93)
        schema = client.generate_json.call_args.kwargs["schema"]
        self.assertIn("books", schema["properties"]["category_slug"]["enum"])

    def test_invalid_values_fall_back(self):
        data = {"category_slug": "spaceship", "title": "?", "condition": "BROKEN", "confidence": 7}
        with fake_gemini(data):
            result = vision.recognize_product(self.IMG)
        self.assertEqual(result.data["category_slug"], "etc")
        self.assertEqual(result.data["condition"], Product.Condition.GOOD)
        self.assertEqual(result.data["confidence"], 1.0)

    def test_requires_image(self):
        with self.assertRaises(AIInputError):
            vision.recognize_product([])


# ───────────────────────── (3) 사기 탐지 ─────────────────────────


class FraudRuleTests(TestCase):
    def assertHit(self, text, fragment):
        hits = fraud.check_text_rules(text)
        self.assertTrue(any(fragment in h for h in hits), f"{text!r} → {hits}")

    def test_positive_rules(self):
        self.assertHit("선입금 후 발송해요", "입금을 먼저")
        self.assertHit("입금 확인 후 바로 발송합니다", "입금을 먼저")
        self.assertHit("국민 123456-01-123456 로 보내주세요", "계좌번호")
        self.assertHit("3333-01-1234567 입금", "계좌번호")
        self.assertHit("카톡 abc123 으로 연락주세요", "외부 메신저")
        self.assertHit("텔레그램 @seller 로 와주세요", "외부 메신저")
        self.assertHit("010-1234-5678 문자 주세요", "개인 연락처")
        self.assertHit("http://safe-pay.xyz 안전결제 링크로 결제해 주세요", "안전결제")
        self.assertHit("택배거래만 가능해요", "택배거래만")
        self.assertHit("신분증 사진 보내주세요", "개인정보")
        self.assertHit("오늘 안에 입금하시면 드려요", "빠른 입금")
        self.assertHit("해외에 있어서 택배로만 보내드려요", "만날 수 없다")

    def test_negative_rules(self):
        for text in [
            "직거래 원해요. 화정역 근처에서 만나요.",
            "텔레비전 팔아요. 라인업이 좋아요.",
            "2024-01-15 에 구매했어요",
            "온라인 강의 수강권이에요",
            "",
        ]:
            self.assertEqual(fraud.check_text_rules(text), [], text)

    def test_phone_is_not_account(self):
        hits = fraud.check_text_rules("010-1234-5678")
        self.assertFalse(any("계좌" in h for h in hits))

    def test_combine_scores(self):
        self.assertEqual(fraud.combine_scores(40, None), 40)
        self.assertEqual(fraud.combine_scores(0, 80), 80)
        self.assertEqual(fraud.combine_scores(40, 10), 25)
        self.assertEqual(fraud.combine_scores(90, 20), 90)  # 강한 규칙은 유지
        self.assertEqual(fraud.level_for(29), "LOW")
        self.assertEqual(fraud.level_for(30), "MEDIUM")
        self.assertEqual(fraud.level_for(70), "HIGH")


class FraudAnalysisTests(AIDataMixin, TestCase):
    SCAM = {
        "title": "아이폰 15 프로 미개봉",
        "content": "택배거래만 해요. 선입금 후 발송합니다. 카톡 scam77 로 연락주세요. 국민 123456-01-123456",
        "price": 250000,
    }

    def test_rule_only_when_ai_unavailable(self):
        product = self.make_product(**self.SCAM)
        with fake_gemini(side_effect=AIUnavailableError()):
            analysis = fraud.analyze_product(product)
        self.assertEqual(analysis.source, FraudAnalysis.Source.RULE)
        self.assertEqual(analysis.risk_level, FraudAnalysis.RiskLevel.HIGH)
        self.assertTrue(analysis.is_warning)
        self.assertGreaterEqual(len(analysis.rule_hits), 3)
        self.assertEqual(analysis.reasons, analysis.rule_hits[:3])

    def test_ai_and_rules_combined(self):
        product = self.make_product(**self.SCAM)
        ai = {"risk_score": 95, "risk_level": "HIGH", "reasons": ["선입금을 요구해요", "외부 메신저로 유도해요"]}
        with fake_gemini(ai) as client:
            analysis = fraud.analyze_product(product)
        self.assertEqual(analysis.source, FraudAnalysis.Source.RULE_AI)
        self.assertGreaterEqual(analysis.risk_score, 95)  # 강한 규칙(100)이 하한
        self.assertEqual(analysis.reasons, ai["reasons"])
        prompt = client.generate_json.call_args.args[0]
        self.assertIn("<listing>", prompt)
        self.assertIn("입금을 먼저", prompt)  # 규칙 결과를 AI 에 참고로 전달

    def test_benign_product_low(self):
        product = self.make_product()
        with fake_gemini({"risk_score": 5, "risk_level": "LOW", "reasons": []}):
            analysis = fraud.analyze_product(product)
        self.assertEqual(analysis.risk_level, FraudAnalysis.RiskLevel.LOW)
        self.assertEqual(analysis.source, FraudAnalysis.Source.AI)
        self.assertFalse(analysis.is_warning)

    def test_same_content_hash_skips_reanalysis(self):
        product = self.make_product()
        with fake_gemini({"risk_score": 5, "risk_level": "LOW", "reasons": []}) as client:
            first = fraud.analyze_product(product)
            second = fraud.analyze_product(product)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(client.generate_json.call_count, 1)
        self.assertEqual(AIUsageLog.objects.count(), 1)

    def test_changed_content_reanalyzes_and_force_bypasses_cache(self):
        product = self.make_product()
        low = {"risk_score": 5, "risk_level": "LOW", "reasons": []}
        with fake_gemini(low, low, low) as client:
            fraud.analyze_product(product)
            product.content += " 카톡 주세요"
            product.save()
            changed = fraud.analyze_product(product)
            fraud.analyze_product(product, force=True)
        self.assertEqual(client.generate_json.call_count, 3)
        self.assertIn("외부 메신저", " ".join(changed.rule_hits))
        self.assertEqual(FraudAnalysis.objects.count(), 1)

    def test_rule_only_result_retries_ai_later(self):
        product = self.make_product()
        with fake_gemini(side_effect=AIServiceError("x")):
            self.assertEqual(fraud.analyze_product(product).source, FraudAnalysis.Source.RULE)
        with fake_gemini({"risk_score": 3, "risk_level": "LOW", "reasons": []}) as client:
            self.assertEqual(fraud.analyze_product(product).source, FraudAnalysis.Source.AI)
        self.assertEqual(client.generate_json.call_count, 1)

    def test_price_anomaly_rules(self):
        cheap = self.make_product(title="맥북 프로 14 M3", content="상태 좋아요", price=30000)
        hits, _ = fraud.price_rules(cheap)
        self.assertIn(fraud.RULE_PREMIUM_CHEAP, hits)
        case = self.make_product(title="아이폰 케이스", content="새 케이스예요", price=5000)
        hits, _ = fraud.price_rules(case)
        self.assertNotIn(fraud.RULE_PREMIUM_CHEAP, hits)

        for i in range(6):
            self.make_product(title=f"모니터 {i}", price=300000)
        low = self.make_product(title="모니터 27인치", price=20000)
        hits, context = fraud.price_rules(low)
        self.assertIn(fraud.RULE_BELOW_MARKET, hits)
        self.assertIn("중앙값", context)

    def test_unsaved_product_returns_none(self):
        self.assertIsNone(fraud.analyze_product(Product(title="x")))


# ───────────────────────── (4) 가격 협상 ─────────────────────────


class NegotiationTests(AIDataMixin, TestCase):
    def test_detect_negotiation(self):
        for text in ["35만원에 가능할까요?", "혹시 네고 되나요?", "조금만 깎아주세요", "25,000원에 주실 수 있나요",
                     "2만5천원에 안될까요", "만원에 될까요", "10000원이면 살게요", "가격 조정 가능한가요", "에누리 좀 해주세요"]:
            self.assertTrue(negotiation.detect_negotiation(text), text)
        for text in ["안녕하세요 아직 판매중인가요?", "5시에 가능해요", "언제 거래 가능하세요?", "3일에 가능", "", "택배비 포함인가요?"]:
            self.assertFalse(negotiation.detect_negotiation(text), text)

    def test_extract_offer_price(self):
        self.assertEqual(negotiation.extract_offer_price("35만원에 가능?"), 350000)
        self.assertEqual(negotiation.extract_offer_price("2만5천원"), 25000)
        self.assertEqual(negotiation.extract_offer_price("2.5만 어때요"), 25000)
        self.assertEqual(negotiation.extract_offer_price("380,000원에 주세요"), 380000)
        self.assertEqual(negotiation.extract_offer_price("5천원만 빼주세요"), 5000)
        self.assertIsNone(negotiation.extract_offer_price("네고 되나요"))

    def _room(self):
        product = self.make_product()
        room = ChatRoom.objects.create(product=product, seller=self.seller, buyer=self.buyer)
        ChatMessage.objects.create(room=room, sender=self.buyer, content="안녕하세요!")
        ChatMessage.objects.create(room=room, sender=self.seller, content="네 안녕하세요")
        target = ChatMessage.objects.create(room=room, sender=self.buyer, content="40만원에 가능할까요?")
        return room, target

    def test_generate_drafts_normalizes(self):
        _room, target = self._room()
        data = {"drafts": [
            {"tone": "역제안", "text": "42만원 어떠세요?", "price": 420000},
            {"tone": "정중한 거절", "text": "죄송해요, 가격은 그대로예요.", "price": 450000},
            {"tone": "이상한톤", "text": "43만원까지 해드릴게요", "price": 999999},
        ]}
        with fake_gemini(data) as client:
            result = negotiation.generate_drafts(target, user=self.seller)
        tones = [d["tone"] for d in result.data["drafts"]]
        self.assertEqual(tones, ["정중한 거절", "소폭 양보", "역제안"])
        self.assertIsNone(result.data["drafts"][1]["price"])  # 판매가 초과 금액 제거
        self.assertEqual(result.data["offered_price"], 400000)
        prompt = client.generate_json.call_args.args[0]
        self.assertIn("구매자: 안녕하세요!", prompt)
        self.assertIn("판매자: 네 안녕하세요", prompt)
        self.assertIn("400,000원", prompt)

    def test_drafts_cached_per_conversation(self):
        _room, target = self._room()
        data = {"drafts": [{"tone": t, "text": "답장"} for t in ["정중한 거절", "소폭 양보", "역제안"]]}
        with fake_gemini(data) as client:
            negotiation.generate_drafts(target)
            again = negotiation.generate_drafts(target)
        self.assertTrue(again.cached)
        self.assertEqual(client.generate_json.call_count, 1)

    def test_empty_drafts_is_error(self):
        _room, target = self._room()
        with fake_gemini({"drafts": []}):
            with self.assertRaises(AIServiceError):
                negotiation.generate_drafts(target)
