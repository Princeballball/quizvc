from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vocabulary", "0002_require_attempt_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="quizattemptquestion",
            name="choice_order",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
