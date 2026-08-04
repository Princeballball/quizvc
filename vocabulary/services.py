import json
import random

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
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


REQUIRED_IMPORT_FIELDS = {
    "id",
    "word",
    "part_of_speech",
    "meaning_zh",
    "question",
    "options",
    "answer_letter",
    "answer",
}

DISPLAY_LABELS = ("A", "B", "C", "D")


def normalize_word(text):
    return text.strip().lower()


def import_vocabulary_json(path, title, slug, level, unit):
    with open(path, encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, list):
        raise ValidationError("JSON 最外層必須是 list。")

    stats = {
        "words_created": 0,
        "words_updated": 0,
        "questions_created": 0,
        "questions_updated": 0,
        "errors": 0,
    }

    with transaction.atomic():
        vocabulary_set, _ = VocabularySet.objects.update_or_create(
            slug=slug,
            defaults={
                "title": title,
                "level": level,
                "unit": unit,
                "is_published": True,
            },
        )

        for index, item in enumerate(payload, start=1):
            _validate_import_item(item, index)

            word_text = item["word"].strip()
            normalized = normalize_word(word_text)
            word, created = Word.objects.get_or_create(
                normalized_text=normalized,
                defaults={"text": word_text},
            )
            if created:
                stats["words_created"] += 1
            elif word.text != word_text:
                word.text = word_text
                word.save(update_fields=["text", "normalized_text", "updated_at"])
                stats["words_updated"] += 1

            word_sense, _ = WordSense.objects.get_or_create(
                word=word,
                part_of_speech=item["part_of_speech"],
                meaning_zh=item["meaning_zh"],
            )
            VocabularySetItem.objects.update_or_create(
                vocabulary_set=vocabulary_set,
                word_sense=word_sense,
                defaults={"order": index},
            )

            question, question_created = Question.objects.update_or_create(
                vocabulary_set=vocabulary_set,
                source_id=str(item["id"]),
                defaults={
                    "word_sense": word_sense,
                    "question_type": Question.SENTENCE_CHOICE,
                    "prompt": item["question"],
                    "is_active": True,
                },
            )
            if question_created:
                stats["questions_created"] += 1
            else:
                stats["questions_updated"] += 1

            question.choices.all().delete()
            for order, label in enumerate(("A", "B", "C", "D"), start=1):
                QuestionChoice.objects.create(
                    question=question,
                    label=label,
                    text=item["options"][label],
                    is_correct=label == item["answer_letter"],
                    order=order,
                )

            _validate_question_choices(question, item["answer"])

    return stats


def _validate_import_item(item, index):
    missing = REQUIRED_IMPORT_FIELDS.difference(item)
    if missing:
        raise ValidationError(f"第 {index} 筆缺少欄位：{', '.join(sorted(missing))}")
    if not isinstance(item["options"], dict):
        raise ValidationError(f"第 {index} 筆 options 必須是 object。")
    if set(item["options"]) != {"A", "B", "C", "D"}:
        raise ValidationError(f"第 {index} 筆 options 必須包含 A, B, C, D。")
    if item["answer_letter"] not in item["options"]:
        raise ValidationError(f"第 {index} 筆 answer_letter 不在 options 中。")
    if item["options"][item["answer_letter"]] != item["answer"]:
        raise ValidationError(f"第 {index} 筆 answer 與正確選項文字不一致。")


def _validate_question_choices(question, answer):
    choices = list(question.choices.all())
    if len(choices) != 4:
        raise ValidationError("每題必須有四個選項。")
    correct = [choice for choice in choices if choice.is_correct]
    if len(correct) != 1:
        raise ValidationError("每題必須剛好有一個正確答案。")
    if correct[0].text != answer:
        raise ValidationError("正確答案文字與題目答案不一致。")


def parse_question_count(raw_value, available_count):
    if raw_value == "all":
        return available_count
    try:
        count = int(raw_value)
    except (TypeError, ValueError):
        raise ValidationError("題數選擇不正確。")
    if count not in (10, 20) and count != available_count:
        raise ValidationError("題數選擇不正確。")
    return min(count, available_count)


def create_quiz_attempt(vocabulary_set, question_count, user=None, only_question_ids=None):
    if not getattr(user, "is_authenticated", False):
        raise ValidationError("開始測驗前請先登入。")

    questions = Question.objects.filter(
        vocabulary_set=vocabulary_set,
        is_active=True,
    ).select_related("word_sense", "word_sense__word")

    if only_question_ids is not None:
        questions = questions.filter(id__in=only_question_ids)

    question_ids = list(questions.values_list("id", flat=True))
    if not question_ids:
        raise ValidationError("目前沒有可用題目。")
    if question_count == "all":
        requested_count = len(question_ids)
    else:
        requested_count = int(question_count)
    if requested_count > len(question_ids):
        raise ValidationError("題數超過可用題目數。")

    selected_ids = random.sample(question_ids, requested_count)
    choice_ids_by_question = {
        question_id: list(
            QuestionChoice.objects.filter(question_id=question_id).values_list("id", flat=True)
        )
        for question_id in selected_ids
    }
    for choice_ids in choice_ids_by_question.values():
        random.shuffle(choice_ids)

    with transaction.atomic():
        attempt = QuizAttempt.objects.create(
            user=user,
            vocabulary_set=vocabulary_set,
            question_count=requested_count,
            total_points=requested_count * 5,
        )
        QuizAttemptQuestion.objects.bulk_create(
            [
                QuizAttemptQuestion(
                    attempt=attempt,
                    question_id=question_id,
                    display_order=order,
                    choice_order=choice_ids_by_question[question_id],
                )
                for order, question_id in enumerate(selected_ids, start=1)
            ]
        )
    return attempt


def choice_options_for_attempt_question(attempt_question):
    choices = list(attempt_question.question.choices.all())
    choices_by_id = {choice.id: choice for choice in choices}
    ordered_choices = [
        choices_by_id[choice_id]
        for choice_id in attempt_question.choice_order
        if choice_id in choices_by_id
    ]
    if len(ordered_choices) != len(choices):
        ordered_ids = {choice.id for choice in ordered_choices}
        ordered_choices.extend(choice for choice in choices if choice.id not in ordered_ids)

    return [
        {"display_label": label, "choice": choice}
        for label, choice in zip(DISPLAY_LABELS, ordered_choices)
    ]


def choice_display_map(attempt_question):
    return {
        option["choice"].id: option["display_label"]
        for option in choice_options_for_attempt_question(attempt_question)
    }


def attempt_question_rows(attempt):
    rows = []
    attempt_questions = attempt.attempt_questions.select_related(
        "question",
        "question__word_sense",
        "question__word_sense__word",
    ).prefetch_related("question__choices")
    for attempt_question in attempt_questions:
        rows.append(
            {
                "attempt_question": attempt_question,
                "question": attempt_question.question,
                "options": choice_options_for_attempt_question(attempt_question),
            }
        )
    return rows


def grade_quiz_attempt(attempt, submitted_answers):
    with transaction.atomic():
        attempt = QuizAttempt.objects.select_for_update().get(pk=attempt.pk)
        if attempt.is_submitted:
            raise ValidationError("這份測驗已經送出，不能再次修改。")

        attempt_questions = list(
            attempt.attempt_questions.select_related("question").order_by("display_order")
        )
        correct_count = 0

        for attempt_question in attempt_questions:
            selected_choice = submitted_answers.get(str(attempt_question.id))
            is_correct = False
            if selected_choice is not None:
                if selected_choice.question_id != attempt_question.question_id:
                    raise ValidationError("送出的選項與題目不符。")
                is_correct = selected_choice.is_correct
                if is_correct:
                    correct_count += 1

            QuizAnswer.objects.update_or_create(
                attempt_question=attempt_question,
                defaults={
                    "selected_choice": selected_choice,
                    "is_correct": is_correct,
                },
            )

        attempt.mark_submitted(correct_count)
        attempt.save(
            update_fields=["correct_count", "total_points", "score", "submitted_at"]
        )
    return attempt


def selected_choices_from_post(attempt, post_data):
    submitted_answers = {}
    attempt_questions = attempt.attempt_questions.select_related("question")
    for attempt_question in attempt_questions:
        raw_choice_id = post_data.get(f"question_{attempt_question.id}")
        if not raw_choice_id:
            submitted_answers[str(attempt_question.id)] = None
            continue
        try:
            choice = QuestionChoice.objects.get(pk=raw_choice_id)
        except (QuestionChoice.DoesNotExist, ValueError):
            raise ValidationError("送出的選項不存在。")
        if choice.question_id != attempt_question.question_id:
            raise ValidationError("送出的選項與題目不符。")
        submitted_answers[str(attempt_question.id)] = choice
    return submitted_answers
