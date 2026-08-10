import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import LoginForm, RegisterForm
from .models import ActiveSession, QuestionChoice, QuizAttempt, VocabularySet
from .services import (
    attempt_question_rows,
    choice_display_map,
    create_quiz_attempt,
    grade_quiz_attempt,
    import_missing_default_vocabulary,
    parse_question_count,
    selected_choices_from_post,
)

def safe_next_url(request, fallback=None):
    fallback = fallback or reverse(settings.LOGIN_REDIRECT_URL)
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


def heartbeat(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    if not request.session.session_key:
        request.session.create()

    user = request.user if request.user.is_authenticated else None
    ActiveSession.objects.update_or_create(
        session_key=request.session.session_key,
        defaults={"user": user},
    )
    _cleanup_expired_active_sessions()
    return JsonResponse({"ok": True})


def active_users(request):
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    if not _has_internal_api_token(request):
        return JsonResponse({"detail": "Forbidden"}, status=403)

    cutoff = timezone.now() - timedelta(seconds=settings.ACTIVE_SESSION_SECONDS)
    sessions = (
        ActiveSession.objects.filter(last_seen__gte=cutoff)
        .select_related("user")
        .order_by("-last_seen")
    )
    return JsonResponse(
        {
            "active_users": sessions.count(),
            "sessions": [
                {
                    "username": session.user.username if session.user else None,
                    "last_seen": session.last_seen.isoformat(),
                }
                for session in sessions
            ],
        }
    )


def _has_internal_api_token(request):
    expected_token = settings.INTERNAL_API_TOKEN
    if not expected_token:
        return False
    authorization = request.headers.get("Authorization", "")
    scheme, _, supplied_token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not supplied_token:
        return False
    return secrets.compare_digest(
        supplied_token.encode("utf-8"),
        expected_token.encode("utf-8"),
    )


def _cleanup_expired_active_sessions():
    cutoff = timezone.now() - timedelta(hours=settings.ACTIVE_SESSION_RETENTION_HOURS)
    ActiveSession.objects.filter(last_seen__lt=cutoff).delete()


def home(request):
    import_missing_default_vocabulary()
    sets = (
        VocabularySet.objects.filter(is_published=True)
        .annotate(active_question_count=Count("questions", filter=Q(questions__is_active=True)))
        .order_by("level", "unit")
    )
    return render(request, "vocabulary/home.html", {"sets": sets})


def register(request):
    if request.user.is_authenticated:
        return redirect("vocabulary:home")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(safe_next_url(request))
    else:
        form = RegisterForm()

    return render(
        request,
        "vocabulary/register.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def login_view(request):
    if request.user.is_authenticated:
        return redirect("vocabulary:home")

    if request.method == "POST":
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            if not form.cleaned_data.get("remember_me"):
                request.session.set_expiry(0)
            return redirect(safe_next_url(request))
    else:
        form = LoginForm(request)

    return render(
        request,
        "vocabulary/login.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


def logout_view(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    logout(request)
    return redirect("vocabulary:home")


@login_required
def quiz_history(request):
    attempts = (
        QuizAttempt.objects.filter(user=request.user, submitted_at__isnull=False)
        .select_related("vocabulary_set")
        .order_by("-submitted_at")
    )
    paginator = Paginator(attempts, 10)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "vocabulary/quiz_history.html",
        {
            "page_obj": page_obj,
            "attempt_count": attempts.count(),
        },
    )


def word_list(request, slug):
    vocabulary_set = get_object_or_404(VocabularySet, slug=slug, is_published=True)
    query = request.GET.get("q", "").strip()
    items = vocabulary_set.items.select_related("word_sense", "word_sense__word").order_by(
        "order"
    )
    if query:
        items = items.filter(
            Q(word_sense__word__text__icontains=query)
            | Q(word_sense__meaning_zh__icontains=query)
            | Q(word_sense__part_of_speech__icontains=query)
        )
    question_prompts = {
        question.word_sense_id: question.prompt
        for question in vocabulary_set.questions.filter(is_active=True)
    }
    rows = [
        {"item": item, "prompt": question_prompts.get(item.word_sense_id, "")}
        for item in items
    ]
    return render(
        request,
        "vocabulary/word_list.html",
        {"vocabulary_set": vocabulary_set, "rows": rows, "query": query},
    )


def start_quiz(request, slug):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    if not request.user.is_authenticated:
        return redirect(f"{reverse('vocabulary:login')}?next={reverse('vocabulary:home')}")
    vocabulary_set = get_object_or_404(VocabularySet, slug=slug, is_published=True)
    available_count = vocabulary_set.questions.filter(is_active=True).count()
    try:
        question_count = parse_question_count(request.POST.get("question_count"), available_count)
        attempt = create_quiz_attempt(vocabulary_set, question_count, user=request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if hasattr(exc, "messages") else str(exc))
        return redirect("vocabulary:home")
    return redirect("vocabulary:quiz", attempt_id=attempt.id)


@login_required
def quiz(request, attempt_id):
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, user=request.user)
    if attempt.is_submitted:
        return redirect("vocabulary:result", attempt_id=attempt.id)
    rows = attempt_question_rows(attempt)
    for row in rows:
        row["selected_choice_id"] = ""
    return render(
        request,
        "vocabulary/quiz.html",
        {"attempt": attempt, "rows": rows, "errors": []},
    )


@login_required
def submit_quiz(request, attempt_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, user=request.user)
    if attempt.is_submitted:
        return redirect("vocabulary:result", attempt_id=attempt.id)

    try:
        submitted_answers = selected_choices_from_post(attempt, request.POST)
        grade_quiz_attempt(attempt, submitted_answers)
    except ValidationError as exc:
        selected = {}
        for key, value in request.POST.items():
            if key.startswith("question_"):
                selected[key.replace("question_", "")] = value
        rows = attempt_question_rows(attempt)
        for row in rows:
            aq_id = str(row["attempt_question"].id)
            row["selected_choice_id"] = selected.get(aq_id, "")
        errors = exc.messages if hasattr(exc, "messages") else [str(exc)]
        return render(
            request,
            "vocabulary/quiz.html",
            {"attempt": attempt, "rows": rows, "errors": errors},
            status=400,
        )
    return redirect("vocabulary:result", attempt_id=attempt.id)


@login_required
def result(request, attempt_id):
    attempt = get_object_or_404(
        QuizAttempt.objects.select_related("vocabulary_set").prefetch_related(
            Prefetch(
                "attempt_questions__question__choices",
                queryset=QuestionChoice.objects.order_by("order"),
            )
        ),
        pk=attempt_id,
        user=request.user,
    )
    if not attempt.is_submitted:
        return redirect("vocabulary:quiz", attempt_id=attempt.id)

    rows = []
    wrong_question_ids = []
    for attempt_question in attempt.attempt_questions.select_related(
        "question",
        "question__word_sense",
        "question__word_sense__word",
        "answer",
        "answer__selected_choice",
    ):
        correct_choice = attempt_question.question.choices.get(is_correct=True)
        answer = getattr(attempt_question, "answer", None)
        selected_choice = answer.selected_choice if answer else None
        display_map = choice_display_map(attempt_question)
        is_correct = bool(answer and answer.is_correct)
        if not is_correct:
            wrong_question_ids.append(attempt_question.question_id)
        rows.append(
            {
                "attempt_question": attempt_question,
                "question": attempt_question.question,
                "answer": answer,
                "selected_choice": selected_choice,
                "selected_display_label": display_map.get(selected_choice.id)
                if selected_choice
                else "",
                "correct_choice": correct_choice,
                "correct_display_label": display_map.get(correct_choice.id, ""),
                "is_correct": is_correct,
            }
        )

    return render(
        request,
        "vocabulary/result.html",
        {
            "attempt": attempt,
            "rows": rows,
            "has_wrong": bool(wrong_question_ids),
        },
    )


@login_required
def retry_wrong(request, attempt_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    attempt = get_object_or_404(QuizAttempt, pk=attempt_id, user=request.user)
    if not attempt.is_submitted:
        return redirect("vocabulary:quiz", attempt_id=attempt.id)

    wrong_question_ids = [
        attempt_question.question_id
        for attempt_question in attempt.attempt_questions.select_related("answer")
        if not getattr(attempt_question, "answer", None)
        or not attempt_question.answer.is_correct
    ]
    if not wrong_question_ids:
        return redirect("vocabulary:result", attempt_id=attempt.id)
    new_attempt = create_quiz_attempt(
        attempt.vocabulary_set,
        len(wrong_question_ids),
        user=request.user,
        only_question_ids=wrong_question_ids,
    )
    return redirect("vocabulary:quiz", attempt_id=new_attempt.id)
