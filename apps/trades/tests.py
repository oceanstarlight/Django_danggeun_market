"""거래완료 · 후기 · 매너온도 테스트."""

import itertools
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import Profile, Region
from apps.chat.models import ChatMessage, ChatRoom
from apps.notifications.models import Notification
from apps.products.models import Category, Product

from . import selectors, services
from .forms import ReviewForm
from .models import Review

User = get_user_model()
_seq = itertools.count(1)


def make_user(temperature="36.5", with_profile=True):
    n = next(_seq)
    user = User.objects.create_user(username=f"trader{n}", password="pass-1234-word")
    if with_profile:
        Profile.objects.create(
            user=user,
            nickname=f"거래이웃{n}",
            region=Region.objects.first(),
            manner_temperature=Decimal(temperature),
        )
    return user


def make_product(seller, **kwargs):
    defaults = {
        "category": Category.objects.first(),
        "region": Region.objects.first(),
        "title": f"거래 상품 {next(_seq)}",
        "content": "설명이에요.",
        "price": 20000,
    }
    defaults.update(kwargs)
    return Product.objects.create(seller=seller, **defaults)


def temperature_of(user):
    return Profile.objects.get(user=user).manner_temperature


class TradeFixtureMixin:
    def setUp(self):
        self.seller = make_user()
        self.buyer = make_user()
        self.other_buyer = make_user()
        self.stranger = make_user()
        self.product = make_product(self.seller)
        self.room = ChatRoom.objects.create(product=self.product, seller=self.seller, buyer=self.buyer)
        self.other_room = ChatRoom.objects.create(product=self.product, seller=self.seller, buyer=self.other_buyer)

    def sold_product(self):
        product = make_product(self.seller, status=Product.Status.SOLD, buyer=self.buyer)
        ChatRoom.objects.create(product=product, seller=self.seller, buyer=self.buyer)
        return product


# ───────────────────────── 서비스 ─────────────────────────


class CompleteTradeServiceTests(TradeFixtureMixin, TestCase):
    def test_complete_sets_sold_buyer_and_notifies_buyer(self):
        services.complete_trade(self.product, self.seller, self.buyer)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SOLD)
        self.assertEqual(self.product.buyer, self.buyer)
        note = Notification.objects.get(user=self.buyer)
        self.assertEqual(note.kind, Notification.Kind.STATUS_CHANGE)
        self.assertEqual(note.url, reverse("trades:review_create", args=[self.product.pk]))
        self.assertIn(self.product.title, note.message)
        self.assertFalse(Notification.objects.filter(user=self.other_buyer).exists())

    def test_complete_without_buyer(self):
        services.complete_trade(self.product, self.seller, None)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SOLD)
        self.assertIsNone(self.product.buyer)
        self.assertFalse(Notification.objects.exists())

    def test_only_seller_can_complete(self):
        with self.assertRaises(services.TradeError):
            services.complete_trade(self.product, self.buyer, self.buyer)

    def test_buyer_must_be_chat_partner(self):
        with self.assertRaisesMessage(services.TradeError, "채팅한 이웃"):
            services.complete_trade(self.product, self.seller, self.stranger)
        with self.assertRaises(services.TradeError):
            services.complete_trade(self.product, self.seller, self.seller)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SELLING)

    def test_cannot_complete_twice(self):
        services.complete_trade(self.product, self.seller, self.buyer)
        with self.assertRaisesMessage(services.TradeError, "이미 거래완료"):
            services.complete_trade(self.product, self.seller, self.other_buyer)
        self.product.refresh_from_db()
        self.assertEqual(self.product.buyer, self.buyer)


class MannerTemperatureTests(TestCase):
    def test_rating_deltas(self):
        cases = {5: "37.0", 4: "36.7", 3: "36.5", 2: "36.2", 1: "35.9"}
        for rating, expected in cases.items():
            with self.subTest(rating=rating):
                user = make_user("36.5")
                services.apply_manner_rating(user, rating)
                self.assertEqual(temperature_of(user), Decimal(expected))

    def test_clamped_between_0_and_99(self):
        hot = make_user("98.8")
        services.apply_manner_rating(hot, 5)
        self.assertEqual(temperature_of(hot), Decimal("99.0"))
        cold = make_user("0.3")
        services.apply_manner_rating(cold, 1)
        self.assertEqual(temperature_of(cold), Decimal("0.0"))

    def test_user_without_profile_is_ignored(self):
        user = make_user(with_profile=False)
        self.assertIsNone(services.apply_manner_rating(user, 5))

    def test_clamp_temperature(self):
        self.assertEqual(services.clamp_temperature(Decimal("120")), Decimal("99"))
        self.assertEqual(services.clamp_temperature(Decimal("-3")), Decimal("0"))
        self.assertEqual(services.clamp_temperature(Decimal("36.55")), Decimal("36.6"))


class CreateReviewServiceTests(TradeFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.sold = self.sold_product()

    def test_buyer_reviews_seller(self):
        review = services.create_review(
            self.sold, self.buyer, 5, ["친절해요", "응답이 빨라요", "친절해요"], "  좋은 거래였어요  "
        )
        self.assertEqual(review.reviewee, self.seller)
        self.assertEqual(review.manner_tags, ["친절해요", "응답이 빨라요"])  # 중복 제거
        self.assertEqual(review.content, "좋은 거래였어요")
        self.assertEqual(temperature_of(self.seller), Decimal("37.0"))
        note = Notification.objects.get(user=self.seller, kind=Notification.Kind.REVIEW)
        self.assertEqual(note.url, reverse("accounts:mypage") + "?tab=reviews")

    def test_seller_reviews_buyer_with_buyer_tags(self):
        review = services.create_review(self.sold, self.seller, 2, ["무리하게 가격을 깎았어요"])
        self.assertEqual(review.reviewee, self.buyer)
        self.assertEqual(temperature_of(self.buyer), Decimal("36.2"))

    def test_both_directions_allowed_once_each(self):
        services.create_review(self.sold, self.buyer, 4)
        services.create_review(self.sold, self.seller, 4)
        self.assertEqual(Review.objects.filter(product=self.sold).count(), 2)
        with self.assertRaisesMessage(services.TradeError, "이미"):
            services.create_review(self.sold, self.buyer, 5)
        self.assertEqual(temperature_of(self.seller), Decimal("36.7"))  # 두 번째는 반영 안 됨

    def test_rejects_tag_for_wrong_role(self):
        # '상품 상태가 설명과 같아요'는 판매자에게만 줄 수 있어요
        with self.assertRaisesMessage(services.TradeError, "매너 태그"):
            services.create_review(self.sold, self.seller, 5, ["상품 상태가 설명과 같아요"])
        self.assertFalse(Review.objects.exists())

    def test_rejects_invalid_rating_and_long_content(self):
        for bad in (0, 6, "x", None):
            with self.subTest(rating=bad), self.assertRaises(services.TradeError):
                services.create_review(self.sold, self.buyer, bad)
        with self.assertRaises(services.TradeError):
            services.create_review(self.sold, self.buyer, 5, content="가" * 501)
        self.assertFalse(Review.objects.exists())

    def test_rejects_non_participant_and_unsold(self):
        with self.assertRaisesMessage(services.TradeError, "당사자"):
            services.create_review(self.sold, self.stranger, 5)
        with self.assertRaisesMessage(services.TradeError, "거래완료된 상품"):
            services.create_review(self.product, self.buyer, 5)
        no_buyer = make_product(self.seller, status=Product.Status.SOLD)
        with self.assertRaises(services.TradeError):
            services.create_review(no_buyer, self.seller, 5)

    def test_review_block_reason(self):
        self.assertIsNone(services.review_block_reason(self.sold, self.buyer))
        self.assertIsNone(services.review_block_reason(self.sold, self.seller))
        self.assertIsNotNone(services.review_block_reason(self.sold, self.stranger))
        services.create_review(self.sold, self.buyer, 3)
        self.assertIn("이미", services.review_block_reason(self.sold, self.buyer))


class SelectorTests(TradeFixtureMixin, TestCase):
    def test_chat_partners_ordered_with_last_message(self):
        ChatMessage.objects.create(room=self.room, sender=self.buyer, content="첫 메시지")
        ChatMessage.objects.create(room=self.room, sender=self.buyer, content="마지막 메시지")
        from django.utils import timezone

        ChatRoom.objects.filter(pk=self.room.pk).update(last_message_at=timezone.now())
        partners = list(selectors.chat_partners(self.product))
        self.assertEqual([r.buyer for r in partners], [self.buyer, self.other_buyer])
        self.assertEqual(partners[0].last_message, "마지막 메시지")
        self.assertEqual(partners[0].num_messages, 2)
        self.assertIsNone(partners[1].last_message)


class ReviewFormTests(TestCase):
    def test_choices_depend_on_reviewee_role(self):
        seller_form = ReviewForm(reviewee_is_seller=True)
        buyer_form = ReviewForm(reviewee_is_seller=False)
        seller_tags = [v for v, _ in seller_form.fields["good_tags"].choices]
        buyer_tags = [v for v, _ in buyer_form.fields["bad_tags"].choices]
        self.assertIn("상품 상태가 설명과 같아요", seller_tags)
        self.assertIn("무리하게 가격을 깎았어요", buyer_tags)

    def test_merges_tags_and_requires_rating(self):
        form = ReviewForm({"rating": "4", "good_tags": ["친절해요"], "bad_tags": ["응답이 느려요"]})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["rating"], 4)
        self.assertEqual(form.cleaned_data["manner_tags"], ["친절해요", "응답이 느려요"])
        form = ReviewForm({"good_tags": ["친절해요"]})
        self.assertFalse(form.is_valid())
        self.assertIn("rating", form.errors)

    def test_rating_options_mark_checked(self):
        form = ReviewForm({"rating": "2"})
        options = form.rating_options()
        self.assertEqual([o["value"] for o in options], [5, 4, 3, 2, 1])
        self.assertEqual([o["value"] for o in options if o["checked"]], [2])
        self.assertIn("+0.5", options[0]["caption"])


# ───────────────────────── 뷰 ─────────────────────────


class CompleteViewTests(TradeFixtureMixin, TestCase):
    def url(self, product=None):
        return reverse("trades:complete", args=[(product or self.product).pk])

    def test_login_required(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_non_seller_forbidden(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.client.post(self.url(), {"buyer": self.buyer.pk}).status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SELLING)

    def test_missing_product_404(self):
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(reverse("trades:complete", args=[999999])).status_code, 404)

    def test_get_lists_chat_partners(self):
        self.client.force_login(self.seller)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "trades/complete.html")
        self.assertContains(response, self.buyer.profile.nickname)
        self.assertContains(response, self.other_buyer.profile.nickname)
        self.assertNotContains(response, self.stranger.profile.nickname)
        self.assertEqual(response.context["selected"], "")

    def test_get_preselects_buyer_from_query(self):
        self.client.force_login(self.seller)
        response = self.client.get(self.url() + f"?buyer={self.other_buyer.pk}")
        self.assertEqual(response.context["selected"], str(self.other_buyer.pk))
        response = self.client.get(self.url() + f"?buyer={self.stranger.pk}")
        self.assertEqual(response.context["selected"], "")

    def test_query_count_is_constant(self):
        for _ in range(5):
            ChatRoom.objects.create(product=self.product, seller=self.seller, buyer=make_user())
        self.client.force_login(self.seller)
        self.client.get(self.url())  # 워밍업 (세션 등)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.url())
        few = len(ctx.captured_queries)
        for _ in range(5):
            ChatRoom.objects.create(product=self.product, seller=self.seller, buyer=make_user())
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.url())
        self.assertEqual(len(ctx.captured_queries), few)

    def test_post_completes_and_redirects_to_review(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url(), {"buyer": self.buyer.pk})
        self.assertRedirects(response, reverse("trades:review_create", args=[self.product.pk]))
        self.product.refresh_from_db()
        self.assertEqual((self.product.status, self.product.buyer), (Product.Status.SOLD, self.buyer))
        self.assertTrue(Notification.objects.filter(user=self.buyer, kind=Notification.Kind.STATUS_CHANGE).exists())

    def test_post_without_buyer_option(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url(), {"buyer": "none"})
        self.assertRedirects(response, reverse("products:detail", args=[self.product.pk]), fetch_redirect_response=False)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SOLD)
        self.assertIsNone(self.product.buyer)

    def test_post_invalid_choices_rerender_with_error(self):
        self.client.force_login(self.seller)
        for value in ("", "abc", str(self.stranger.pk)):
            with self.subTest(value=value):
                response = self.client.post(self.url(), {"buyer": value})
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.context["error"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SELLING)

    def test_already_sold_redirects_to_detail(self):
        sold = self.sold_product()
        self.client.force_login(self.seller)
        response = self.client.get(self.url(sold))
        self.assertRedirects(response, reverse("products:detail", args=[sold.pk]), fetch_redirect_response=False)

    def test_empty_state_without_chats(self):
        lonely = make_product(self.seller)
        self.client.force_login(self.seller)
        response = self.client.get(self.url(lonely))
        self.assertContains(response, "아직 채팅한 이웃이 없어요")
        self.assertContains(response, "채팅 밖에서 거래했어요")

    def test_put_not_allowed(self):
        self.client.force_login(self.seller)
        self.assertEqual(self.client.put(self.url()).status_code, 405)


class ReviewViewTests(TradeFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.sold = self.sold_product()
        self.url = reverse("trades:review_create", args=[self.sold.pk])

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_stranger_forbidden(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"rating": 5}).status_code, 403)
        self.assertFalse(Review.objects.exists())

    def test_missing_product_404(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(reverse("trades:review_create", args=[999999])).status_code, 404)

    def test_get_form_for_buyer_and_seller(self):
        self.client.force_login(self.buyer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "trades/review_form.html")
        self.assertEqual(response.context["reviewee"], self.seller)
        self.assertContains(response, "상품 상태가 설명과 같아요")
        self.client.force_login(self.seller)
        response = self.client.get(self.url)
        self.assertEqual(response.context["reviewee"], self.buyer)
        self.assertContains(response, "무리하게 가격을 깎았어요")
        self.assertNotContains(response, "상품 상태가 설명과 같아요")

    def test_post_creates_review(self):
        self.client.force_login(self.buyer)
        response = self.client.post(
            self.url, {"rating": "5", "good_tags": ["친절해요", "가격이 합리적이에요"], "content": "감사해요"}
        )
        self.assertRedirects(response, reverse("products:detail", args=[self.sold.pk]), fetch_redirect_response=False)
        review = Review.objects.get()
        self.assertEqual((review.reviewer, review.reviewee, review.rating), (self.buyer, self.seller, 5))
        self.assertEqual(review.manner_tags, ["친절해요", "가격이 합리적이에요"])
        self.assertEqual(temperature_of(self.seller), Decimal("37.0"))
        self.assertTrue(Notification.objects.filter(user=self.seller, kind=Notification.Kind.REVIEW).exists())

    def test_post_invalid_rerenders(self):
        self.client.force_login(self.buyer)
        response = self.client.post(self.url, {"good_tags": ["친절해요"]})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.context["form"].errors["rating"])
        response = self.client.post(self.url, {"rating": "5", "good_tags": ["가짜 태그"]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Review.objects.exists())

    def test_second_review_redirects(self):
        Review.objects.create(product=self.sold, reviewer=self.buyer, reviewee=self.seller, rating=4)
        self.client.force_login(self.buyer)
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("products:detail", args=[self.sold.pk]), fetch_redirect_response=False)
        response = self.client.post(self.url, {"rating": "1"})
        self.assertEqual(Review.objects.count(), 1)

    def test_unsold_product_redirects(self):
        self.client.force_login(self.seller)
        response = self.client.get(reverse("trades:review_create", args=[self.product.pk]))
        self.assertRedirects(response, reverse("products:detail", args=[self.product.pk]), fetch_redirect_response=False)

    def test_full_flow_complete_then_both_reviews(self):
        """판매자가 거래완료 → 구매자 알림에서 후기 → 판매자도 후기."""
        self.client.force_login(self.seller)
        self.client.post(reverse("trades:complete", args=[self.product.pk]), {"buyer": self.other_buyer.pk})
        note = Notification.objects.get(user=self.other_buyer)

        self.client.force_login(self.other_buyer)
        response = self.client.get(reverse("notifications:go", args=[note.pk]))
        review_url = reverse("trades:review_create", args=[self.product.pk])
        self.assertRedirects(response, review_url)
        self.client.post(review_url, {"rating": "4", "good_tags": ["응답이 빨라요"]})

        self.client.force_login(self.seller)
        self.client.post(review_url, {"rating": "5", "good_tags": ["거래를 깔끔하게 마무리했어요"]})

        self.assertEqual(Review.objects.filter(product=self.product).count(), 2)
        self.assertEqual(temperature_of(self.seller), Decimal("36.7"))
        self.assertEqual(temperature_of(self.other_buyer), Decimal("37.0"))
