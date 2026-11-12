"""회원가입 · 로그인 · 로그아웃 · 중복 확인."""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts import services
from apps.accounts.forms import normalize_phone
from apps.accounts.models import Profile, Region

from .factories import make_user

User = get_user_model()


def signup_data(**overrides):
    data = {
        "username": "newbie_01",
        "nickname": "새내기",
        "name": "홍길동",
        "birth_date": "2000-01-15",
        "phone": "01012345678",
        "region": str(Region.objects.first().pk),
        "password1": "Poly-market-2026!",
        "password2": "Poly-market-2026!",
    }
    data.update(overrides)
    return data


class NormalizePhoneTests(TestCase):
    def test_formats(self):
        self.assertEqual(normalize_phone("01012345678"), "010-1234-5678")
        self.assertEqual(normalize_phone("010-1234-5678"), "010-1234-5678")
        self.assertEqual(normalize_phone("011 123 4567"), "011-123-4567")
        self.assertIsNone(normalize_phone("02-123-4567"))
        self.assertIsNone(normalize_phone(""))


class SignupTests(TestCase):
    url = reverse("accounts:signup")

    def test_get_renders_form_with_region_groups(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "accounts/signup.html")
        self.assertContains(res, "<optgroup", html=False)
        self.assertContains(res, 'id="check-username"')

    def test_signup_creates_user_profile_and_logs_in(self):
        res = self.client.post(self.url, signup_data())
        self.assertRedirects(res, reverse("core:home"), fetch_redirect_response=False)
        user = User.objects.get(username="newbie_01")
        self.assertEqual(user.first_name, "홍길동")
        self.assertEqual(user.profile.nickname, "새내기")
        self.assertEqual(user.profile.phone, "010-1234-5678")
        self.assertEqual(user.profile.birth_date, date(2000, 1, 15))
        self.assertEqual(user.profile.region, Region.objects.first())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_signup_redirects_to_safe_next_only(self):
        res = self.client.post(self.url + "?next=/accounts/me/", {**signup_data(), "next": "/accounts/me/"})
        self.assertRedirects(res, "/accounts/me/", fetch_redirect_response=False)
        self.client.logout()
        res = self.client.post(
            self.url,
            {**signup_data(username="other_02", nickname="다른이웃", phone="01099998888"), "next": "https://evil.example/"},
        )
        self.assertRedirects(res, reverse("core:home"), fetch_redirect_response=False)

    def test_duplicates_are_rejected(self):
        make_user(username="Taken_ID", nickname="중복닉", phone="010-1234-5678")
        res = self.client.post(
            self.url, signup_data(username="taken_id", nickname="중복닉", phone="010-1234-5678")
        )
        self.assertEqual(res.status_code, 200)
        form = res.context["form"]
        self.assertIn("이미 사용 중인 아이디예요.", form.errors["username"])
        self.assertIn("이미 사용 중인 닉네임이에요.", form.errors["nickname"])
        self.assertIn("이미 가입된 휴대폰 번호예요.", form.errors["phone"])
        self.assertFalse(User.objects.filter(username="taken_id").exists())

    def test_format_and_password_validation(self):
        res = self.client.post(
            self.url,
            signup_data(username="a!", nickname="x", phone="12345", password2="different-pass", region=""),
        )
        form = res.context["form"]
        for field in ("username", "nickname", "phone", "password2", "region"):
            self.assertIn(field, form.errors, field)
        self.assertEqual(User.objects.count(), 0)

    def test_future_birth_date_rejected(self):
        res = self.client.post(self.url, signup_data(birth_date="2999-01-01"))
        self.assertIn("birth_date", res.context["form"].errors)

    def test_logged_in_user_is_redirected(self):
        self.client.force_login(make_user())
        self.assertRedirects(self.client.get(self.url), reverse("core:home"), fetch_redirect_response=False)


class RegisterServiceTests(TestCase):
    def test_integrity_error_becomes_account_error(self):
        make_user(nickname="겹침")
        with self.assertRaises(services.AccountError):
            services.register_user(username="unique_1", password="x-Pass-1234", nickname="겹침")
        self.assertFalse(User.objects.filter(username="unique_1").exists())

    def test_ensure_profile_creates_unique_nickname(self):
        admin = User.objects.create_user(username="admin")
        make_user(nickname="admin")
        profile = services.ensure_profile(admin)
        self.assertEqual(profile.nickname, "admin2")
        self.assertEqual(Profile.objects.get(user=admin), profile)
        self.assertEqual(services.ensure_profile(admin), profile)  # 두 번째는 그대로


class CheckDuplicateTests(TestCase):
    url = reverse("accounts:check_duplicate")

    def test_username(self):
        make_user(username="exists_1")
        self.assertContains(self.client.get(self.url, {"username": "EXISTS_1"}), "이미 사용 중인 아이디예요.")
        self.assertContains(self.client.get(self.url, {"username": "fresh_1"}), "사용할 수 있는 아이디예요.")
        self.assertContains(self.client.get(self.url, {"username": "a"}), "4~20자")

    def test_nickname_excludes_self(self):
        me = make_user(nickname="내닉네임")
        self.assertContains(self.client.get(self.url, {"nickname": "내닉네임"}), "이미 사용 중인 닉네임이에요.")
        self.client.force_login(me)
        self.assertContains(self.client.get(self.url, {"nickname": "내닉네임"}), "멋진 닉네임이에요!")

    def test_phone(self):
        make_user(phone="010-1111-2222")
        self.assertContains(self.client.get(self.url, {"phone": "01011112222"}), "이미 가입된 휴대폰 번호예요.")
        self.assertContains(self.client.get(self.url, {"phone": "010-3333-4444"}), "사용할 수 있는 번호예요.")
        self.assertContains(self.client.get(self.url, {"phone": "abc"}), "형식으로")

    def test_empty_value_renders_nothing(self):
        res = self.client.get(self.url, {"username": ""})
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "<p")


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = make_user(username="loginme", nickname="로그인이웃", password="Secret-pass-99")

    def test_login_success_redirects_to_next(self):
        res = self.client.post(
            reverse("accounts:login"),
            {"username": "loginme", "password": "Secret-pass-99", "remember": "on", "next": "/accounts/me/"},
        )
        self.assertRedirects(res, "/accounts/me/", fetch_redirect_response=False)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_login_without_remember_expires_at_browser_close(self):
        self.client.post(reverse("accounts:login"), {"username": "loginme", "password": "Secret-pass-99"})
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_login_failure_shows_error(self):
        res = self.client.post(reverse("accounts:login"), {"username": "loginme", "password": "wrong"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "아이디 또는 비밀번호를 다시 확인해 주세요.")

    def test_login_rejects_external_next(self):
        res = self.client.post(
            reverse("accounts:login"),
            {"username": "loginme", "password": "Secret-pass-99", "next": "//evil.example/"},
        )
        self.assertRedirects(res, reverse("core:home"), fetch_redirect_response=False)

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        res = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(res, reverse("core:home"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
