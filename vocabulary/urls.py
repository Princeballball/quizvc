from django.urls import path

from . import views

app_name = "vocabulary"

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("accounts/history/", views.quiz_history, name="quiz_history"),
    path("sets/<slug:slug>/words/", views.word_list, name="word_list"),
    path("sets/<slug:slug>/start/", views.start_quiz, name="start_quiz"),
    path("attempts/<uuid:attempt_id>/", views.quiz, name="quiz"),
    path("attempts/<uuid:attempt_id>/submit/", views.submit_quiz, name="submit_quiz"),
    path("attempts/<uuid:attempt_id>/result/", views.result, name="result"),
    path(
        "attempts/<uuid:attempt_id>/retry-wrong/",
        views.retry_wrong,
        name="retry_wrong",
    ),
]
