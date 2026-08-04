from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from vocabulary.models import Question
from vocabulary.services import create_quiz_attempt, grade_quiz_attempt
from vocabulary.tests.helpers import import_fixture


class AuthenticationTests(TestCase):
    def setUp(self):
        import_fixture()
        self.vocabulary_set = Question.objects.first().vocabulary_set
        self.User = get_user_model()

    def test_register_success_logs_user_in(self):
        response = self.client.post(
            reverse("vocabulary:register"),
            {
                "username": "student",
                "email": "student@example.com",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["user"].is_authenticated)

    def test_duplicate_username_cannot_register(self):
        self.User.objects.create_user(
            username="student", email="one@example.com", password="StrongPass123"
        )

        response = self.client.post(
            reverse("vocabulary:register"),
            {
                "username": "student",
                "email": "two@example.com",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["user"].is_authenticated)

    def test_duplicate_email_cannot_register_case_insensitive(self):
        self.User.objects.create_user(
            username="one", email="Student@Example.com", password="StrongPass123"
        )

        response = self.client.post(
            reverse("vocabulary:register"),
            {
                "username": "two",
                "email": "student@example.com",
                "password1": "StrongPass123",
                "password2": "StrongPass123",
            },
        )

        self.assertContains(response, "這個 Email 已經被使用。")

    def test_login_with_username(self):
        self.User.objects.create_user(
            username="student", email="student@example.com", password="StrongPass123"
        )

        response = self.client.post(
            reverse("vocabulary:login"),
            {"identifier": "student", "password": "StrongPass123"},
            follow=True,
        )

        self.assertTrue(response.context["user"].is_authenticated)

    def test_login_with_email(self):
        self.User.objects.create_user(
            username="student", email="Student@Example.com", password="StrongPass123"
        )

        response = self.client.post(
            reverse("vocabulary:login"),
            {"identifier": "student@example.com", "password": "StrongPass123"},
            follow=True,
        )

        self.assertTrue(response.context["user"].is_authenticated)

    def test_wrong_password_cannot_login(self):
        self.User.objects.create_user(
            username="student", email="student@example.com", password="StrongPass123"
        )

        response = self.client.post(
            reverse("vocabulary:login"),
            {"identifier": "student", "password": "wrong-password"},
        )

        self.assertContains(response, "登入失敗")
        self.assertFalse(response.context["user"].is_authenticated)

    def test_logout_rejects_get_and_accepts_post(self):
        user = self.User.objects.create_user(
            username="student", email="student@example.com", password="StrongPass123"
        )
        self.client.force_login(user)

        self.assertEqual(self.client.get(reverse("vocabulary:logout")).status_code, 405)
        response = self.client.post(reverse("vocabulary:logout"), follow=True)

        self.assertFalse(response.context["user"].is_authenticated)

    def test_anonymous_user_cannot_start_quiz(self):
        response = self.client.post(
            reverse("vocabulary:start_quiz", args=[self.vocabulary_set.slug]),
            {"question_count": "10"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("vocabulary:login"), response["Location"])

    def test_anonymous_user_cannot_view_history(self):
        response = self.client.get(reverse("vocabulary:quiz_history"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("vocabulary:login"), response["Location"])

    def test_user_cannot_view_other_users_attempt(self):
        owner = self.User.objects.create_user(
            username="owner", email="owner@example.com", password="StrongPass123"
        )
        visitor = self.User.objects.create_user(
            username="visitor", email="visitor@example.com", password="StrongPass123"
        )
        attempt = create_quiz_attempt(self.vocabulary_set, 1, user=owner)
        attempt_question = attempt.attempt_questions.first()
        choice = attempt_question.question.choices.get(is_correct=True)
        grade_quiz_attempt(attempt, {str(attempt_question.id): choice})
        self.client.force_login(visitor)

        self.assertEqual(
            self.client.get(reverse("vocabulary:quiz", args=[attempt.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("vocabulary:result", args=[attempt.id])).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse("vocabulary:submit_quiz", args=[attempt.id])).status_code,
            404,
        )

    def test_unsafe_next_url_is_not_used(self):
        self.User.objects.create_user(
            username="student", email="student@example.com", password="StrongPass123"
        )

        response = self.client.post(
            f"{reverse('vocabulary:login')}?next=https://example.com/phish",
            {"identifier": "student", "password": "StrongPass123"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("vocabulary:home"))
