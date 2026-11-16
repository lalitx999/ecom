from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.db import models
from django.templatetags.static import static
from django.utils import timezone

from .fields import ThaiSlugField, private_storage, slip_upload_to
from django.urls import reverse


class Category(models.Model):
    name = models.CharField('ชื่อหมวดหมู่', max_length=100)
    slug = ThaiSlugField(unique=True, allow_unicode=True)
    order = models.PositiveIntegerField('ลำดับ', default=0)

    class Meta:
        ordering = ['order', 'name']
        verbose_name = 'หมวดหมู่'
        verbose_name_plural = 'หมวดหมู่'

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products', verbose_name='หมวดหมู่')
    name = models.CharField('ชื่อสินค้า', max_length=200)
    slug = ThaiSlugField(unique=True, allow_unicode=True)
    brand = models.CharField('แบรนด์', max_length=100, blank=True)
    size = models.CharField('ขนาดบรรจุภัณฑ์', max_length=50, blank=True)
    description = models.TextField('ข้อมูลสินค้า', blank=True)
    price = models.DecimalField('ราคาขาย', max_digits=10, decimal_places=2)
    compare_price = models.DecimalField('ราคาปกติ', max_digits=10, decimal_places=2, null=True, blank=True,
                                        help_text='ใส่เมื่อต้องการแสดงราคาขีดฆ่าและเปอร์เซ็นต์ส่วนลด')
    stock = models.PositiveIntegerField('จำนวนในสต็อก', default=0)
    image = models.ImageField('รูปสินค้า', upload_to='products/', blank=True)
    is_active = models.BooleanField('แสดงสินค้า', default=True)
    is_new = models.BooleanField('สินค้าใหม่', default=False)
    is_best_seller = models.BooleanField('สินค้าขายดี', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', 'name']
        verbose_name = 'สินค้า'
        verbose_name_plural = 'สินค้า'
        indexes = [models.Index(fields=['is_active', '-created_at'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('shop:product_detail', args=[self.slug])

    @property
    def image_url(self):
        if self.image:
            return self.image.url
        return static('img/placeholder.svg')

    @property
    def on_sale(self):
        return bool(self.compare_price and self.compare_price > self.price)

    @property
    def discount_percent(self):
        if not self.on_sale:
            return 0
        return int(((self.compare_price - self.price) / self.compare_price * Decimal(100)).quantize(Decimal('1')))

    @property
    def in_stock(self):
        return self.stock > 0


class Carrier(models.TextChoices):
    THAILAND_POST = 'thailand_post', 'ไปรษณีย์ไทย'
    KERRY = 'kerry', 'Kerry Express'
    FLASH = 'flash', 'Flash Express'
    JT = 'jt', 'J&T Express'
    BEST = 'best', 'Best Express'
    SCG = 'scg', 'SCG Express'
    NINJA = 'ninja', 'Ninja Van'
    DHL = 'dhl', 'DHL'
    OTHER = 'other', 'อื่น ๆ'


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING_PAYMENT = 'pending_payment', 'รอชำระเงิน'
        PROCESSING = 'processing', 'กำลังเตรียมสินค้า'
        SHIPPED = 'shipped', 'จัดส่งแล้ว'
        COMPLETED = 'completed', 'สำเร็จ'
        CANCELLED = 'cancelled', 'ยกเลิก'

    class Payment(models.TextChoices):
        COD = 'cod', 'เก็บเงินปลายทาง'
        TRANSFER = 'transfer', 'โอนเงิน / พร้อมเพย์'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='orders')
    number = models.CharField('เลขที่คำสั่งซื้อ', max_length=20, unique=True, null=True, blank=True, editable=False)
    status = models.CharField('สถานะ', max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT)
    payment_method = models.CharField('วิธีชำระเงิน', max_length=20, choices=Payment.choices)

    full_name = models.CharField('ชื่อ-นามสกุล', max_length=150)
    phone = models.CharField('เบอร์โทรศัพท์', max_length=20)
    address = models.TextField('ที่อยู่จัดส่ง')
    province = models.CharField('จังหวัด', max_length=80)
    postal_code = models.CharField('รหัสไปรษณีย์', max_length=5)
    note = models.CharField('หมายเหตุ', max_length=255, blank=True)

    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    paid_at = models.DateTimeField('ชำระเงินเมื่อ', null=True, blank=True)
    payment_slip = models.ImageField('สลิปโอนเงิน', upload_to=slip_upload_to, storage=private_storage, blank=True)
    slip_uploaded_at = models.DateTimeField(null=True, blank=True)
    carrier = models.CharField('ขนส่ง', max_length=20, choices=Carrier.choices, blank=True)
    tracking_number = models.CharField('เลขพัสดุ', max_length=40, blank=True)
    shipped_at = models.DateTimeField('จัดส่งเมื่อ', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'คำสั่งซื้อ'
        verbose_name_plural = 'คำสั่งซื้อ'

    def __str__(self):
        return self.number or f'Order {self.pk}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f'LM{timezone.localtime(self.created_at):%y%m%d}{self.pk:05d}'
            super().save(update_fields=['number'])

    def get_absolute_url(self):
        return reverse('shop:order_detail', args=[self.number])

    @property
    def awaiting_payment(self):
        return self.status == self.Status.PENDING_PAYMENT

    @property
    def slip_url(self):
        return reverse('shop:order_slip', args=[self.number]) if self.payment_slip else ''

    @property
    def tracking_url(self):
        template = settings.CARRIER_TRACKING_URLS.get(self.carrier)
        return template.format(n=quote(self.tracking_number)) if template and self.tracking_number else ''


class OrderItem(models.Model):
    """Snapshot of the product at purchase time (name/price never change afterwards)."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=200)
    size = models.CharField(max_length=50, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    qty = models.PositiveIntegerField()
    image_url = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = 'รายการสินค้า'
        verbose_name_plural = 'รายการสินค้า'

    @property
    def line_total(self):
        return self.unit_price * self.qty
