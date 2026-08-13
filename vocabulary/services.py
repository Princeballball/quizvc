import json
import random
import re
from pathlib import Path

from django.conf import settings
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


def import_missing_default_vocabulary():
    """Import bundled JSON units that do not exist in the database yet."""
    data_dir = Path(settings.BASE_DIR) / "data"
    json_paths = sorted(data_dir.glob("unit*_vocabulary_questions.json"))
    imported = False
    for path in json_paths:
        match = re.fullmatch(r"unit(\d+)_vocabulary_questions\.json", path.name)
        if not match:
            continue
        unit = int(match.group(1))
        slug = f"level-4-unit-{unit:02d}"
        if VocabularySet.objects.filter(slug=slug).exists():
            continue
        import_vocabulary_json(
            path,
            title=f"Level 4 Unit {unit:02d}",
            slug=slug,
            level=4,
            unit=unit,
        )
        imported = True
    return imported


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
    return create_attempt(
        vocabulary_set,
        question_count,
        user=user,
        only_question_ids=only_question_ids,
    )


def create_attempt(
    vocabulary_set,
    question_count,
    user=None,
    only_question_ids=None,
    quiz_type=QuizAttempt.SENTENCE,
    direction="",
):
    if not getattr(user, "is_authenticated", False):
        raise ValidationError("開始測驗前請先登入。")

    if quiz_type not in dict(QuizAttempt.QUIZ_TYPES):
        raise ValidationError("測驗類型不正確。")
    if quiz_type == QuizAttempt.TRANSLATION and direction not in dict(QuizAttempt.DIRECTIONS):
        raise ValidationError("翻譯方向不正確。")

    questions = Question.objects.filter(
        vocabulary_set=vocabulary_set,
        is_active=True,
    ).select_related("word_sense", "word_sense__word")

    if only_question_ids is not None:
        questions = questions.filter(id__in=only_question_ids)

    question_rows = list(questions.values_list("id", "word_sense_id"))
    if quiz_type == QuizAttempt.TRANSLATION:
        unique_questions = {}
        for question_id, word_sense_id in question_rows:
            unique_questions.setdefault(word_sense_id, question_id)
        question_ids = list(unique_questions.values())
    else:
        question_ids = [question_id for question_id, _ in question_rows]
    if not question_ids:
        raise ValidationError("目前沒有可用題目。")
    if question_count == "all":
        requested_count = len(question_ids)
    else:
        requested_count = int(question_count)
    if requested_count > len(question_ids):
        raise ValidationError(f"題數超過可用題目數，目前最多可出 {len(question_ids)} 題。")

    selected_ids = random.sample(question_ids, requested_count)
    if quiz_type == QuizAttempt.TRANSLATION:
        return _create_translation_attempt(
            vocabulary_set,
            selected_ids,
            user,
            direction,
        )

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
            quiz_type=QuizAttempt.SENTENCE,
            direction="",
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


def _translation_directions(direction, count):
    if direction != QuizAttempt.MIXED:
        return [direction] * count
    first_count = count // 2
    if count % 2 and random.choice((True, False)):
        first_count += 1
    directions = [QuizAttempt.ZH_TO_EN] * first_count
    directions.extend([QuizAttempt.EN_TO_ZH] * (count - first_count))
    random.shuffle(directions)
    return directions


def _unique_translation_pool(vocabulary_set, direction):
    senses = [
        item.word_sense
        for item in vocabulary_set.items.select_related("word_sense__word").order_by("order")
    ]
    text_for = (
        (lambda sense: sense.word.text)
        if direction == QuizAttempt.ZH_TO_EN
        else (lambda sense: sense.meaning_zh)
    )
    unique = {}
    for sense in senses:
        text = text_for(sense).strip()
        if text:
            unique.setdefault(text, sense)
    return unique, text_for


def _translation_options(vocabulary_set, word_sense, direction):
    pool, text_for = _unique_translation_pool(vocabulary_set, direction)
    correct_text = text_for(word_sense).strip()
    distractors = [text for text in pool if text != correct_text]
    if len(distractors) < 3:
        raise ValidationError("此單元沒有足夠的不同選項，單字翻譯題至少需要四個不同答案。")
    choices = [correct_text, *random.sample(distractors, 3)]
    random.shuffle(choices)
    return choices, choices.index(correct_text)


def _create_translation_attempt(vocabulary_set, selected_ids, user, direction):
    questions = {
        question.id: question
        for question in Question.objects.filter(id__in=selected_ids).select_related(
            "word_sense__word"
        )
    }
    directions = _translation_directions(direction, len(selected_ids))
    generated = []
    for question_id, question_direction in zip(selected_ids, directions):
        question = questions[question_id]
        options, correct_index = _translation_options(
            vocabulary_set, question.word_sense, question_direction
        )
        prompt = (
            question.word_sense.meaning_zh
            if question_direction == QuizAttempt.ZH_TO_EN
            else question.word_sense.word.text
        )
        generated.append((question, question_direction, prompt, options, correct_index))

    with transaction.atomic():
        attempt = QuizAttempt.objects.create(
            user=user,
            vocabulary_set=vocabulary_set,
            quiz_type=QuizAttempt.TRANSLATION,
            direction=direction,
            question_count=len(selected_ids),
            total_points=len(selected_ids) * 5,
        )
        QuizAttemptQuestion.objects.bulk_create(
            [
                QuizAttemptQuestion(
                    attempt=attempt,
                    question=question,
                    display_order=order,
                    question_direction=question_direction,
                    prompt_text=prompt,
                    option_texts=options,
                    correct_option_index=correct_index,
                )
                for order, (question, question_direction, prompt, options, correct_index)
                in enumerate(generated, start=1)
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
        if attempt.quiz_type == QuizAttempt.TRANSLATION:
            options = [
                {"display_label": label, "value": str(index), "text": text}
                for index, (label, text) in enumerate(
                    zip(DISPLAY_LABELS, attempt_question.option_texts)
                )
            ]
            rows.append(
                {
                    "attempt_question": attempt_question,
                    "question": attempt_question.question,
                    "question_text": attempt_question.prompt_text,
                    "instruction": "請選出正確的英文單字。"
                    if attempt_question.question_direction == QuizAttempt.ZH_TO_EN
                    else "請選出正確的中文意思。",
                    "direction_label": attempt_question.get_question_direction_display(),
                    "options": options,
                }
            )
            continue
        rows.append(
            {
                "attempt_question": attempt_question,
                "question": attempt_question.question,
                "question_text": attempt_question.question.prompt,
                "instruction": "",
                "direction_label": "",
                "options": [
                    {
                        **option,
                        "value": str(option["choice"].id),
                        "text": option["choice"].text,
                    }
                    for option in choice_options_for_attempt_question(attempt_question)
                ],
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
            selected = submitted_answers.get(str(attempt_question.id))
            selected_choice = None
            is_correct = False
            selected_option_index = None
            selected_text = ""
            if attempt.quiz_type == QuizAttempt.TRANSLATION and selected is not None:
                selected_option_index = selected
                selected_text = attempt_question.option_texts[selected]
                is_correct = selected == attempt_question.correct_option_index
            elif selected is not None:
                selected_choice = selected
                if selected_choice.question_id != attempt_question.question_id:
                    raise ValidationError("送出的選項與題目不符。")
                is_correct = selected_choice.is_correct
            if is_correct:
                correct_count += 1

            QuizAnswer.objects.update_or_create(
                attempt_question=attempt_question,
                defaults={
                    "selected_choice": selected_choice,
                    "selected_option_index": selected_option_index,
                    "selected_text": selected_text,
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
        if attempt.quiz_type == QuizAttempt.TRANSLATION:
            try:
                option_index = int(raw_choice_id)
            except (TypeError, ValueError):
                raise ValidationError("送出的選項不存在。")
            if option_index not in range(len(attempt_question.option_texts)):
                raise ValidationError("送出的選項不存在。")
            submitted_answers[str(attempt_question.id)] = option_index
            continue
        try:
            choice = QuestionChoice.objects.get(pk=raw_choice_id)
        except (QuestionChoice.DoesNotExist, ValueError):
            raise ValidationError("送出的選項不存在。")
        if choice.question_id != attempt_question.question_id:
            raise ValidationError("送出的選項與題目不符。")
        submitted_answers[str(attempt_question.id)] = choice
    return submitted_answers
