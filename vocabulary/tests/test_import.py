import json
import tempfile

from django.core.exceptions import ValidationError
from django.test import TestCase

from vocabulary.models import Question, VocabularySet, Word
from vocabulary.services import import_vocabulary_json
from vocabulary.tests.helpers import FIXTURE_PATH, import_fixture


class ImportTests(TestCase):
    def test_successfully_imports_fixture(self):
        import_fixture()

        self.assertEqual(Question.objects.count(), 46)
        self.assertEqual(VocabularySet.objects.get().title, "Level 4 Unit 01")
        self.assertTrue(all(question.choices.count() == 4 for question in Question.objects.all()))
        self.assertTrue(
            all(
                question.choices.filter(is_correct=True).count() == 1
                for question in Question.objects.all()
            )
        )

    def test_import_is_idempotent(self):
        import_fixture()
        import_fixture()

        self.assertEqual(Question.objects.count(), 46)
        self.assertEqual(Word.objects.count(), 44)

    def test_bad_format_rolls_back(self):
        first_item = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))[0]
        bad_payload = [first_item, {"id": 999}]

        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as file:
            json.dump(bad_payload, file)
            file.flush()
            with self.assertRaises(ValidationError):
                import_vocabulary_json(
                    file.name,
                    title="Level 4 Unit 01",
                    slug="level-4-unit-01",
                    level=4,
                    unit=1,
                )

        self.assertEqual(Question.objects.count(), 0)
        self.assertEqual(Word.objects.count(), 0)
