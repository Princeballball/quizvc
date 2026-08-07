from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from vocabulary.models import ActiveSession


class HeartbeatTests(TestCase):
    def test_anonymous_heartbeat_creates_active_session(self):
        response = self.client.post(reverse("vocabulary:heartbeat"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        active_session = ActiveSession.objects.get()
        self.assertIsNone(active_session.user)
        self.assertTrue(active_session.session_key)

    def test_authenticated_heartbeat_stores_user(self):
        user = get_user_model().objects.create_user(
            username="student",
            email="student@example.com",
            password="StrongPass123",
        )
        self.client.force_login(user)

        self.client.post(reverse("vocabulary:heartbeat"))

        self.assertEqual(ActiveSession.objects.get().user, user)

    def test_same_session_updates_existing_row(self):
        self.client.post(reverse("vocabulary:heartbeat"))
        active_session = ActiveSession.objects.get()
        old_seen = active_session.last_seen - timedelta(minutes=5)
        ActiveSession.objects.filter(pk=active_session.pk).update(last_seen=old_seen)

        response = self.client.post(reverse("vocabulary:heartbeat"))
        active_session.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ActiveSession.objects.count(), 1)
        self.assertGreater(active_session.last_seen, old_seen)

    @override_settings(INTERNAL_API_TOKEN=None)
    def test_active_users_fails_closed_without_token(self):
        response = self.client.get(reverse("vocabulary:active_users"))

        self.assertEqual(response.status_code, 403)

    @override_settings(INTERNAL_API_TOKEN="secret-token")
    def test_active_users_rejects_wrong_token(self):
        response = self.client.get(
            reverse("vocabulary:active_users"),
            HTTP_AUTHORIZATION="Bearer wrong-token",
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(INTERNAL_API_TOKEN="secret-token")
    def test_active_users_counts_recent_sessions_only(self):
        ActiveSession.objects.create(session_key="recent")
        old = ActiveSession.objects.create(session_key="old")
        ActiveSession.objects.filter(pk=old.pk).update(
            last_seen=timezone.now() - timedelta(seconds=46)
        )

        response = self.client.get(
            reverse("vocabulary:active_users"),
            HTTP_AUTHORIZATION="Bearer secret-token",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active_users"], 1)
        self.assertNotIn("session_key", response.content.decode())

    def test_heartbeat_uses_csrf_protection(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(reverse("vocabulary:heartbeat"))

        self.assertEqual(response.status_code, 403)

    def test_heartbeat_accepts_valid_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        home_response = csrf_client.get(reverse("vocabulary:home"))
        csrf_token = home_response.cookies["csrftoken"].value

        response = csrf_client.post(
            reverse("vocabulary:heartbeat"),
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ActiveSession.objects.count(), 1)
