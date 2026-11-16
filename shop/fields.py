from django.core import validators as dj_validators
from django.core.validators import RegexValidator
from django.db import models

# Letters, digits, "_" and "-" plus the Thai block (Django's own slug validators reject Thai tone marks).
validate_thai_slug = RegexValidator(r'^[-\w฀-๿]+\Z', 'ใช้ได้เฉพาะตัวอักษร ตัวเลข และเครื่องหมาย -')


class ThaiSlugField(models.SlugField):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # CharField.__init__ already cached the stock slug validator in self.validators; swap it for ours.
        stock = (dj_validators.validate_slug, dj_validators.validate_unicode_slug)
        self.validators[:] = [validate_thai_slug] + [v for v in self.validators if v not in stock]

    def formfield(self, **kwargs):
        return models.CharField.formfield(self, **{'max_length': self.max_length, **kwargs})


# ---- private storage for payment slips ----
import os
import uuid

from django.conf import settings
from django.core.files.storage import FileSystemStorage


def private_storage():
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT)


def slip_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp'):
        ext = '.jpg'
    return f'slips/{uuid.uuid4().hex}{ext}'  # unguessable name
