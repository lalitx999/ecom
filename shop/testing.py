import io
import shutil
import tempfile

from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from .models import Order


class SlipStorageMixin:
    """Keeps uploaded test slips out of the real private_media folder."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._slip_tmp = tempfile.mkdtemp()
        field = Order._meta.get_field('payment_slip')
        cls._slip_orig = field.storage
        field.storage = FileSystemStorage(location=cls._slip_tmp)

    @classmethod
    def tearDownClass(cls):
        Order._meta.get_field('payment_slip').storage = cls._slip_orig
        shutil.rmtree(cls._slip_tmp, ignore_errors=True)
        super().tearDownClass()


def image_file(name='slip.png', fmt='PNG', size=(30, 30)):
    buf = io.BytesIO()
    Image.new('RGB', size, '#0b0b5c').save(buf, fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f'image/{fmt.lower()}')
