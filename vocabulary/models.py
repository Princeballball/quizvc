import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VocabularySet(TimeStampedModel):
    title = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    level = models.PositiveIntegerField()
    unit = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["level", "unit", "title"]

    def __str__(self):
        return self.title


class Word(TimeStampedModel):
    text = models.CharField(max_length=120)
    normalized_text = models.CharField(max_length=120, unique=True, editable=False)

    class Meta:
        ordering = ["normalized_text"]

    def save(self, *args, **kwargs):
        self.text = self.text.strip()
        self.normalized_text = self.text.lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.text


class WordSense(TimeStampedModel):
    PARTS_OF_SPEECH = [
        ("verb", "verb"),
        ("noun", "noun"),
        ("adjective", "adjective"),
        ("adverb", "adverb"),
        ("preposition", "preposition"),
        ("other", "other"),
    ]

    word = models.ForeignKey(Word, on_delete=models.CASCADE, related_name="senses")
    part_of_speech = models.CharField(max_length=20, choices=PARTS_OF_SPEECH)
    meaning_zh = models.CharField(max_length=255)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["word__normalized_text", "part_of_speech", "meaning_zh"]
        constraints = [
            models.UniqueConstraint(
                fields=["word", "part_of_speech", "meaning_zh"],
                name="unique_word_sense",
            )
        ]

    def __str__(self):
        return f"{self.word.text} ({self.part_of_speech})"


class VocabularySetItem(models.Model):
    vocabulary_set = models.ForeignKey(
        VocabularySet, on_delete=models.CASCADE, related_name="items"
    )
    word_sense = models.ForeignKey(
        WordSense, on_delete=models.CASCADE, related_name="set_items"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["vocabulary_set", "word_sense"],
                name="unique_vocabulary_set_item",
            )
        ]

    def __str__(self):
        return f"{self.vocabulary_set}: {self.word_sense}"


class Question(TimeStampedModel):
    SENTENCE_CHOICE = "sentence_choice"

    vocabulary_set = models.ForeignKey(
        VocabularySet, on_delete=models.CASCADE, related_name="questions"
    )
    word_sense = models.ForeignKey(
        WordSense, on_delete=models.PROTECT, related_name="questions"
    )
    source_id = models.CharField(max_length=60, blank=True)
    question_type = models.CharField(max_length=40, default=SENTENCE_CHOICE)
    prompt = models.TextField()
    explanation = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["vocabulary_set", "source_id", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["vocabulary_set", "source_id"],
                name="unique_question_source",
            )
        ]

    def __str__(self):
        return self.prompt

    def clean(self):
        super().clean()
        if self.pk:
            correct_count = self.choices.filter(is_correct=True).count()
            choice_count = self.choices.count()
            if choice_count and choice_count != 4:
                raise ValidationError("每題必須有四個選項。")
            if choice_count and correct_count != 1:
                raise ValidationError("每題必須剛好有一個正確答案。")


class QuestionChoice(models.Model):
    LABELS = [(letter, letter) for letter in ("A", "B", "C", "D")]

    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name="choices"
    )
    label = models.CharField(max_length=1, choices=LABELS)
    text = models.CharField(max_length=255)
    is_correct = models.BooleanField(default=False)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["question", "label"], name="unique_question_choice_label"
            ),
            models.UniqueConstraint(
                fields=["question", "order"], name="unique_question_choice_order"
            ),
        ]

    def __str__(self):
        return f"{self.question_id} {self.label}. {self.text}"

    def clean(self):
        super().clean()
        if self.is_correct and self.question_id:
            qs = QuestionChoice.objects.filter(question=self.question, is_correct=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError("每題只能有一個正確選項。")


class QuizAttempt(models.Model):
    SENTENCE = "sentence"
    TRANSLATION = "translation"
    QUIZ_TYPES = [(SENTENCE, "英文例句"), (TRANSLATION, "單字翻譯")]
    ZH_TO_EN = "zh_to_en"
    EN_TO_ZH = "en_to_zh"
    MIXED = "mixed"
    DIRECTIONS = [
        (ZH_TO_EN, "中文 → 英文"),
        (EN_TO_ZH, "英文 → 中文"),
        (MIXED, "雙向混合"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
    )
    vocabulary_set = models.ForeignKey(
        VocabularySet, on_delete=models.PROTECT, related_name="attempts"
    )
    quiz_type = models.CharField(max_length=20, choices=QUIZ_TYPES, default=SENTENCE)
    direction = models.CharField(max_length=20, choices=DIRECTIONS, blank=True)
    question_count = models.PositiveIntegerField()
    points_per_question = models.PositiveIntegerField(default=5)
    total_points = models.PositiveIntegerField(default=0)
    score = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_submitted(self):
        return self.submitted_at is not None

    @property
    def wrong_count(self):
        return self.question_count - self.correct_count

    @property
    def mode_label(self):
        if self.quiz_type == self.TRANSLATION:
            return f"{self.get_quiz_type_display()}・{self.get_direction_display()}"
        return self.get_quiz_type_display()

    def mark_submitted(self, correct_count):
        self.correct_count = correct_count
        self.total_points = self.question_count * self.points_per_question
        self.score = correct_count * self.points_per_question
        self.submitted_at = timezone.now()

    def __str__(self):
        return f"{self.vocabulary_set} - {self.score}/{self.total_points}"


class QuizAttemptQuestion(models.Model):
    attempt = models.ForeignKey(
        QuizAttempt, on_delete=models.CASCADE, related_name="attempt_questions"
    )
    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="attempt_questions"
    )
    display_order = models.PositiveIntegerField()
    choice_order = models.JSONField(default=list, blank=True)
    question_direction = models.CharField(
        max_length=20, choices=QuizAttempt.DIRECTIONS, blank=True
    )
    prompt_text = models.TextField(blank=True)
    option_texts = models.JSONField(default=list, blank=True)
    correct_option_index = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["attempt", "question"], name="unique_attempt_question"
            ),
            models.UniqueConstraint(
                fields=["attempt", "display_order"], name="unique_attempt_display_order"
            ),
        ]

    def __str__(self):
        return f"{self.attempt_id} Q{self.display_order}"


class QuizAnswer(models.Model):
    attempt_question = models.OneToOneField(
        QuizAttemptQuestion, on_delete=models.CASCADE, related_name="answer"
    )
    selected_choice = models.ForeignKey(
        QuestionChoice,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quiz_answers",
    )
    selected_option_index = models.PositiveSmallIntegerField(null=True, blank=True)
    selected_text = models.CharField(max_length=255, blank=True)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if (
            self.selected_choice_id
            and self.attempt_question_id
            and self.selected_choice.question_id != self.attempt_question.question_id
        ):
            raise ValidationError("選項不屬於這一題。")

    def __str__(self):
        return f"{self.attempt_question}: {self.selected_choice or '未作答'}"


class ActiveSession(models.Model):
    session_key = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="active_sessions",
    )
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen"]

    def __str__(self):
        return f"{self.user or 'anonymous'} @ {self.last_seen}"
