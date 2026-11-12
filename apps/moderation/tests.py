"""신고 · 차단 서비스/뷰 테스트."""

import json

from django.test import TestCase
from django.urls import reverse

from apps.accounts.tests.factories import make_product, make_user
from apps.moderation import services
from apps.moderation.models import Block, Report


class BlockServiceTests(TestCase):
    def setUp(self):
        self.a, self.b = make_user(), make_user()

    def test_toggle_and_lookup(self):
        self.assertTrue(services.toggle_block(self.a, self.b))
        self.assertTrue(services.has_blocked(self.a, self.b))
        self.assertFalse(services.has_blocked(self.b, self.a))
        self.assertTrue(services.is_blocked_between(self.b, self.a))
        self.assertEqual(services.blocked_user_ids(self.a), {self.b.pk})
        self.assertEqual(services.blocked_user_ids(self.b), {self.a.pk})
        self.assertFalse(services.toggle_block(self.a, self.b))
        self.assertFalse(Block.objects.exists())

    def test_block_is_idempotent_and_self_block_rejected(self):
        services.block_user(self.a, self.b)
        services.block_user(self.a, self.b)
        self.assertEqual(Block.objects.count(), 1)
        with self.assertRaises(services.ModerationError):
            services.block_user(self.a, self.a)
        self.assertFalse(services.unblock_user(self.b, self.a))


class ReportServiceTests(TestCase):
    def setUp(self):
        self.seller, self.reporter = make_user(), make_user()
        self.product = make_product(self.seller)

    def test_product_report_sets_reported_user(self):
        report = services.create_report(self.reporter, reason=Report.Reason.FRAUD, detail="  선입금 요구  ", product=self.product)
        self.assertEqual(report.reported_user, self.seller)
        self.assertEqual(report.detail, "선입금 요구")
        self.assertEqual(report.status, Report.Status.PENDING)

    def test_duplicate_pending_report_rejected_but_allowed_after_review(self):
        services.create_report(self.reporter, reason=Report.Reason.SPAM, product=self.product)
        with self.assertRaises(services.ModerationError):
            services.create_report(self.reporter, reason=Report.Reason.SPAM, product=self.product)
        Report.objects.update(status=Report.Status.REVIEWED)
        services.create_report(self.reporter, reason=Report.Reason.SPAM, product=self.product)
        self.assertEqual(Report.objects.count(), 2)

    def test_user_report_is_separate_from_product_report(self):
        services.create_report(self.reporter, reason=Report.Reason.SPAM, product=self.product)
        services.create_report(self.reporter, reason=Report.Reason.ABUSE, reported_user=self.seller)
        self.assertEqual(Report.objects.count(), 2)

    def test_invalid_targets(self):
        with self.assertRaises(services.ModerationError):
            services.create_report(self.seller, reason=Report.Reason.ETC, product=self.product)
        with self.assertRaises(services.ModerationError):
            services.create_report(self.reporter, reason=Report.Reason.ETC, reported_user=self.reporter)
        with self.assertRaises(services.ModerationError):
            services.create_report(self.reporter, reason=Report.Reason.ETC)


class ReportViewTests(TestCase):
    def setUp(self):
        self.seller = make_user(username="seller_x", nickname="판매자엑스")
        self.reporter = make_user(username="reporter_y")
        self.product = make_product(self.seller, title="수상한 상품")
        self.product_url = reverse("moderation:report_product", args=[self.product.pk])
        self.user_url = reverse("moderation:report_user", args=["seller_x"])
        self.client.force_login(self.reporter)

    def test_requires_login(self):
        self.client.logout()
        res = self.client.get(self.product_url)
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse("accounts:login"), res["Location"])

    def test_get_full_page_and_htmx_partial(self):
        res = self.client.get(self.product_url)
        self.assertTemplateUsed(res, "moderation/report_form.html")
        self.assertContains(res, "수상한 상품")
        self.assertNotContains(res, "hx-post")  # 전용 페이지는 일반 POST
        res = self.client.get(self.product_url, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(res, "moderation/partials/report_form.html")
        self.assertTemplateNotUsed(res, "base.html")
        self.assertContains(res, f'hx-post="{self.product_url}"')

    def test_post_product_report(self):
        res = self.client.post(self.product_url, {"reason": "FRAUD", "detail": "계좌 입금 먼저 요구"})
        self.assertRedirects(res, reverse("products:detail", args=[self.product.pk]), fetch_redirect_response=False)
        report = Report.objects.get()
        self.assertEqual((report.reporter, report.product, report.reason), (self.reporter, self.product, "FRAUD"))

    def test_htmx_post_returns_done_with_toast(self):
        res = self.client.post(self.user_url, {"reason": "ABUSE"}, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(res, "moderation/partials/report_done.html")
        self.assertIn("showToast", json.loads(res["HX-Trigger"]))
        self.assertEqual(Report.objects.get().reported_user, self.seller)

    def test_duplicate_shows_form_error(self):
        self.client.post(self.product_url, {"reason": "SPAM"})
        res = self.client.post(self.product_url, {"reason": "SPAM"}, HTTP_HX_REQUEST="true")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "이미 신고했어요")
        self.assertEqual(Report.objects.count(), 1)

    def test_validation(self):
        res = self.client.post(self.product_url, {"reason": ""})
        self.assertIn("reason", res.context["form"].errors)
        res = self.client.post(self.product_url, {"reason": "ETC", "detail": ""})
        self.assertIn("detail", res.context["form"].errors)
        self.assertFalse(Report.objects.exists())

    def test_cannot_report_own_product_or_self(self):
        self.client.force_login(self.seller)
        self.assertEqual(self.client.get(self.product_url).status_code, 403)
        self.assertEqual(self.client.post(self.user_url, {"reason": "SPAM"}).status_code, 403)

    def test_not_found(self):
        self.assertEqual(self.client.get(reverse("moderation:report_product", args=[99999])).status_code, 404)
        self.assertEqual(self.client.get(reverse("moderation:report_user", args=["ghost"])).status_code, 404)


class BlockViewTests(TestCase):
    def setUp(self):
        self.me = make_user(username="me_user")
        self.target = make_user(username="target_user", nickname="불편한이웃")
        self.url = reverse("moderation:block_toggle", args=["target_user"])
        self.client.force_login(self.me)

    def test_post_only(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_toggle_redirects_to_profile_or_safe_next(self):
        res = self.client.post(self.url)
        self.assertRedirects(res, "/users/target_user/", fetch_redirect_response=False)
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.target).exists())
        res = self.client.post(self.url, {"next": reverse("moderation:block_list")})
        self.assertRedirects(res, reverse("moderation:block_list"), fetch_redirect_response=False)
        self.assertFalse(Block.objects.exists())
        res = self.client.post(self.url, {"next": "https://evil.example/"})
        self.assertRedirects(res, "/users/target_user/", fetch_redirect_response=False)

    def test_htmx_returns_button_partial(self):
        res = self.client.post(self.url, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(res, "moderation/partials/block_button.html")
        self.assertContains(res, "차단 해제")
        self.assertIn("불편한이웃", json.loads(res["HX-Trigger"])["showToast"]["message"])

    def test_self_block_forbidden_and_unknown_404(self):
        self.assertEqual(self.client.post(reverse("moderation:block_toggle", args=["me_user"])).status_code, 403)
        self.assertEqual(self.client.post(reverse("moderation:block_toggle", args=["nobody"])).status_code, 404)

    def test_anonymous_redirected(self):
        self.client.logout()
        res = self.client.post(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Block.objects.exists())

    def test_block_list_shows_only_my_blocks(self):
        other = make_user(nickname="남의차단")
        Block.objects.create(blocker=self.me, blocked=self.target)
        Block.objects.create(blocker=other, blocked=self.me)
        res = self.client.get(reverse("moderation:block_list"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "불편한이웃")
        self.assertNotContains(res, "남의차단")
        self.assertEqual(len(res.context["page_obj"].object_list), 1)

    def test_block_list_empty_state(self):
        self.assertContains(self.client.get(reverse("moderation:block_list")), "차단한 이웃이 없어요")
