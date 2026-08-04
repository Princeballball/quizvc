from .models import VocabularySet


def primary_vocabulary_set(request):
    return {
        "primary_vocabulary_set": VocabularySet.objects.filter(is_published=True)
        .order_by("level", "unit")
        .first()
    }
