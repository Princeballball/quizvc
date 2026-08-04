from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from unittest.mock import patch

from vocabulary.models import Question, QuestionChoice, QuizAnswer
from vocabulary.services import (
    attempt_question_rows,
    choice_display_map,
    create_quiz_attempt,
    grade_quiz_attempt,
    selected_choices_from_post,
)
from vocabulary.tests.helpers import import_fixture


class QuizTests(TestCase):
    def setUp(self):
        import_fixture()
        self.vocabulary_set = Question.objects.first().vocabulary_set
        self.user = get_user_model().objects.create_user(
            username="student", email="student@example.com", password="pass12345"
        )

    def test_starting_ten_question_quiz_creates_attempt_questions(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 10, user=self.user)

        self.assertEqual(attempt.attempt_questions.count(), 10)
        question_ids = list(attempt.attempt_questions.values_list("question_id", flat=True))
        self.assertEqual(len(question_ids), len(set(question_ids)))
        self.assertTrue(
            all(aq.choice_order for aq in attempt.attempt_questions.all())
        )

    def test_choice_order_is_saved_and_display_labels_are_positional(self):
        question = Question.objects.first()
        with patch("vocabulary.services.random.sample", return_value=[question.id]):
            with patch("vocabulary.services.random.shuffle", side_effect=lambda values: values.reverse()):
                attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)

        attempt_question = attempt.attempt_questions.select_related("question").get()
        options = attempt_question_rows(attempt)[0]["options"]

        self.assertEqual([option["display_label"] for option in options], ["A", "B", "C", "D"])
        self.assertEqual(
            [option["choice"].id for option in options],
            attempt_question.choice_order,
        )
        self.assertNotEqual(
            [option["display_label"] for option in options],
            [option["choice"].label for option in options],
        )

    def test_new_attempt_can_have_new_choice_order(self):
        question = Question.objects.first()

        with patch("vocabulary.services.random.sample", return_value=[question.id]):
            with patch("vocabulary.services.random.shuffle", side_effect=lambda values: None):
                first = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
            with patch("vocabulary.services.random.shuffle", side_effect=lambda values: values.reverse()):
                second = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)

        self.assertNotEqual(
            first.attempt_questions.get().choice_order,
            second.attempt_questions.get().choice_order,
        )

    def test_inactive_questions_are_not_selected(self):
        inactive = Question.objects.first()
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        attempt = create_quiz_attempt(self.vocabulary_set, 45, user=self.user)
        selected_ids = set(attempt.attempt_questions.values_list("question_id", flat=True))

        self.assertNotIn(inactive.id, selected_ids)

    def test_grading_correct_wrong_and_unanswered(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 3, user=self.user)
        attempt_questions = list(attempt.attempt_questions.all())
        correct_choice = attempt_questions[0].question.choices.get(is_correct=True)
        wrong_choice = attempt_questions[1].question.choices.filter(is_correct=False).first()
        answers = {
            str(attempt_questions[0].id): correct_choice,
            str(attempt_questions[1].id): wrong_choice,
            str(attempt_questions[2].id): None,
        }

        grade_quiz_attempt(attempt, answers)
        attempt.refresh_from_db()

        self.assertEqual(attempt.correct_count, 1)
        self.assertEqual(attempt.score, 5)
        self.assertEqual(QuizAnswer.objects.count(), 3)

    def test_grading_still_uses_choice_id_after_choice_shuffle(self):
        question = Question.objects.first()
        with patch("vocabulary.services.random.sample", return_value=[question.id]):
            with patch("vocabulary.services.random.shuffle", side_effect=lambda values: values.reverse()):
                attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        attempt_question = attempt.attempt_questions.get()
        correct_choice = attempt_question.question.choices.get(is_correct=True)

        grade_quiz_attempt(attempt, {str(attempt_question.id): correct_choice})
        attempt.refresh_from_db()

        self.assertEqual(attempt.correct_count, 1)
        self.assertEqual(attempt.score, 5)
        self.assertIn(correct_choice.id, choice_display_map(attempt_question))

    def test_cannot_submit_other_questions_choice(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 2, user=self.user)
        attempt_questions = list(attempt.attempt_questions.all())
        wrong_question_choice = attempt_questions[1].question.choices.first()

        with self.assertRaises(ValidationError):
            grade_quiz_attempt(
                attempt,
                {str(attempt_questions[0].id): wrong_question_choice},
            )

    def test_cannot_change_submitted_attempt(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 1, user=self.user)
        attempt_question = attempt.attempt_questions.first()
        choice = attempt_question.question.choices.get(is_correct=True)
        grade_quiz_attempt(attempt, {str(attempt_question.id): choice})

        with self.assertRaises(ValidationError):
            grade_quiz_attempt(attempt, {str(attempt_question.id): choice})

    def test_post_parser_rejects_choice_from_other_question(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 2, user=self.user)
        attempt_questions = list(attempt.attempt_questions.all())
        other_choice = attempt_questions[1].question.choices.first()

        with self.assertRaises(ValidationError):
            selected_choices_from_post(
                attempt,
                {f"question_{attempt_questions[0].id}": str(other_choice.id)},
            )

    def test_retry_wrong_uses_original_wrong_questions(self):
        attempt = create_quiz_attempt(self.vocabulary_set, 3, user=self.user)
        attempt_questions = list(attempt.attempt_questions.all())
        answers = {}
        wrong_ids = []
        for attempt_question in attempt_questions:
            choice = attempt_question.question.choices.filter(is_correct=False).first()
            answers[str(attempt_question.id)] = choice
            wrong_ids.append(attempt_question.question_id)
        grade_quiz_attempt(attempt, answers)

        retry = create_quiz_attempt(
            self.vocabulary_set,
            len(wrong_ids),
            user=self.user,
            only_question_ids=wrong_ids,
        )

        self.assertEqual(
            set(retry.attempt_questions.values_list("question_id", flat=True)),
            set(wrong_ids),
        )
