import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django import forms
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Profile, Region
from apps.core.forms import StyledFormMixin
from apps.core.storage import StorageError, upload_image
from apps.core.templatetags import poly_tags
from apps.products.models import Category

User = get_user_model()


class PriceFilterTests(SimpleTestCase):
    def test_price_formats_with_comma(self):
        self.assertEqual(poly_tags.price(15000), "15,000원")
        self.assertEqual(poly_tags.price(1234567), "1,234,567원")

    def test_zero_is_free(self):
        self.assertEqual(poly_tags.price(0), "나눔")

    def test_none_and_invalid(self):
        self.assertEqual(poly_tags.price(None), "")
        self.assertEqual(poly_tags.price("abc"), "abc")


class TimeagoFilterTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()

    def ago(self, **kwargs):
        return poly_tags.timeago(self.now - timedelta(**kwargs), self.now)

    def test_ranges(self):
        self.assertEqual(self.ago(seconds=10), "방금 전")
        self.assertEqual(self.ago(minutes=3), "3분 전")
        self.assertEqual(self.ago(hours=2), "2시간 전")
        self.assertEqual(self.ago(days=3), "3일 전")

    def test_yesterday(self):
        # 고정 시각(KST 10시)에서 30시간 전 = 전날 새벽 → '어제'
        tz = timezone.get_current_timezone()
        now = timezone.make_aware(datetime(2026, 11, 12, 10, 0), tz)
        self.assertEqual(poly_tags.timeago(now - timedelta(hours=30), now), "어제")
        self.assertEqual(poly_tags.timeago(now - timedelta(hours=40), now), "2일 전")

    def test_old_date_format(self):
        old = self.now - timedelta(days=40)
        self.assertEqual(poly_tags.timeago(old, self.now), timezone.localtime(old).strftime("%Y.%m.%d"))

    def test_empty(self):
        self.assertEqual(poly_tags.timeago(None), "")


class StatusClassFilterTests(SimpleTestCase):
    def test_mapping(self):
        self.assertEqual(poly_tags.status_class("SELLING"), "badge-selling")
        self.assertEqual(poly_tags.status_class("RESERVED"), "badge-reserved")
        self.assertEqual(poly_tags.status_class("SOLD"), "badge-sold")
        self.assertEqual(poly_tags.status_class("???"), "badge-neutral")


class DisplayNameAndQuerystringTests(TestCase):
    def test_display_name_prefers_nickname(self):
        user = User.objects.create_user("tester", password="pw-12345678")
        self.assertEqual(poly_tags.display_name(user), "tester")
        Profile.objects.create(user=user, nickname="폴리", region=Region.objects.first())
        user.refresh_from_db()
        self.assertEqual(poly_tags.display_name(user), "폴리")

    def test_querystring_keeps_and_replaces(self):
        request = RequestFactory().get("/products/", {"q": "아이폰", "page": "1", "sort": "latest"})
        tpl = Template("{% load poly_tags %}{% querystring page=3 sort=None %}")
        result = tpl.render(Context({"request": request}))
        self.assertIn("page=3", result)
        self.assertIn("q=", result)
        self.assertNotIn("sort=", result)
        self.assertTrue(result.startswith("?"))


class SeedDataTests(TestCase):
    def test_regions_and_categories_seeded(self):
        self.assertGreaterEqual(Region.objects.count(), 40)
        self.assertEqual(Category.objects.count(), 15)
        self.assertEqual(Category.objects.first().slug, "digital")
        region = Region.objects.get(sigungu="강남구", dong="역삼동")
        self.assertEqual(region.name, "서울특별시 강남구 역삼동")


class StorageLocalTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.tmp, MEDIA_URL="/media/", USE_SUPABASE_STORAGE=False)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_saves_to_media_root(self):
        file = SimpleUploadedFile("photo.JPEG", b"\xff\xd8\xff fake jpeg", content_type="image/jpeg")
        url = upload_image(file, "products/1")
        self.assertTrue(url.startswith("/media/products/1/"))
        self.assertTrue(url.endswith(".jpg"))
        saved = Path(self.tmp) / url.removeprefix("/media/")
        self.assertTrue(saved.exists())
        self.assertEqual(saved.read_bytes(), b"\xff\xd8\xff fake jpeg")

    def test_folder_traversal_is_cleaned(self):
        file = SimpleUploadedFile("a.png", b"png", content_type="image/png")
        url = upload_image(file, "../../etc")
        self.assertTrue(url.startswith("/media/etc/"))

    def test_rejects_bad_extension(self):
        file = SimpleUploadedFile("evil.exe", b"MZ", content_type="application/octet-stream")
        with self.assertRaises(StorageError):
            upload_image(file, "products")

    def test_rejects_too_large(self):
        with override_settings(MAX_UPLOAD_IMAGE_SIZE=10):
            file = SimpleUploadedFile("big.png", b"x" * 11, content_type="image/png")
            with self.assertRaises(StorageError):
                upload_image(file, "products")


class StyledFormMixinTests(SimpleTestCase):
    class DemoForm(StyledFormMixin, forms.Form):
        name = forms.CharField()
        body = forms.CharField(widget=forms.Textarea)
        kind = forms.ChoiceField(choices=[("a", "A")])
        agree = forms.BooleanField(required=False)
        hidden = forms.CharField(widget=forms.HiddenInput, required=False)

    def test_classes(self):
        form = self.DemoForm()
        self.assertEqual(form.fields["name"].widget.attrs["class"], "input")
        self.assertEqual(form.fields["body"].widget.attrs["class"], "textarea")
        self.assertEqual(form.fields["kind"].widget.attrs["class"], "select")
        self.assertEqual(form.fields["agree"].widget.attrs["class"], "checkbox")
        self.assertNotIn("class", form.fields["hidden"].widget.attrs)


# spec 7절 URL 계약: (이름, args, 기대 경로)
URL_CONTRACT = [
    ("core:home", [], "/"),
    ("core:health", [], "/state/"),
    ("accounts:signup", [], "/accounts/signup/"),
    ("accounts:login", [], "/accounts/login/"),
    ("accounts:logout", [], "/accounts/logout/"),
    ("accounts:mypage", [], "/accounts/me/"),
    ("accounts:profile_edit", [], "/accounts/me/edit/"),
    ("accounts:seller_profile", ["polly"], "/users/polly/"),
    ("products:list", [], "/products/"),
    ("products:create", [], "/products/new/"),
    ("products:detail", [1], "/products/1/"),
    ("products:update", [1], "/products/1/edit/"),
    ("products:delete", [1], "/products/1/delete/"),
    ("products:wishlist_toggle", [1], "/products/1/wishlist/"),
    ("products:status_change", [1], "/products/1/status/"),
    ("chat:list", [], "/chats/"),
    ("chat:room", [1], "/chats/1/"),
    ("chat:start", [1], "/chats/start/1/"),
    ("chat:mark_read", [1], "/chats/1/read/"),
    ("trades:complete", [1], "/trades/1/complete/"),
    ("trades:review_create", [1], "/trades/1/review/"),
    ("notifications:list", [], "/notifications/"),
    ("notifications:dropdown", [], None),
    ("notifications:read_all", [], None),
    ("notifications:go", [1], "/notifications/1/go/"),
    ("notifications:badge", [], None),
    ("moderation:report_product", [1], "/moderation/report/product/1/"),
    ("moderation:report_user", ["polly"], "/moderation/report/user/polly/"),
    ("moderation:block_toggle", ["polly"], "/moderation/block/polly/"),
    ("moderation:block_list", [], "/moderation/blocks/"),
    ("ai:describe", [], None),
    ("ai:recognize", [], None),
    ("ai:negotiate", [1], "/ai/negotiate/1/"),
    ("ai:fraud_refresh", [1], "/ai/fraud/1/"),
]


class UrlContractTests(SimpleTestCase):
    def test_every_contract_url_reverses(self):
        for name, args, expected in URL_CONTRACT:
            with self.subTest(name=name):
                path = reverse(name, args=args)
                if expected is not None:
                    self.assertEqual(path, expected)
                else:
                    prefix = "/" + name.split(":")[0] + "/"
                    self.assertTrue(path.startswith(prefix), path)


class HealthTests(TestCase):
    def test_health_ok(self):
        response = self.client.get("/state/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "server OK")


class NavContextProcessorTests(TestCase):
    def test_nav_values(self):
        from apps.core.context_processors import nav

        user = User.objects.create_user("navuser", password="pw-12345678")
        request = RequestFactory().get("/")
        request.user = user
        ctx = nav(request)
        self.assertEqual(ctx["nav_unread_notifications"], 0)
        self.assertEqual(ctx["nav_unread_chats"], 0)
        self.assertEqual(ctx["nav_categories"].count(), 15)


class CrossAppServiceTests(TestCase):
    """foundation 이 제공하는 크로스 앱 서비스 계약."""

    def setUp(self):
        self.a = User.objects.create_user("alice", password="pw-12345678")
        self.b = User.objects.create_user("bob", password="pw-12345678")
        self.c = User.objects.create_user("carol", password="pw-12345678")

    def test_notify_and_collapse(self):
        from apps.notifications.models import Notification
        from apps.notifications.services import notify, unread_count

        n1 = notify(self.a, Notification.Kind.NEW_MESSAGE, "첫 메시지", url="/chats/1/", collapse_key=1)
        n2 = notify(self.a, Notification.Kind.NEW_MESSAGE, "둘째 메시지", url="/chats/1/", collapse_key=1)
        self.assertEqual(n1.pk, n2.pk)
        self.assertEqual(Notification.objects.get(pk=n1.pk).message, "둘째 메시지")
        notify(self.a, Notification.Kind.REVIEW, "후기가 도착했어요")
        self.assertEqual(unread_count(self.a), 2)
        self.assertEqual(unread_count(self.b), 0)

    def test_block_services(self):
        from apps.moderation.models import Block
        from apps.moderation.services import blocked_user_ids, is_blocked_between

        Block.objects.create(blocker=self.a, blocked=self.b)
        Block.objects.create(blocker=self.c, blocked=self.a)
        self.assertEqual(blocked_user_ids(self.a), {self.b.pk, self.c.pk})
        self.assertEqual(blocked_user_ids(self.b), {self.a.pk})
        self.assertTrue(is_blocked_between(self.b, self.a))
        self.assertFalse(is_blocked_between(self.b, self.c))

    def test_unread_chat_count(self):
        from apps.chat.models import ChatMessage, ChatRoom
        from apps.chat.services import unread_chat_count
        from apps.products.models import Product

        product = Product.objects.create(
            seller=self.a, category=Category.objects.first(), title="자전거", content="좋아요", price=10000
        )
        room = ChatRoom.objects.create(product=product, seller=self.a, buyer=self.b)
        ChatMessage.objects.create(room=room, sender=self.b, content="안녕하세요")
        ChatMessage.objects.create(room=room, sender=self.b, content="구매 가능할까요?")
        ChatMessage.objects.create(room=room, sender=self.a, content="네")
        self.assertEqual(unread_chat_count(self.a), 2)
        self.assertEqual(unread_chat_count(self.b), 1)
        self.assertEqual(room.unread_count_for(self.a), 2)
        self.assertEqual(room.other_user(self.a), self.b)
        self.assertIsNone(product.thumbnail_url)
        self.assertEqual(product.chat_count, 1)
        self.assertEqual(product.wish_count, 0)


class StyleguideTests(TestCase):
    """개발용 스타일가이드: DEBUG 에서만 열린다."""

    def test_hidden_when_not_debug(self):
        self.assertEqual(self.client.get("/dev/styleguide/").status_code, 404)

    @override_settings(DEBUG=True)
    def test_renders_in_debug(self):
        response = self.client.get(reverse("core:styleguide"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "components/_styleguide.html")
        self.assertContains(response, "스타일가이드")


class BaseLayoutTests(TestCase):
    """base.html 이 비로그인/로그인 모두에서 렌더되는지 (홈 화면 기준)."""

    def test_anonymous(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "base.html")
        self.assertContains(response, reverse("accounts:login"))
        self.assertContains(response, reverse("accounts:signup"))

    def test_logged_in(self):
        user = User.objects.create_user("layout", password="pw-12345678")
        Profile.objects.create(user=user, nickname="레이아웃", region=Region.objects.first())
        self.client.force_login(user)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "base.html")
        self.assertContains(response, "레이아웃")  # 프로필 메뉴의 display_name
        self.assertContains(response, reverse("accounts:logout"))
        self.assertContains(response, reverse("notifications:badge"))

    def test_logged_in_without_profile(self):
        # Profile 없는 사용자(예: createsuperuser)도 nav 가 깨지지 않아야 한다
        user = User.objects.create_user("noprofile", password="pw-12345678")
        self.client.force_login(user)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "noprofile")
