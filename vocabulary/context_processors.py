from django.conf import settings

from .models import VocabularySet


def site_state(request):
    return {
        "primary_vocabulary_set": VocabularySet.objects.filter(is_published=True)
        .order_by("level", "unit")
        .first(),
        "heartbeat_interval_ms": settings.HEARTBEAT_INTERVAL_SECONDS * 1000,
    }
