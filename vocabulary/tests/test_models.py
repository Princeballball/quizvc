from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from vocabulary.models import (
    Question,
    QuestionChoice,
    VocabularySet,
    Word,
    WordSense,
)


class ModelTests(TestCase):
    def test_word_normalizes_to_lowercase(self):
        word = Word.objects.create(text=" Involve ")

        self.assertEqual(word.text, "Involve")
        self.assertEqual(word.normalized_text, "involve")

    def test_same_word_does_not_duplicate_by_case(self):
        Word.objects.create(text="Involve")

        with self.assertRaises(IntegrityError):
            Word.objects.create(text="involve")

    def test_same_question_cannot_have_duplicate_label(self):
        question = self._question()
        QuestionChoice.objects.create(question=question, label="A", text="one", order=1)

        with self.assertRaises(IntegrityError):
            QuestionChoice.objects.create(question=question, label="A", text="two", order=2)

    def test_question_choice_validates_single_correct_answer(self):
        question = self._question()
        QuestionChoice.objects.create(
            question=question, label="A", text="involve", is_correct=True, order=1
        )
        second = QuestionChoice(
            question=question, label="B", text="obtain", is_correct=True, order=2
        )

        with self.assertRaises(ValidationError):
            second.full_clean()

    def _question(self):
        vocabulary_set = VocabularySet.objects.create(
            title="Level 4 Unit 01", slug="level-4-unit-01", level=4, unit=1
        )
        word = Word.objects.create(text="involve")
        sense = WordSense.objects.create(
            word=word,
            part_of_speech="verb",
            meaning_zh="使涉入",
        )
        return Question.objects.create(
            vocabulary_set=vocabulary_set,
            word_sense=sense,
            source_id="1",
            prompt="The project will _____ students.",
        )
