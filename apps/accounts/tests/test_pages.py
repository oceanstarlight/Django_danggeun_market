"""마이페이지 · 프로필 수정 · 판매자 프로필 · selectors."""

import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts import selectors
from apps.accounts.models import Profile, Region
from apps.chat.models import ChatRoom
from apps.moderation.models import Block
from apps.products.models import Product, RecentView, Wishlist
from apps.trades.models import Review

from .factories import make_product, make_user, png_file

User = get_user_model()
MYPAGE = reverse("accounts:mypage")


class SelectorTests(TestCase):
    def setUp(self):
        self.seller = make_user()
        self.buyer = make_user()
        self.other = make_user()

    def test_card_counts_are_exact_even_when_filtered_by_wishlist(self):
        product = make_product(self.seller)
        Wishlist.objects.create(user=self.buyer, product=product)
        Wishlist.objects.create(user=self.other, product=product)
        ChatRoom.objects.create(product=product, seller=self.seller, buyer=self.buyer)
        item = selectors.wishlist_products(self.buyer).get()
        self.assertEqual((item.wish_count, item.chat_count), (2, 1))

    def test_wishlist_and_recent_order_and_block_filter(self):
        p1, p2 = make_product(self.seller), make_product(self.other)
        Wishlist.objects.create(user=self.buyer, product=p1)
        Wishlist.objects.create(user=self.buyer, product=p2)
        self.assertEqual(list(selectors.wishlist_products(self.buyer)), [p2, p1])
        self.assertEqual(list(selectors.wishlist_products(self.buyer, {self.other.pk})), [p1])
        RecentView.objects.create(user=self.buyer, product=p2)
        RecentView.objects.create(user=self.buyer, product=p1)
        self.assertEqual(list(selectors.recent_products(self.buyer)), [p1, p2])

    def test_review_summary(self):
        empty = selectors.review_summary(self.seller)
        self.assertEqual((empty["count"], empty["avg"], empty["stars"], empty["tags"]), (0, None, 0, []))
        p1, p2 = make_product(self.seller), make_product(self.seller)
        Review.objects.create(product=p1, reviewer=self.buyer, reviewee=self.seller, rating=5, manner_tags=["친절해요", "응답이 빨라요"])
        Review.objects.create(product=p2, reviewer=self.other, reviewee=self.seller, rating=4, manner_tags=["친절해요"])
        summary = selectors.review_summary(self.seller)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["avg"], Decimal("4.5"))
        self.assertEqual(summary["stars"], 5)
        self.assertEqual(summary["tags"][0], ("친절해요", 2))

    def test_product_counts(self):
        make_product(self.seller)
        make_product(self.seller, status=Product.Status.RESERVED)
        make_product(self.seller, status=Product.Status.SOLD)
        self.assertEqual(selectors.product_counts(self.seller), {"selling": 2, "sold": 1})


class MypageTests(TestCase):
    def setUp(self):
        self.me = make_user(nickname="나야나")
        self.seller = make_user(nickname="판매왕")
        self.client.force_login(self.me)

    def test_requires_login(self):
        self.client.logout()
        res = self.client.get(MYPAGE)
        self.assertRedirects(res, f"{reverse('accounts:login')}?next={MYPAGE}", fetch_redirect_response=False)

    def test_htmx_anonymous_gets_hx_redirect(self):
        self.client.logout()
        res = self.client.get(MYPAGE, HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL="http://testserver/users/x/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["HX-Redirect"], f"{reverse('accounts:login')}?next=%2Fusers%2Fx%2F")

    def test_default_tab_lists_my_selling_products(self):
        selling = make_product(self.me, title="판매중인 자전거")
        make_product(self.me, title="이미 팔린 책상", status=Product.Status.SOLD)
        res = self.client.get(MYPAGE)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "accounts/mypage.html")
        self.assertEqual(res.context["tab"], "selling")
        self.assertEqual(list(res.context["page_obj"]), [selling])
        self.assertContains(res, "나야나")
        self.assertEqual(res.context["counts"]["selling"], 1)
        self.assertEqual(res.context["counts"]["sold"], 1)

    def test_each_tab(self):
        sold = make_product(self.me, status=Product.Status.SOLD)
        bought = make_product(self.seller, status=Product.Status.SOLD, buyer=self.me)
        wished = make_product(self.seller)
        Wishlist.objects.create(user=self.me, product=wished)
        RecentView.objects.create(user=self.me, product=wished)
        review = Review.objects.create(product=bought, reviewer=self.seller, reviewee=self.me, rating=5, content="좋은 분이에요")
        expected = {"sold": [sold], "bought": [bought], "wishlist": [wished], "recent": [wished], "reviews": [review]}
        for tab, items in expected.items():
            with self.subTest(tab=tab):
                res = self.client.get(MYPAGE, {"tab": tab})
                self.assertEqual(res.context["tab"], tab)
                self.assertEqual(list(res.context["page_obj"]), items)
        self.assertContains(self.client.get(MYPAGE, {"tab": "reviews"}), "좋은 분이에요")

    def test_invalid_tab_falls_back(self):
        self.assertEqual(self.client.get(MYPAGE, {"tab": "nope"}).context["tab"], "selling")

    def test_empty_states(self):
        self.assertContains(self.client.get(MYPAGE), "판매 중인 상품이 없어요")
        self.assertContains(self.client.get(MYPAGE, {"tab": "wishlist"}), "찜한 상품이 없어요")

    def test_blocked_seller_products_hidden_from_wishlist(self):
        wished = make_product(self.seller)
        Wishlist.objects.create(user=self.me, product=wished)
        Block.objects.create(blocker=self.seller, blocked=self.me)
        res = self.client.get(MYPAGE, {"tab": "wishlist"})
        self.assertEqual(list(res.context["page_obj"]), [])
        self.assertEqual(res.context["counts"]["wishlist"], 0)

    def test_htmx_tab_returns_partial(self):
        res = self.client.get(MYPAGE, {"tab": "sold"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="mypage-panel")
        self.assertTemplateUsed(res, "accounts/partials/mypage_panel.html")
        self.assertTemplateNotUsed(res, "base.html")

    def test_user_without_profile_gets_one(self):
        bare = User.objects.create_user(username="bare_user")
        self.client.force_login(bare)
        self.assertEqual(self.client.get(MYPAGE).status_code, 200)
        self.assertTrue(Profile.objects.filter(user=bare).exists())

    def test_query_count_does_not_grow_with_products(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(MYPAGE)
            return len(ctx)

        make_product(self.me)
        few = count_queries()
        for _ in range(6):
            p = make_product(self.me)
            Wishlist.objects.create(user=self.seller, product=p)
        self.assertEqual(count_queries(), few)

    def test_pagination(self):
        for _ in range(25):
            make_product(self.me)
        res = self.client.get(MYPAGE, {"page": 2})
        self.assertEqual(len(res.context["page_obj"].object_list), 5)
        self.assertContains(res, "?page=1")


@override_settings(USE_SUPABASE_STORAGE=False)
class ProfileEditTests(TestCase):
    url = reverse("accounts:profile_edit")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls.media)
        cls._media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls._media_override.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.me = make_user(nickname="원래닉")
        self.client.force_login(self.me)
        self.region = Region.objects.last()

    def post(self, **extra):
        data = {"nickname": "바뀐닉", "region": self.region.pk, "bio": "  주말에 거래해요  "}
        data.update(extra)
        return self.client.post(self.url, data)

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_get(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'value="원래닉"')
        self.assertContains(res, 'enctype="multipart/form-data"')

    def test_update_fields(self):
        res = self.post()
        self.assertRedirects(res, MYPAGE, fetch_redirect_response=False)
        profile = Profile.objects.get(user=self.me)
        self.assertEqual((profile.nickname, profile.region, profile.bio), ("바뀐닉", self.region, "주말에 거래해요"))

    def test_avatar_upload_and_remove(self):
        self.post(avatar=png_file())
        profile = Profile.objects.get(user=self.me)
        self.assertTrue(profile.avatar_url.startswith("/media/avatars/"), profile.avatar_url)
        self.post(remove_avatar="on")
        self.assertEqual(Profile.objects.get(user=self.me).avatar_url, "")

    def test_avatar_html_disguised_as_png_is_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        evil = SimpleUploadedFile("evil.png", b"<html><script>alert(1)</script></html>", content_type="text/html")
        res = self.post(avatar=evil)
        self.assertEqual(res.status_code, 200)
        self.assertIn("avatar", res.context["form"].errors)
        self.assertEqual(Profile.objects.get(user=self.me).avatar_url, "")

    def test_invalid_avatar_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        res = self.post(avatar=SimpleUploadedFile("note.txt", b"hello", content_type="text/plain"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("avatar", res.context["form"].errors)
        self.assertEqual(Profile.objects.get(user=self.me).nickname, "원래닉")

    def test_nickname_taken_by_other(self):
        make_user(nickname="남의닉")
        res = self.post(nickname="남의닉")
        self.assertIn("nickname", res.context["form"].errors)

    def test_keeping_own_nickname_is_ok(self):
        res = self.post(nickname="원래닉")
        self.assertEqual(res.status_code, 302)

    def test_storage_error_is_shown(self):
        from unittest import mock

        from apps.core.storage import StorageError

        with mock.patch("apps.accounts.services.upload_image", side_effect=StorageError("업로드 실패했어요.")):
            res = self.post(avatar=png_file())
        self.assertEqual(res.status_code, 200)
        self.assertIn("업로드 실패했어요.", res.context["form"].errors["avatar"])
        self.assertEqual(Profile.objects.get(user=self.me).nickname, "원래닉")


class SellerProfileTests(TestCase):
    def setUp(self):
        self.seller = make_user(username="seller_a", nickname="동네판매자", bio="친절하게 거래해요")
        self.viewer = make_user(username="viewer_b")
        self.url = reverse("accounts:seller_profile", args=["seller_a"])

    def test_url_contract(self):
        self.assertEqual(self.url, "/users/seller_a/")

    def test_public_view(self):
        on_sale = make_product(self.seller, title="판매중 의자")
        make_product(self.seller, title="거래완료 의자", status=Product.Status.SOLD)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "동네판매자")
        self.assertContains(res, "친절하게 거래해요")
        self.assertEqual(list(res.context["page_obj"]), [on_sale])
        self.assertNotContains(res, "신고하기")  # 비로그인은 신고/차단 메뉴 없음

    def test_unknown_or_inactive_user_404(self):
        self.assertEqual(self.client.get(reverse("accounts:seller_profile", args=["ghost"])).status_code, 404)
        self.seller.is_active = False
        self.seller.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_reviews_tab_with_average(self):
        p = make_product(self.seller, status=Product.Status.SOLD, buyer=self.viewer)
        Review.objects.create(product=p, reviewer=self.viewer, reviewee=self.seller, rating=4, manner_tags=["응답이 빨라요"])
        res = self.client.get(self.url, {"tab": "reviews"})
        self.assertEqual(res.context["summary"]["avg"], Decimal("4.0"))
        self.assertContains(res, "응답이 빨라요")

    def test_logged_in_viewer_sees_report_and_block(self):
        self.client.force_login(self.viewer)
        res = self.client.get(self.url)
        self.assertContains(res, reverse("moderation:report_user", args=["seller_a"]))
        self.assertContains(res, reverse("moderation:block_toggle", args=["seller_a"]))

    def test_me_sees_edit_button(self):
        self.client.force_login(self.seller)
        res = self.client.get(self.url)
        self.assertTrue(res.context["is_me"])
        self.assertContains(res, reverse("accounts:profile_edit"))
        self.assertNotContains(res, reverse("moderation:block_toggle", args=["seller_a"]))

    def test_blocked_hides_products(self):
        make_product(self.seller, title="숨겨질 상품")
        Block.objects.create(blocker=self.viewer, blocked=self.seller)
        self.client.force_login(self.viewer)
        res = self.client.get(self.url)
        self.assertTrue(res.context["i_blocked"])
        self.assertIsNone(res.context["page_obj"])
        self.assertNotContains(res, "숨겨질 상품")
        self.assertContains(res, "차단한 이웃이에요")

    def test_blocked_by_seller_hides_products(self):
        make_product(self.seller, title="숨겨질 상품")
        Block.objects.create(blocker=self.seller, blocked=self.viewer)
        self.client.force_login(self.viewer)
        res = self.client.get(self.url)
        self.assertFalse(res.context["i_blocked"])
        self.assertTrue(res.context["blocked"])
        self.assertNotContains(res, "숨겨질 상품")

    def test_htmx_partial(self):
        res = self.client.get(self.url, {"tab": "sold"}, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="seller-panel")
        self.assertTemplateUsed(res, "accounts/partials/seller_panel.html")
        self.assertTemplateNotUsed(res, "base.html")

    def test_user_without_profile_renders(self):
        User.objects.create_user(username="noprofile")
        res = self.client.get(reverse("accounts:seller_profile", args=["noprofile"]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "36.5")
