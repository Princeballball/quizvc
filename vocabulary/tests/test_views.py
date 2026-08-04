import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from vocabulary.models import Question
from vocabulary.services import create_quiz_attempt, grade_quiz_attempt, choice_display_map
from vocabulary.tests.helpers import import_fixture


class ViewTests(TestCase):
    def setUp(self):
        import_fixture()
        self.vocabulary_set = Question.objects.first().vocabulary_set
        self.user = get_user_model().objects.create_user(
            username="student", email="student@example.com", password="pass12345"
        )

    def test_home_returns_200(self):
        response = self.client.get(reverse("vocabulary:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Level 4 Unit 01")

    def test_register_and_login_pages_return_200(self):
        self.assertEqual(self.client.get(reverse("vocabulary:register")).status_code, 200)
        self.assertEqual(self.client.get(reverse("vocabulary:login")).status_code, 200)

    def test_authenticated_user_login_page_redirects_home(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("vocabulary:login"))

        self.assertRedirects(response, reverse("vocabulary:home"))

    def test_history_only_shows_current_users_attempts(self):
        other = get_user_model().objects.create_user(
            username="other", email="other@example.com", password="pass12345"
        )
        own_attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        other_attempt = create_quiz_attempt(self.vocabulary_set, 1, user=other)
        for attempt in (own_attempt, other_attempt):
            attempt_question = attempt.attempt_questions.first()
            choice = attempt_question.question.choices.get(is_correct=True)
            grade_quiz_attempt(attempt, {str(attempt_question.id): choice})
        self.client.force_login(self.user)

        response = self.client.get(reverse("vocabulary:quiz_history"))

        self.assertContains(response, str(own_attempt.score))
        self.assertContains(response, reverse("vocabulary:result", args=[own_attempt.id]))
        self.assertNotContains(response, reverse("vocabulary:result", args=[other_attempt.id]))

    def test_unpublished_set_does_not_show_on_home(self):
        self.vocabulary_set.is_published = False
        self.vocabulary_set.save(update_fields=["is_published"])

        response = self.client.get(reverse("vocabulary:home"))

        self.assertNotContains(response, "Level 4 Unit 01")

    def test_start_endpoint_rejects_get(self):
        response = self.client.get(
            reverse("vocabulary:start_quiz", args=[self.vocabulary_set.slug])
        )

        self.assertEqual(response.status_code, 405)

    def test_quiz_page_does_not_expose_correct_flag(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 10, user=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("vocabulary:quiz", args=[attempt.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "is_correct")
        self.assertNotContains(response, "answer_letter")

    def test_quiz_page_display_labels_are_always_a_to_d(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("vocabulary:quiz", args=[attempt.id]))
        labels = re.findall(
            r'<span class="choice-label">\(([A-D])\)</span>',
            response.content.decode(),
        )

        self.assertEqual(labels, ["A", "B", "C", "D"])

    def test_quiz_choice_text_order_is_stable_on_refresh(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        self.client.force_login(self.user)
        url = reverse("vocabulary:quiz", args=[attempt.id])

        first = self.client.get(url).content.decode()
        second = self.client.get(url).content.decode()

        self.assertEqual(
            re.findall(r'value="(\d+)"', first),
            re.findall(r'value="(\d+)"', second),
        )

    def test_result_shows_answer_and_meaning(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        self.client.force_login(self.user)
        attempt_question = attempt.attempt_questions.first()
        choice = attempt_question.question.choices.get(is_correct=True)
        grade_quiz_attempt(attempt, {str(attempt_question.id): choice})

        response = self.client.get(reverse("vocabulary:result", args=[attempt.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, choice.text)
        self.assertContains(response, attempt_question.question.word_sense.meaning_zh)

    def test_result_page_uses_attempt_display_label(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        self.client.force_login(self.user)
        attempt_question = attempt.attempt_questions.first()
        choice = attempt_question.question.choices.get(is_correct=True)
        expected_label = choice_display_map(attempt_question)[choice.id]
        grade_quiz_attempt(attempt, {str(attempt_question.id): choice})

        response = self.client.get(reverse("vocabulary:result", args=[attempt.id]))

        self.assertContains(response, f"（{expected_label}）{choice.text}")

    def test_unsubmitted_result_redirects_to_quiz(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("vocabulary:result", args=[attempt.id]))

        self.assertRedirects(response, reverse("vocabulary:quiz", args=[attempt.id]))
