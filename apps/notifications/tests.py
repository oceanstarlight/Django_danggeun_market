"""알림 서비스 · 목록 · 드롭다운/배지(HTMX) · 모두 읽음 · 이동 테스트."""

import json

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import selectors, services
from .models import Notification

User = get_user_model()
HTMX = {"HTTP_HX_REQUEST": "true"}
Kind = Notification.Kind


class NotificationFixtureMixin:
    def setUp(self):
        self.user = User.objects.create_user("noti_user", password="pass-1234-word")
        self.other = User.objects.create_user("noti_other", password="pass-1234-word")

    def make(self, user=None, **kwargs):
        kwargs.setdefault("kind", Kind.SYSTEM)
        kwargs.setdefault("message", "알림이에요")
        return Notification.objects.create(user=user or self.user, **kwargs)


class ServiceAndSelectorTests(NotificationFixtureMixin, TestCase):
    def test_notify_collapse_key_updates_unread(self):
        first = services.notify(self.user, Kind.NEW_MESSAGE, "안녕하세요", url="/chats/1/", collapse_key=1)
        second = services.notify(self.user, Kind.NEW_MESSAGE, "아직 판매하시나요?", url="/chats/1/", collapse_key=1)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.get().message, "아직 판매하시나요?")
        services.mark_read(second)
        third = services.notify(self.user, Kind.NEW_MESSAGE, "또 왔어요", url="/chats/1/", collapse_key=1)
        self.assertNotEqual(third.pk, first.pk)

    def test_notify_truncates_and_ignores_anonymous(self):
        note = services.notify(self.user, Kind.SYSTEM, "가" * 300)
        self.assertEqual(len(note.message), 200)
        self.assertIsNone(services.notify(None, Kind.SYSTEM, "x"))

    def test_counts_and_mark_all_read_only_mine(self):
        self.make()
        self.make(is_read=True)
        self.make(user=self.other)
        self.assertEqual(selectors.notification_counts(self.user), {"all": 2, "unread": 1})
        self.assertEqual(services.mark_all_read(self.user), 1)
        self.assertEqual(services.unread_count(self.user), 0)
        self.assertEqual(services.unread_count(self.other), 1)

    def test_recent_notifications_limit(self):
        for i in range(12):
            self.make(message=f"알림 {i}")
        recent = selectors.recent_notifications(self.user)
        self.assertEqual(len(recent), selectors.DROPDOWN_LIMIT)
        self.assertEqual(recent[0].message, "알림 11")

    def test_icon_properties(self):
        self.assertEqual(Notification(kind=Kind.REVIEW).icon_name, "star-fill")
        self.assertEqual(Notification(kind=Kind.NEW_MESSAGE).icon_class, "notif-icon-NEW_MESSAGE")
        self.assertEqual(Notification(kind=Kind.SYSTEM).icon_name, "bell")


class ListViewTests(NotificationFixtureMixin, TestCase):
    url = reverse("notifications:list")

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_shows_only_my_notifications_with_tabs(self):
        self.make(message="내 안 읽은 알림")
        self.make(message="내 읽은 알림", is_read=True)
        self.make(user=self.other, message="남의 알림")
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notifications/notification_list.html")
        self.assertContains(response, "내 안 읽은 알림")
        self.assertContains(response, "내 읽은 알림")
        self.assertNotContains(response, "남의 알림")
        self.assertEqual(response.context["counts"], {"all": 2, "unread": 1})
        self.assertContains(response, reverse("notifications:read_all"))

        response = self.client.get(self.url + "?filter=unread")
        self.assertEqual(response.context["current_filter"], "unread")
        self.assertContains(response, "내 안 읽은 알림")
        self.assertNotContains(response, "내 읽은 알림")

    def test_empty_states(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.url), "아직 받은 알림이 없어요")
        self.make(is_read=True)
        self.assertContains(self.client.get(self.url + "?filter=unread"), "안 읽은 알림이 없어요")

    def test_pagination(self):
        for i in range(25):
            self.make(message=f"알림 {i}")
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(len(response.context["page_obj"].object_list), 20)
        response = self.client.get(self.url + "?page=2")
        self.assertEqual(len(response.context["page_obj"].object_list), 5)
        response = self.client.get(self.url + "?page=999")  # 범위 밖이면 마지막 페이지
        self.assertEqual(response.context["page_obj"].number, 2)

    def test_query_count_does_not_grow(self):
        self.client.force_login(self.user)
        self.make()
        self.client.get(self.url)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.url)
        base = len(ctx.captured_queries)
        for _ in range(10):
            self.make(kind=Kind.REVIEW)
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.url)
        self.assertEqual(len(ctx.captured_queries), base)


class DropdownAndBadgeTests(NotificationFixtureMixin, TestCase):
    def test_dropdown_renders_recent_ten_with_oob_badge(self):
        for i in range(12):
            self.make(message=f"알림 {i}")
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:dropdown"), **HTMX)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notifications/partials/dropdown.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertEqual(len(response.context["notifications"]), 10)
        self.assertContains(response, "알림 11")
        self.assertNotContains(response, "알림 1<")
        self.assertContains(response, 'hx-swap-oob="innerHTML"')
        self.assertContains(response, '<span class="nav-badge">12</span>', html=True)
        self.assertContains(response, reverse("notifications:read_all"))
        self.assertIn("no-cache", response["Cache-Control"])

    def test_dropdown_empty(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:dropdown"), **HTMX)
        self.assertContains(response, "아직 알림이 없어요")
        self.assertNotContains(response, "nav-badge")

    def test_dropdown_without_htmx_redirects_to_list(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:dropdown"))
        self.assertRedirects(response, reverse("notifications:list"))

    def test_dropdown_anonymous_htmx_gets_hx_redirect(self):
        response = self.client.get(reverse("notifications:dropdown"), **HTMX)
        self.assertIn(reverse("accounts:login"), response["HX-Redirect"])

    def test_badge(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:badge"), **HTMX)
        self.assertEqual(response.content.strip(), b"")
        for _ in range(3):
            self.make()
        response = self.client.get(reverse("notifications:badge"), **HTMX)
        self.assertEqual(response.content.decode().strip(), '<span class="nav-badge">3</span>')

    def test_badge_caps_at_99(self):
        Notification.objects.bulk_create([Notification(user=self.user, message="x") for _ in range(120)])
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:badge"), **HTMX)
        self.assertContains(response, "99+")

    def test_badge_anonymous_is_empty_not_redirect(self):
        response = self.client.get(reverse("notifications:badge"), **HTMX)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
        self.assertNotIn("HX-Redirect", response)

    def test_nav_uses_badge_polling(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:list"))
        self.assertContains(response, 'hx-trigger="every 30s"')


class ReadAllTests(NotificationFixtureMixin, TestCase):
    url = reverse("notifications:read_all")

    def test_get_not_allowed(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_login_required(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)

    def test_post_marks_only_mine_and_redirects(self):
        self.make()
        self.make()
        mine_other = self.make(user=self.other)
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"next": reverse("notifications:list") + "?filter=unread"})
        self.assertRedirects(response, reverse("notifications:list") + "?filter=unread")
        self.assertEqual(services.unread_count(self.user), 0)
        mine_other.refresh_from_db()
        self.assertFalse(mine_other.is_read)

    def test_unsafe_next_is_ignored(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"next": "https://evil.example.com/"})
        self.assertRedirects(response, reverse("notifications:list"))

    def test_htmx_returns_panel_and_toast(self):
        self.make()
        self.client.force_login(self.user)
        response = self.client.post(self.url, **HTMX)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "notifications/partials/dropdown.html")
        self.assertNotContains(response, "nav-badge")
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["showToast"]["message"], "알림을 모두 읽었어요.")

    def test_csrf_enforced(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.make()
        self.assertEqual(client.post(self.url).status_code, 403)
        self.assertEqual(services.unread_count(self.user), 1)


class GoTests(NotificationFixtureMixin, TestCase):
    def test_marks_read_and_redirects(self):
        note = self.make(url="/products/")
        self.client.force_login(self.user)
        response = self.client.get(reverse("notifications:go", args=[note.pk]))
        self.assertRedirects(response, "/products/", fetch_redirect_response=False)
        note.refresh_from_db()
        self.assertTrue(note.is_read)

    def test_other_users_notification_404(self):
        note = self.make(user=self.other, url="/products/")
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("notifications:go", args=[note.pk])).status_code, 404)
        note.refresh_from_db()
        self.assertFalse(note.is_read)

    def test_empty_or_external_url_falls_back_to_list(self):
        self.client.force_login(self.user)
        for url in ("", "https://evil.example.com/", "//evil.example.com/x"):
            with self.subTest(url=url):
                note = self.make(url=url)
                response = self.client.get(reverse("notifications:go", args=[note.pk]))
                self.assertRedirects(response, reverse("notifications:list"))

    def test_login_required(self):
        note = self.make(url="/products/")
        response = self.client.get(reverse("notifications:go", args=[note.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])
