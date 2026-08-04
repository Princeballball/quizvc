from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_legacy_attempts(apps, schema_editor):
    QuizAttempt = apps.get_model("vocabulary", "QuizAttempt")
    User = apps.get_model("auth", "User")
    if not QuizAttempt.objects.filter(user__isnull=True).exists():
        return
    user, _ = User.objects.get_or_create(
        username="legacy_anonymous",
        defaults={
            "email": "legacy-anonymous@example.invalid",
            "is_active": False,
        },
    )
    QuizAttempt.objects.filter(user__isnull=True).update(user=user)


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("vocabulary", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(assign_legacy_attempts, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="quizattempt",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="quiz_attempts",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
