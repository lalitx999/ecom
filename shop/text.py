import re
import unicodedata


def make_slug(text):
    """URL-safe slug that keeps Thai letters and tone marks (Django's slugify() drops the combining marks)."""
    text = unicodedata.normalize('NFC', text).strip().lower()
    text = re.sub(r'[^\w฀-๿\s-]', '', text)
    return re.sub(r'[-\s]+', '-', text).strip('-_')


def unique_slug(model, source, instance=None, fallback='item', max_length=40):
    base = make_slug(source)[:max_length].strip('-') or fallback
    slug, n = base, 2
    qs = model.objects.all()
    if instance is not None and instance.pk:
        qs = qs.exclude(pk=instance.pk)
    while qs.filter(slug=slug).exists():
        slug, n = f'{base}-{n}', n + 1
    return slug
