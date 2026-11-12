"""products 앱 테스트 (모델 헬퍼 · selectors · services · 뷰 권한/흐름)."""

import io
import json
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import Profile, Region
from apps.chat.models import ChatRoom
from apps.moderation.models import Block
from apps.notifications.models import Notification

from . import selectors, services
from .forms import MAX_IMAGES
from .models import Category, Product, ProductImage, RecentView, Wishlist

User = get_user_model()
TEMP_MEDIA = tempfile.mkdtemp(prefix="poly-test-media-")


def make_png(name="photo.png", color=(13, 148, 136)):
    """Pillow 로 진짜 PNG 를 만든다."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def toast_message(response):
    """HX-Trigger 헤더의 showToast 메시지 (ASCII 로 이스케이프돼 있어야 함)."""
    header = response["HX-Trigger"]
    header.encode("ascii")  # 비 ASCII 면 htmx 가 못 읽는 MIME 인코딩이 돼요
    return json.loads(header)["showToast"]["message"]


class ProductTestMixin:
    """공용 픽스처: 지역 2곳, 카테고리, 판매자/구매자/기타 사용자."""

    @classmethod
    def setUpTestData(cls):
        regions = list(Region.objects.all()[:2])
        cls.region, cls.other_region = regions[0], regions[1]
        cls.category = Category.objects.get(slug="digital")
        cls.other_category = Category.objects.get(slug="books")
        cls.seller = cls.make_user("seller", "판매자", cls.region)
        cls.buyer = cls.make_user("buyer", "구매자", cls.region)
        cls.stranger = cls.make_user("stranger", "이웃", cls.other_region)

    @staticmethod
    def make_user(username, nickname, region=None, **extra):
        user = User.objects.create_user(username=username, password="pass-1234!", **extra)
        Profile.objects.create(user=user, nickname=nickname, region=region)
        return user

    def make_product(self, seller=None, **kwargs):
        defaults = {
            "category": self.category,
            "region": self.region,
            "title": "아이폰 15 프로",
            "content": "깨끗하게 사용했어요. 직거래 원해요.",
            "price": 900000,
        }
        defaults.update(kwargs)
        return Product.objects.create(seller=seller or self.seller, **defaults)

    def form_data(self, **overrides):
        data = {
            "title": "맥북 에어 M2",
            "category": self.category.pk,
            "condition": Product.Condition.LIKE_NEW,
            "price": "1200000",
            "negotiable": "on",
            "region": self.region.pk,
            "content": "배터리 사이클 30회, 박스 포함이에요.",
        }
        data.update(overrides)
        return data


# ───────────────────────── selectors ─────────────────────────


class SelectorTests(ProductTestMixin, TestCase):
    def test_card_data_counts_are_annotated_without_row_multiplication(self):
        product = self.make_product()
        Wishlist.objects.create(user=self.buyer, product=product)
        Wishlist.objects.create(user=self.stranger, product=product)
        ChatRoom.objects.create(product=product, seller=self.seller, buyer=self.buyer)
        row = selectors.with_card_data(Product.objects.filter(pk=product.pk)).get()
        self.assertEqual(row.num_wishes, 2)
        self.assertEqual(row.num_chats, 1)
        self.assertEqual(row.wish_count, 2)
        self.assertEqual(row.chat_count, 1)

    def test_search_terms_category_status_and_sort(self):
        cheap = self.make_product(title="갤럭시 버즈", price=30000)
        pricey = self.make_product(title="갤럭시 S24 울트라", price=1100000)
        self.make_product(title="해리포터 전집", category=self.other_category, price=50000)
        sold = self.make_product(title="갤럭시 탭", price=200000, status=Product.Status.SOLD)

        found = list(selectors.search_products(None, q="갤럭시"))
        self.assertCountEqual(found, [cheap, pricey, sold])
        # 여러 단어는 AND
        self.assertEqual(list(selectors.search_products(None, q="갤럭시 울트라")), [pricey])
        # 카테고리
        books = list(selectors.search_products(None, category=self.other_category))
        self.assertEqual([p.title for p in books], ["해리포터 전집"])
        # 거래 가능만
        selling = selectors.search_products(None, q="갤럭시", status="selling")
        self.assertNotIn(sold, selling)
        # 정렬
        asc = list(selectors.search_products(None, q="갤럭시", sort="price_asc"))
        self.assertEqual(asc[0], cheap)
        desc = list(selectors.search_products(None, q="갤럭시", sort="price_desc"))
        self.assertEqual(desc[0], pricey)

    def test_popular_sort_uses_wishes(self):
        a = self.make_product(title="A")
        b = self.make_product(title="B")
        Wishlist.objects.create(user=self.buyer, product=b)
        self.assertEqual(list(selectors.search_products(None, sort="popular"))[:2], [b, a])
        self.assertEqual(selectors.popular_products(None)[0], b)

    def test_blocked_users_products_are_hidden_both_directions(self):
        mine = self.make_product(seller=self.stranger, title="이웃 상품")
        Block.objects.create(blocker=self.buyer, blocked=self.stranger)
        self.assertNotIn(mine, selectors.search_products(self.buyer))
        self.assertNotIn(mine, selectors.latest_products(self.buyer))
        # 차단당한 쪽에서도 안 보임
        own = self.make_product(seller=self.buyer, title="구매자 상품")
        self.assertNotIn(own, selectors.search_products(self.stranger))
        # 제3자는 그대로 보임
        self.assertIn(mine, selectors.search_products(self.seller))

    def test_resolve_region(self):
        self.assertEqual(selectors.resolve_region(self.buyer, ""), ("me", self.region))
        self.assertEqual(selectors.resolve_region(self.buyer, "all"), ("all", None))
        self.assertEqual(
            selectors.resolve_region(self.buyer, str(self.other_region.pk)),
            (str(self.other_region.pk), self.other_region),
        )
        # 내 동네 id 를 직접 고르면 'me' 로 취급
        self.assertEqual(selectors.resolve_region(self.buyer, str(self.region.pk)), ("me", self.region))
        # 동네가 없는 사용자/비로그인/잘못된 값 → 전체
        no_region = self.make_user("noregion", "무동네")
        self.assertEqual(selectors.resolve_region(no_region, ""), ("all", None))
        self.assertEqual(selectors.resolve_region(no_region, "me"), ("all", None))
        self.assertEqual(selectors.resolve_region(None, "abc"), ("all", None))
        self.assertEqual(selectors.resolve_region(None, "999999"), ("all", None))

    def test_wishlisted_products_keeps_total_wish_count(self):
        product = self.make_product()
        Wishlist.objects.create(user=self.buyer, product=product)
        Wishlist.objects.create(user=self.stranger, product=product)
        rows = list(selectors.wishlisted_products(self.buyer))
        self.assertEqual(rows, [product])
        self.assertEqual(rows[0].wish_count, 2)

    def test_recent_viewed_products(self):
        p1 = self.make_product(title="첫번째")
        p2 = self.make_product(title="두번째")
        services.record_view(p1, self.buyer)
        services.record_view(p2, self.buyer)
        self.assertEqual(selectors.recent_viewed_products(self.buyer), [p2, p1])
        self.assertEqual(selectors.recent_viewed_products(None), [])


# ───────────────────────── services ─────────────────────────


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ServiceTests(ProductTestMixin, TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def test_create_product_saves_images_in_order_and_runs_fraud_analysis(self):
        data = {"title": "자전거", "category": self.category, "region": self.region, "content": "잘 나가요", "price": 0,
                "negotiable": True, "condition": Product.Condition.GOOD}
        with mock.patch("apps.ai.services.fraud.analyze_product") as analyze:
            product = services.create_product(self.seller, data, [make_png("a.png"), make_png("b.png")])
        analyze.assert_called_once_with(product)
        self.assertFalse(product.negotiable)  # 나눔이면 가격 제안 꺼짐
        self.assertEqual(list(product.images.values_list("order", flat=True)), [0, 1])
        self.assertTrue(product.thumbnail_url.startswith("/media/products/"))

    def test_fraud_analysis_failure_does_not_break_save(self):
        data = {"title": "자전거", "category": self.category, "content": "잘 나가요", "price": 1000}
        with mock.patch("apps.ai.services.fraud.analyze_product", side_effect=RuntimeError("boom")):
            with self.assertLogs("apps.products.services", level="ERROR"):
                product = services.create_product(self.seller, data)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

    def test_update_product_removes_adds_and_renumbers_images(self):
        product = self.make_product()
        imgs = [ProductImage.objects.create(product=product, image_url=f"/media/x{i}.png", order=i) for i in range(3)]
        services.update_product(product, {"title": "새 제목"}, new_images=[make_png()], remove_images=[imgs[0]])
        product.refresh_from_db()
        self.assertEqual(product.title, "새 제목")
        rows = list(product.images.order_by("order"))
        self.assertEqual([r.order for r in rows], [0, 1, 2])
        self.assertEqual(rows[0].pk, imgs[1].pk)  # 대표 사진이 다음 사진으로
        self.assertNotIn(imgs[0].pk, [r.pk for r in rows])

    def test_price_change_notifies_wishers_except_seller(self):
        product = self.make_product(price=10000)
        Wishlist.objects.create(user=self.buyer, product=product)
        Wishlist.objects.create(user=self.stranger, product=product)
        services.update_product(product, {"price": 8000})
        notes = Notification.objects.filter(kind=Notification.Kind.PRICE_CHANGE)
        self.assertEqual(notes.count(), 2)
        self.assertFalse(notes.filter(user=self.seller).exists())
        note = notes.get(user=self.buyer)
        self.assertIn("10,000원에서 8,000원으로 내려갔어요", note.message)
        self.assertEqual(note.url, reverse("products:detail", args=[product.pk]))
        # 다시 바꾸면 안 읽은 알림을 갱신 (collapse)
        services.update_product(product, {"price": 7000})
        self.assertEqual(Notification.objects.filter(user=self.buyer, kind=Notification.Kind.PRICE_CHANGE).count(), 1)

    def test_same_price_sends_no_notification(self):
        product = self.make_product(price=10000)
        Wishlist.objects.create(user=self.buyer, product=product)
        services.update_product(product, {"price": 10000, "title": "제목만 바꿈"})
        self.assertFalse(Notification.objects.exists())

    def test_toggle_wishlist(self):
        product = self.make_product()
        self.assertTrue(services.toggle_wishlist(self.buyer, product))
        self.assertTrue(Wishlist.objects.filter(user=self.buyer, product=product).exists())
        self.assertFalse(services.toggle_wishlist(self.buyer, product))
        self.assertFalse(Wishlist.objects.exists())
        with self.assertRaises(services.ProductActionError):
            services.toggle_wishlist(self.seller, product)

    def test_change_status(self):
        product = self.make_product(status=Product.Status.SOLD, buyer=self.buyer)
        self.assertTrue(services.change_status(product, Product.Status.SELLING))
        product.refresh_from_db()
        self.assertEqual(product.status, Product.Status.SELLING)
        self.assertIsNone(product.buyer)  # 거래완료 취소 시 구매자 해제
        self.assertFalse(services.change_status(product, Product.Status.SELLING))
        with self.assertRaises(services.ProductActionError):
            services.change_status(product, Product.Status.SOLD)
        with self.assertRaises(services.ProductActionError):
            services.change_status(product, "WHATEVER")

    def test_record_view_skips_owner_and_prunes(self):
        product = self.make_product()
        services.record_view(product, self.seller)
        product.refresh_from_db()
        self.assertEqual(product.view_count, 0)
        self.assertFalse(RecentView.objects.filter(user=self.seller).exists())
        services.record_view(product, self.buyer)
        services.record_view(product, None)
        product.refresh_from_db()
        self.assertEqual(product.view_count, 2)
        self.assertEqual(RecentView.objects.filter(user=self.buyer).count(), 1)

        with mock.patch.object(services, "RECENT_VIEW_LIMIT", 2):
            for i in range(3):
                services.record_view(self.make_product(title=f"p{i}"), self.buyer, count=False)
        self.assertEqual(RecentView.objects.filter(user=self.buyer).count(), 2)


# ───────────────────────── 홈 / 목록 ─────────────────────────


class HomeViewTests(ProductTestMixin, TestCase):
    def test_anonymous_home(self):
        self.make_product(title="동네 자전거")
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, "방금 올라온 상품")
        self.assertContains(response, "동네 자전거")
        self.assertContains(response, "디지털기기")  # 카테고리 그리드

    def test_logged_in_home_shows_my_region_popular_and_recent(self):
        local = self.make_product(title="우리동네 책상")
        far = self.make_product(title="먼동네 의자", region=self.other_region, seller=self.stranger)
        Wishlist.objects.create(user=self.stranger, product=local)
        services.record_view(far, self.buyer)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"{self.region.dong} 최신 상품")
        self.assertEqual(response.context["local_products"], [local])
        self.assertEqual(response.context["popular_products"][0], local)
        self.assertEqual(response.context["recent_products"], [far])
        self.assertContains(response, "최근 본 상품")

    def test_home_query_count_is_bounded(self):
        for i in range(12):
            p = self.make_product(title=f"상품{i}")
            ProductImage.objects.create(product=p, image_url=f"/media/{i}.png")
        self.client.force_login(self.buyer)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(reverse("core:home"))
        self.assertLess(len(ctx.captured_queries), 25)


class ProductListViewTests(ProductTestMixin, TestCase):
    def test_list_default_region_is_mine(self):
        local = self.make_product(title="우리동네")
        far = self.make_product(title="먼동네", region=self.other_region)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("products:list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["region_value"], "me")
        self.assertIn(local, response.context["products"])
        self.assertNotIn(far, response.context["products"])
        response = self.client.get(reverse("products:list"), {"region": "all"})
        self.assertIn(far, response.context["products"])

    def test_anonymous_sees_all_regions_and_bad_params_are_ignored(self):
        far = self.make_product(region=self.other_region)
        response = self.client.get(
            reverse("products:list"), {"sort": "hack", "status": "??", "category": "nope", "page": "x"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(far, response.context["products"])
        self.assertEqual(response.context["sort_value"], "latest")

    def test_search_empty_state(self):
        response = self.client.get(reverse("products:list"), {"q": "존재하지않는물건"})
        self.assertContains(response, "검색 결과가 없어요")

    def test_htmx_returns_partial_and_load_more(self):
        for i in range(selectors.PAGE_SIZE + 3):
            self.make_product(title=f"상품{i:02d}")
        response = self.client.get(reverse("products:list"), {"region": "all"}, HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(response, "products/partials/product_grid.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertContains(response, 'id="load-more"')
        self.assertContains(response, "page=2")

        page2 = self.client.get(reverse("products:list"), {"region": "all", "page": 2}, HTTP_HX_REQUEST="true")
        self.assertTrue(page2.context["is_append"])
        self.assertNotContains(page2, 'id="product-grid"')
        self.assertNotContains(page2, 'id="load-more"')
        self.assertContains(page2, "모든 상품을 다 봤어요")
        self.assertEqual(len(page2.context["products"]), 3)

    def test_list_has_no_n_plus_one(self):
        def count_queries():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse("products:list"), {"region": "all"})
            return len(ctx.captured_queries)

        self.client.force_login(self.buyer)
        for i in range(3):
            p = self.make_product(title=f"a{i}")
            ProductImage.objects.create(product=p, image_url="/media/a.png")
        few = count_queries()
        for i in range(12):
            p = self.make_product(title=f"b{i}")
            ProductImage.objects.create(product=p, image_url="/media/b.png")
            Wishlist.objects.create(user=self.stranger, product=p)
        many = count_queries()
        self.assertEqual(few, many)

    def test_blocked_seller_hidden_in_list(self):
        hidden = self.make_product(seller=self.stranger)
        Block.objects.create(blocker=self.stranger, blocked=self.buyer)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("products:list"), {"region": "all"})
        self.assertNotIn(hidden, response.context["products"])


# ───────────────────────── 상세 ─────────────────────────


class ProductDetailViewTests(ProductTestMixin, TestCase):
    def test_sold_product_chat_button_disabled_for_anonymous(self):
        product = self.make_product(status=Product.Status.SOLD)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertContains(response, "거래가 끝났어요")
        self.assertNotContains(response, "채팅하기</a>")

    def test_detail_renders_and_counts_view_once_per_session(self):
        product = self.make_product()
        ProductImage.objects.create(product=product, image_url="/media/1.png", order=0)
        ProductImage.objects.create(product=product, image_url="/media/2.png", order=1)
        url = reverse("products:detail", args=[product.pk])
        self.client.force_login(self.buyer)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, product.title)
        self.assertContains(response, "data-gallery-thumb")
        self.assertContains(response, reverse("chat:start", args=[product.pk]))
        self.client.get(url)
        product.refresh_from_db()
        self.assertEqual(product.view_count, 1)
        self.assertTrue(RecentView.objects.filter(user=self.buyer, product=product).exists())

    def test_missing_product_404(self):
        self.assertEqual(self.client.get(reverse("products:detail", args=[999999])).status_code, 404)

    def test_owner_sees_manage_panel_and_no_view_count(self):
        product = self.make_product()
        self.client.force_login(self.seller)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertContains(response, "내 상품 관리")
        self.assertContains(response, reverse("products:status_change", args=[product.pk]))
        self.assertContains(response, reverse("trades:complete", args=[product.pk]))
        self.assertNotContains(response, reverse("chat:start", args=[product.pk]))
        product.refresh_from_db()
        self.assertEqual(product.view_count, 0)

    def test_existing_chat_room_link(self):
        product = self.make_product()
        room = ChatRoom.objects.create(product=product, seller=self.seller, buyer=self.buyer)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertContains(response, reverse("chat:room", args=[room.pk]))

    def test_blocked_relation_hides_chat_and_wish(self):
        product = self.make_product()
        Block.objects.create(blocker=self.buyer, blocked=self.seller)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertContains(response, "차단 관계인 사용자의 상품이에요")
        self.assertNotContains(response, reverse("chat:start", args=[product.pk]))
        self.assertNotContains(response, reverse("products:wishlist_toggle", args=[product.pk]))

    def test_fraud_banner_included_when_analysis_exists(self):
        from apps.ai.models import FraudAnalysis

        product = self.make_product()
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertTemplateNotUsed(response, "ai/partials/fraud_banner.html")
        FraudAnalysis.objects.create(
            product=product, content_hash="x" * 64, risk_level=FraudAnalysis.RiskLevel.HIGH, risk_score=90
        )
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertTemplateUsed(response, "ai/partials/fraud_banner.html")
        self.assertEqual(response.context["fraud_analysis"].risk_score, 90)

    def test_review_link_for_sold_product_participants(self):
        product = self.make_product(status=Product.Status.SOLD, buyer=self.buyer)
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertEqual(response.context["review_url"], reverse("trades:review_create", args=[product.pk]))
        self.client.force_login(self.stranger)
        response = self.client.get(reverse("products:detail", args=[product.pk]))
        self.assertIsNone(response.context["review_url"])
        self.assertContains(response, "거래가 끝났어요")


# ───────────────────────── 등록 / 수정 / 삭제 ─────────────────────────


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ProductFormViewTests(ProductTestMixin, TestCase):
    def test_create_requires_login(self):
        response = self.client.get(reverse("products:create"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_create_form_defaults_to_my_region_and_has_contract_ids(self):
        self.client.force_login(self.buyer)
        response = self.client.get(reverse("products:create"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["region"], self.region.pk)
        for element_id in ("id_title", "id_content", "id_category", "id_condition", "id_price", "id_images"):
            self.assertContains(response, f'id="{element_id}"')
        self.assertContains(response, 'name="images"')
        self.assertContains(response, 'multiple')
        self.assertTemplateUsed(response, "ai/partials/product_form_ai_panel.html")

    def test_create_with_images(self):
        self.client.force_login(self.seller)
        data = self.form_data(images=[make_png("1.png"), make_png("2.png")])
        with mock.patch("apps.ai.services.fraud.analyze_product") as analyze:
            response = self.client.post(reverse("products:create"), data)
        product = Product.objects.get(title="맥북 에어 M2")
        self.assertRedirects(response, reverse("products:detail", args=[product.pk]), fetch_redirect_response=False)
        self.assertEqual(product.seller, self.seller)
        self.assertTrue(product.negotiable)
        self.assertEqual(product.images.count(), 2)
        analyze.assert_called_once()

    def test_create_rejects_too_many_and_fake_images(self):
        self.client.force_login(self.seller)
        too_many = [make_png(f"{i}.png") for i in range(MAX_IMAGES + 1)]
        response = self.client.post(reverse("products:create"), self.form_data(images=too_many))
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "images", f"사진은 최대 {MAX_IMAGES}장까지 올릴 수 있어요. (지금 11장)")

        fake = SimpleUploadedFile("evil.png", b"not an image", content_type="image/png")
        response = self.client.post(reverse("products:create"), self.form_data(images=[fake]))
        self.assertIn("evil.png: 이미지 파일을 읽을 수 없어요.", response.context["form"].errors["images"])

        bad_ext = SimpleUploadedFile("doc.pdf", b"%PDF", content_type="application/pdf")
        response = self.client.post(reverse("products:create"), self.form_data(images=[bad_ext]))
        self.assertTrue(response.context["form"].errors["images"])
        self.assertFalse(Product.objects.exists())

    def test_create_validation_errors(self):
        self.client.force_login(self.seller)
        response = self.client.post(reverse("products:create"), self.form_data(title="a", content="짧", price="-1"))
        form = response.context["form"]
        self.assertIn("title", form.errors)
        self.assertIn("content", form.errors)
        self.assertIn("price", form.errors)

    def test_update_permissions(self):
        product = self.make_product()
        url = reverse("products:update", args=[product.pk])
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.form_data()).status_code, 403)
        self.assertEqual(self.client.get(reverse("products:update", args=[999999])).status_code, 404)

    def test_update_removes_selected_images_and_notifies_wishers(self):
        product = self.make_product(price=1000000)
        keep = ProductImage.objects.create(product=product, image_url="/media/keep.png", order=0)
        drop = ProductImage.objects.create(product=product, image_url="/media/drop.png", order=1)
        Wishlist.objects.create(user=self.buyer, product=product)
        self.client.force_login(self.seller)
        response = self.client.get(reverse("products:update", args=[product.pk]))
        self.assertContains(response, "/media/drop.png")
        self.assertContains(response, 'name="remove_images"')

        data = self.form_data(price="800000", remove_images=[drop.pk], images=[make_png()])
        response = self.client.post(reverse("products:update", args=[product.pk]), data)
        self.assertRedirects(response, reverse("products:detail", args=[product.pk]), fetch_redirect_response=False)
        product.refresh_from_db()
        self.assertEqual(product.price, 800000)
        urls = list(product.images.values_list("image_url", flat=True))
        self.assertEqual(urls[0], keep.image_url)
        self.assertNotIn(drop.image_url, urls)
        self.assertEqual(len(urls), 2)
        self.assertTrue(
            Notification.objects.filter(user=self.buyer, kind=Notification.Kind.PRICE_CHANGE).exists()
        )

    def test_update_cannot_remove_other_products_images(self):
        product = self.make_product()
        other = self.make_product(seller=self.stranger)
        foreign = ProductImage.objects.create(product=other, image_url="/media/other.png")
        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("products:update", args=[product.pk]), self.form_data(remove_images=[foreign.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("remove_images", response.context["form"].errors)
        self.assertTrue(ProductImage.objects.filter(pk=foreign.pk).exists())

    def test_update_respects_image_limit_with_existing(self):
        product = self.make_product()
        for i in range(MAX_IMAGES):
            ProductImage.objects.create(product=product, image_url=f"/media/{i}.png", order=i)
        self.client.force_login(self.seller)
        response = self.client.post(
            reverse("products:update", args=[product.pk]), self.form_data(images=[make_png()])
        )
        self.assertIn("images", response.context["form"].errors)

    def test_delete_flow_and_permissions(self):
        product = self.make_product()
        url = reverse("products:delete", args=[product.pk])
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(url), "이 상품을 삭제할까요?")
        response = self.client.post(url)
        self.assertRedirects(response, reverse("accounts:mypage"), fetch_redirect_response=False)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

    def test_staff_can_delete(self):
        product = self.make_product()
        staff = self.make_user("staff", "운영자", is_staff=True)
        self.client.force_login(staff)
        self.client.post(reverse("products:delete", args=[product.pk]))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())


# ───────────────────────── 찜 / 상태 변경 ─────────────────────────


class WishlistViewTests(ProductTestMixin, TestCase):
    def setUp(self):
        self.product = self.make_product()
        self.url = reverse("products:wishlist_toggle", args=[self.product.pk])

    def test_get_not_allowed(self):
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_anonymous_redirects_to_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
        response = self.client.post(
            self.url, HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL=f"http://testserver/products/{self.product.pk}/"
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], f"{reverse('accounts:login')}?next=/products/{self.product.pk}/")

    def test_toggle_regular_post(self):
        self.client.force_login(self.buyer)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("products:detail", args=[self.product.pk]), fetch_redirect_response=False)
        self.assertTrue(Wishlist.objects.filter(user=self.buyer, product=self.product).exists())

    def test_toggle_htmx_returns_button_partial(self):
        self.client.force_login(self.buyer)
        response = self.client.post(self.url, {"variant": "cta"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "products/partials/wishlist_button.html")
        self.assertContains(response, 'id="wish-cta"')
        self.assertContains(response, 'id="wish-default"')
        self.assertContains(response, 'hx-swap-oob="true"')
        self.assertContains(response, 'aria-pressed="true"')
        self.assertEqual(toast_message(response), "찜했어요")

        response = self.client.post(self.url, HTTP_HX_REQUEST="true")
        self.assertEqual(toast_message(response), "찜을 해제했어요")
        self.assertFalse(Wishlist.objects.exists())

    def test_cannot_wish_own_or_blocked(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertIn("내 상품은 찜할 수 없어요", toast_message(response))

        Block.objects.create(blocker=self.seller, blocked=self.buyer)
        self.client.force_login(self.buyer)
        self.client.post(self.url)
        self.assertFalse(Wishlist.objects.exists())

    def test_unsafe_next_is_ignored(self):
        self.client.force_login(self.buyer)
        response = self.client.post(self.url, {"next": "https://evil.example.com/"})
        self.assertEqual(response["Location"], reverse("products:detail", args=[self.product.pk]))


class StatusChangeViewTests(ProductTestMixin, TestCase):
    def setUp(self):
        self.product = self.make_product()
        self.url = reverse("products:status_change", args=[self.product.pk])

    def test_owner_can_reserve(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url, {"status": Product.Status.RESERVED})
        self.assertRedirects(response, reverse("products:detail", args=[self.product.pk]), fetch_redirect_response=False)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.RESERVED)

    def test_sold_redirects_to_trade_complete(self):
        self.client.force_login(self.seller)
        response = self.client.post(self.url, {"status": Product.Status.SOLD})
        self.assertRedirects(response, reverse("trades:complete", args=[self.product.pk]), fetch_redirect_response=False)
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SELLING)

    def test_htmx_uses_hx_redirect_and_next(self):
        self.client.force_login(self.seller)
        response = self.client.post(
            self.url, {"status": Product.Status.RESERVED, "next": "/chats/"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], "/chats/")

    def test_invalid_status_and_permissions(self):
        self.client.force_login(self.seller)
        self.client.post(self.url, {"status": "BOGUS"})
        self.product.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.SELLING)
        self.client.force_login(self.buyer)
        self.assertEqual(self.client.post(self.url, {"status": Product.Status.RESERVED}).status_code, 403)
        self.assertEqual(self.client.get(self.url).status_code, 405)


class PopularExcludesHighRiskTests(TestCase):
    """인기 상품 TOP 에서 사기 위험 '높음' 상품은 빠진다 (통합 단계 추가)."""

    def test_high_risk_excluded(self):
        from apps.ai.models import FraudAnalysis

        seller = get_user_model().objects.create_user("risk_seller", password="x-pass-1234")
        category = Category.objects.first()
        safe = Product.objects.create(seller=seller, category=category, title="정상 상품", content="내용", price=1000)
        risky = Product.objects.create(seller=seller, category=category, title="의심 상품", content="내용", price=1000)
        FraudAnalysis.objects.create(
            product=risky, content_hash="x" * 64, risk_level="HIGH", risk_score=90, reasons=[], rule_hits=[], source="RULE"
        )
        popular = selectors.popular_products(None)
        self.assertIn(safe, popular)
        self.assertNotIn(risky, popular)


class SearchDefaultsToAllRegionsTests(TestCase):
    """상단 검색창(region 파라미터 없음)으로 검색하면 전체 지역에서 찾는다 (통합 단계 추가)."""

    def test_query_without_region_searches_all(self):
        mine, other = Region.objects.all()[:2]
        buyer = get_user_model().objects.create_user("search_buyer", password="x-pass-1234")
        Profile.objects.create(user=buyer, nickname="검색러", region=mine)
        seller = get_user_model().objects.create_user("far_seller", password="x-pass-1234")
        far = Product.objects.create(
            seller=seller, category=Category.objects.first(), region=other, title="먼동네 자전거", content="내용", price=1000
        )
        self.client.force_login(buyer)
        response = self.client.get(reverse("products:list"), {"q": "자전거"})
        self.assertContains(response, far.title)
        # 동네를 직접 고르면 그 동네만
        response = self.client.get(reverse("products:list"), {"q": "자전거", "region": "me"})
        self.assertNotContains(response, far.title)
