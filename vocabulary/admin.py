from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from .models import (
    ActiveSession,
    Question,
    QuestionChoice,
    QuizAnswer,
    QuizAttempt,
    QuizAttemptQuestion,
    VocabularySet,
    VocabularySetItem,
    Word,
    WordSense,
)


class QuestionChoiceInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        choices = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
        ]
        if choices and len(choices) != 4:
            raise ValidationError("每題必須有四個選項。")
        if choices and sum(1 for choice in choices if choice.get("is_correct")) != 1:
            raise ValidationError("每題必須剛好有一個正確答案。")


class QuestionChoiceInline(admin.TabularInline):
    model = QuestionChoice
    formset = QuestionChoiceInlineFormSet
    extra = 0
    fields = ("label", "text", "is_correct", "order")


class VocabularySetItemInline(admin.TabularInline):
    model = VocabularySetItem
    extra = 0
    autocomplete_fields = ("word_sense",)


@admin.register(VocabularySet)
class VocabularySetAdmin(admin.ModelAdmin):
    list_display = ("title", "level", "unit", "is_published", "question_total")
    list_filter = ("is_published", "level")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    inlines = (VocabularySetItemInline,)

    @admin.display(description="題目數")
    def question_total(self, obj):
        return obj.questions.count()


@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ("text", "normalized_text", "sense_total")
    search_fields = ("text", "normalized_text")
    readonly_fields = ("normalized_text",)

    @admin.display(description="詞義數")
    def sense_total(self, obj):
        return obj.senses.count()


@admin.register(WordSense)
class WordSenseAdmin(admin.ModelAdmin):
    list_display = ("word", "part_of_speech", "meaning_zh")
    list_filter = ("part_of_speech",)
    search_fields = ("word__text", "word__normalized_text", "meaning_zh")
    autocomplete_fields = ("word",)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("short_prompt", "word", "vocabulary_set", "is_active")
    list_filter = ("vocabulary_set", "word_sense__part_of_speech", "is_active")
    search_fields = ("prompt", "word_sense__word__text", "word_sense__meaning_zh")
    autocomplete_fields = ("vocabulary_set", "word_sense")
    inlines = (QuestionChoiceInline,)

    @admin.display(description="題目")
    def short_prompt(self, obj):
        return obj.prompt[:70]

    @admin.display(description="單字")
    def word(self, obj):
        return obj.word_sense.word.text


class QuizAnswerInline(admin.TabularInline):
    model = QuizAnswer
    extra = 0
    can_delete = False
    readonly_fields = ("attempt_question", "selected_choice", "is_correct", "answered_at")


class QuizAttemptQuestionInline(admin.TabularInline):
    model = QuizAttemptQuestion
    extra = 0
    can_delete = False
    readonly_fields = ("question", "display_order")


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "vocabulary_set",
        "score",
        "total_points",
        "correct_count",
        "created_at",
        "submitted_at",
    )
    list_filter = ("vocabulary_set", "submitted_at")
    readonly_fields = (
        "id",
        "user",
        "vocabulary_set",
        "question_count",
        "points_per_question",
        "total_points",
        "score",
        "correct_count",
        "submitted_at",
        "created_at",
    )
    inlines = (QuizAttemptQuestionInline,)


@admin.register(QuestionChoice)
class QuestionChoiceAdmin(admin.ModelAdmin):
    list_display = ("question", "label", "text", "is_correct", "order")
    list_filter = ("is_correct",)
    search_fields = ("text", "question__prompt")


@admin.register(ActiveSession)
class ActiveSessionAdmin(admin.ModelAdmin):
    list_display = ("session_key", "user", "last_seen")
    search_fields = ("session_key", "user__username")
    readonly_fields = ("session_key", "user", "last_seen")
