from pathlib import Path

from django.conf import settings

from vocabulary.services import import_vocabulary_json


FIXTURE_PATH = Path(settings.BASE_DIR) / "data" / "unit01_vocabulary_questions.json"


def import_fixture():
    return import_vocabulary_json(
        FIXTURE_PATH,
        title="Level 4 Unit 01",
        slug="level-4-unit-01",
        level=4,
        unit=1,
    )
