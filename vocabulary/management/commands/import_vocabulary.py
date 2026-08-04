from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from vocabulary.services import import_vocabulary_json


class Command(BaseCommand):
    help = "Import vocabulary questions from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument("json_path")
        parser.add_argument("--title", default="Level 4 Unit 01")
        parser.add_argument("--slug", default="level-4-unit-01")
        parser.add_argument("--level", type=int, default=4)
        parser.add_argument("--unit", type=int, default=1)

    def handle(self, *args, **options):
        try:
            stats = import_vocabulary_json(
                options["json_path"],
                title=options["title"],
                slug=options["slug"],
                level=options["level"],
                unit=options["unit"],
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS("Vocabulary import completed."))
        self.stdout.write(f"新增單字數: {stats['words_created']}")
        self.stdout.write(f"更新單字數: {stats['words_updated']}")
        self.stdout.write(f"新增題目數: {stats['questions_created']}")
        self.stdout.write(f"更新題目數: {stats['questions_updated']}")
        self.stdout.write(f"錯誤筆數: {stats['errors']}")
