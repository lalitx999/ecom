from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.db import models
from django.templatetags.static import static
from django.utils import timezone
from django.utils.functional import cached_property

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


class Brand(models.Model):
    name = models.CharField('ชื่อแบรนด์', max_length=100, unique=True)
    slug = ThaiSlugField(unique=True, allow_unicode=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'แบรนด์'
        verbose_name_plural = 'แบรนด์'

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def for_listing(self):
        """Active products with what cards need (variants, images, brand) fetched in a few queries."""
        return (self.filter(is_active=True, variants__is_active=True).distinct()
                .select_related('category', 'brand').prefetch_related('variants', 'images'))

    def with_min_price(self):
        return self.annotate(price_min=models.Min('variants__price', filter=models.Q(variants__is_active=True)))

    def on_sale(self):
        return self.filter(variants__is_active=True, variants__compare_price__gt=models.F('variants__price')).distinct()


class Product(models.Model):
    """A product page. Price and stock live on its variants (one variant when there are no options)."""
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products', verbose_name='หมวดหมู่')
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name='products', verbose_name='แบรนด์', null=True, blank=True)
    name = models.CharField('ชื่อสินค้า', max_length=200)
    slug = ThaiSlugField(unique=True, allow_unicode=True)
    description = models.TextField('ข้อมูลสินค้า', blank=True)
    set_contents = models.TextField('สิ่งที่อยู่ในชุด', blank=True, help_text='หนึ่งบรรทัดต่อหนึ่งรายการ')
    how_to_use = models.TextField('วิธีใช้', blank=True, help_text='หนึ่งบรรทัดต่อหนึ่งขั้นตอน')
    origin = models.CharField('ประเทศที่ผลิต', max_length=80, blank=True)
    expiry_date = models.DateField('วันหมดอายุ', null=True, blank=True, help_text='ใช้เฉพาะเดือนและปี')
    is_active = models.BooleanField('แสดงสินค้า', default=True)
    is_new = models.BooleanField('สินค้าใหม่', default=False)
    is_best_seller = models.BooleanField('สินค้าขายดี', default=False)
    is_featured = models.BooleanField('แสดงในแบนเนอร์หน้าแรก', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at', 'name']
        verbose_name = 'สินค้า'
        verbose_name_plural = 'สินค้า'
        indexes = [models.Index(fields=['is_active', '-created_at'])]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('shop:product_detail', args=[self.slug])

    # --- variants & images (work best with the prefetches in ProductQuerySet.for_listing) ---
    @cached_property
    def active_variants(self):
        return [v for v in self.variants.all() if v.is_active]

    @cached_property
    def stocked_variants(self):
        return [v for v in self.active_variants if v.stock > 0]

    @cached_property
    def image_list(self):
        return list(self.images.all())

    @property
    def image_url(self):
        return self.image_list[0].image.url if self.image_list else static('img/placeholder.svg')

    @property
    def in_stock(self):
        return bool(self.stocked_variants)

    @property
    def total_stock(self):
        return sum(v.stock for v in self.active_variants)

    def _price_pool(self):
        return self.stocked_variants or self.active_variants

    @property
    def min_price(self):
        pool = self._price_pool()
        return min(v.price for v in pool) if pool else None

    @property
    def max_price(self):
        pool = self._price_pool()
        return max(v.price for v in pool) if pool else None

    @property
    def has_price_range(self):
        return self.min_price != self.max_price

    @property
    def cheapest(self):
        pool = self._price_pool()
        return min(pool, key=lambda v: (v.price, v.sort_order)) if pool else None

    @property
    def on_sale(self):
        return any(v.on_sale for v in self._price_pool())

    @property
    def discount_percent(self):
        return max((v.discount_percent for v in self._price_pool()), default=0)

    @property
    def single_variant(self):
        """The variant to add straight from a product card, when there is nothing to choose."""
        return self.active_variants[0] if len(self.active_variants) == 1 else None

    @property
    def colors(self):
        return list(dict.fromkeys(v.color for v in self.active_variants if v.color))

    @property
    def sizes(self):
        return list(dict.fromkeys(v.size for v in self.active_variants if v.size))

    @property
    def set_contents_list(self):
        return [line.strip() for line in self.set_contents.splitlines() if line.strip()]

    @property
    def how_to_use_list(self):
        return [line.strip() for line in self.how_to_use.splitlines() if line.strip()]


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField('รูป', upload_to='products/')
    color = models.CharField('ใช้กับสี', max_length=50, blank=True, help_text='เว้นว่างถ้าใช้กับทุกสี')
    sort_order = models.PositiveIntegerField('ลำดับ', default=0)

    class Meta:
        ordering = ['sort_order', 'pk']
        verbose_name = 'รูปสินค้า'
        verbose_name_plural = 'รูปสินค้า'

    def __str__(self):
        return f'{self.product} #{self.sort_order}'


class VariantQuerySet(models.QuerySet):
    def purchasable(self):
        return self.filter(is_active=True, product__is_active=True)


class ProductVariant(models.Model):
    """One buyable option (colour x size). Products without options have a single variant with both blank."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    color = models.CharField('สี', max_length=50, blank=True)
    size = models.CharField('ไซซ์ / ขนาด', max_length=50, blank=True)
    sku = models.CharField('รหัสสินค้า (SKU)', max_length=40, unique=True, null=True, blank=True)
    price = models.DecimalField('ราคาขาย', max_digits=10, decimal_places=2)
    compare_price = models.DecimalField('ราคาปกติ', max_digits=10, decimal_places=2, null=True, blank=True,
                                        help_text='ใส่เมื่อต้องการแสดงราคาขีดฆ่า')
    stock = models.PositiveIntegerField('สต็อก', default=0)
    ready_to_ship = models.BooleanField('พร้อมส่ง', default=False)
    is_active = models.BooleanField('เปิดขาย', default=True)
    sort_order = models.PositiveIntegerField('ลำดับ', default=0)

    objects = VariantQuerySet.as_manager()

    class Meta:
        ordering = ['sort_order', 'pk']
        verbose_name = 'ตัวเลือกสินค้า'
        verbose_name_plural = 'ตัวเลือกสินค้า'
        constraints = [models.UniqueConstraint(fields=['product', 'color', 'size'], name='unique_variant_option')]

    def __str__(self):
        return f'{self.product.name} ({self.label})' if self.label else self.product.name

    def save(self, *args, **kwargs):
        if self.sku == '':
            self.sku = None
        super().save(*args, **kwargs)
        if not self.sku:
            self.sku = f'NS{self.product_id:04d}-{self.pk:05d}'
            super().save(update_fields=['sku'])

    @property
    def label(self):
        return ' / '.join(x for x in (self.color, self.size) if x)

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

    @property
    def image_url(self):
        images = self.product.image_list
        match = next((i for i in images if self.color and i.color == self.color), None)
        return (match or images[0]).image.url if images else static('img/placeholder.svg')


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
            self.number = f'NS{timezone.localtime(self.created_at):%y%m%d}{self.pk:05d}'
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
    variant = models.ForeignKey(ProductVariant, on_delete=models.SET_NULL, null=True, blank=True, related_name='order_items')
    name = models.CharField(max_length=200)
    color = models.CharField(max_length=50, blank=True)
    size = models.CharField(max_length=50, blank=True)
    sku = models.CharField(max_length=40, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    qty = models.PositiveIntegerField()
    image_url = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = 'รายการสินค้า'
        verbose_name_plural = 'รายการสินค้า'

    @property
    def variant_label(self):
        return ' / '.join(x for x in (self.color, self.size) if x)

    @property
    def line_total(self):
        return self.unit_price * self.qty
