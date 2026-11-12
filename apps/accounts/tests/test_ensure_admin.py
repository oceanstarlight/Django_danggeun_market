from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

User = get_user_model()
STRONG = "Adm1n-Pass-2026!"


def run(env):
    out = StringIO()
    with mock.patch.dict("os.environ", env, clear=False):
        call_command("ensure_admin", stdout=out)
    return out.getvalue()


class EnsureAdminTests(TestCase):
    def setUp(self):
        patcher = mock.patch.dict(
            "os.environ",
            {"DJANGO_SUPERUSER_USERNAME": "", "DJANGO_SUPERUSER_PASSWORD": "", "DJANGO_SUPERUSER_EMAIL": ""},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skips_without_env(self):
        out = run({})
        self.assertIn("건너뛰어요", out)
        self.assertFalse(User.objects.exists())

    def test_creates_superuser_with_profile(self):
        run({"DJANGO_SUPERUSER_USERNAME": "boss", "DJANGO_SUPERUSER_PASSWORD": STRONG, "DJANGO_SUPERUSER_EMAIL": "a@b.c"})
        u = User.objects.get(username="boss")
        self.assertTrue(u.is_superuser and u.is_staff)
        self.assertTrue(u.check_password(STRONG))
        self.assertEqual(u.email, "a@b.c")
        self.assertTrue(hasattr(u, "profile"))

    def test_resets_password_of_existing_user(self):
        User.objects.create_user("boss", password="old-Password-123")
        out = run({"DJANGO_SUPERUSER_USERNAME": "boss", "DJANGO_SUPERUSER_PASSWORD": STRONG})
        u = User.objects.get(username="boss")
        self.assertIn("재설정", out)
        self.assertTrue(u.check_password(STRONG))
        self.assertTrue(u.is_superuser)
        self.assertEqual(User.objects.count(), 1)

    def test_requires_both_values(self):
        with self.assertRaises(CommandError):
            run({"DJANGO_SUPERUSER_USERNAME": "boss"})

    def test_rejects_weak_password(self):
        with self.assertRaises(CommandError):
            run({"DJANGO_SUPERUSER_USERNAME": "boss", "DJANGO_SUPERUSER_PASSWORD": "1234"})
        self.assertFalse(User.objects.exists())

    def test_password_not_printed(self):
        out = run({"DJANGO_SUPERUSER_USERNAME": "boss", "DJANGO_SUPERUSER_PASSWORD": STRONG})
        self.assertNotIn(STRONG, out)
