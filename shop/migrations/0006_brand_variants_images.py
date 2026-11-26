"""Products get variants (colour x size), several images and a Brand table.

Existing data is carried over: every product becomes one variant with its old price/stock/size,
its image becomes the first ProductImage, brand names become Brand rows, and order items are linked
to the new variant.
"""
import django.db.models.deletion
import shop.fields
from django.db import migrations, models

from shop.text import make_slug


def forwards(apps, schema_editor):
    Brand = apps.get_model('shop', 'Brand')
    Product = apps.get_model('shop', 'Product')
    ProductVariant = apps.get_model('shop', 'ProductVariant')
    ProductImage = apps.get_model('shop', 'ProductImage')
    OrderItem = apps.get_model('shop', 'OrderItem')

    brands = {}
    for product in Product.objects.all():
        name = (product.brand_name or '').strip()
        if name:
            if name not in brands:
                base = make_slug(name)[:40] or 'brand'
                slug, n = base, 2
                while Brand.objects.filter(slug=slug).exists():
                    slug, n = f'{base}-{n}', n + 1
                brands[name] = Brand.objects.create(name=name, slug=slug)
            product.brand = brands[name]
            product.save(update_fields=['brand'])

        variant = ProductVariant.objects.create(
            product=product, size=product.old_size, price=product.price, compare_price=product.compare_price,
            stock=product.stock, is_active=True)
        variant.sku = f'NS{product.pk:04d}-{variant.pk:05d}'
        variant.save(update_fields=['sku'])
        if product.image:
            ProductImage.objects.create(product=product, image=product.image.name, sort_order=0)
        OrderItem.objects.filter(product=product).update(variant=variant)


class Migration(migrations.Migration):

    dependencies = [
        ('shop', '0005_order_carrier_order_paid_at_order_payment_slip_and_more'),
    ]

    operations = [
        migrations.RenameField('product', 'brand', 'brand_name'),
        migrations.RenameField('product', 'size', 'old_size'),
        migrations.CreateModel(
            name='Brand',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='ชื่อแบรนด์')),
                ('slug', shop.fields.ThaiSlugField(allow_unicode=True, unique=True)),
            ],
            options={'verbose_name': 'แบรนด์', 'verbose_name_plural': 'แบรนด์', 'ordering': ['name']},
        ),
        migrations.AddField(
            model_name='product', name='brand',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='products', to='shop.brand', verbose_name='แบรนด์'),
        ),
        migrations.AddField('product', 'set_contents', models.TextField(blank=True, help_text='หนึ่งบรรทัดต่อหนึ่งรายการ', verbose_name='สิ่งที่อยู่ในชุด')),
        migrations.AddField('product', 'how_to_use', models.TextField(blank=True, help_text='หนึ่งบรรทัดต่อหนึ่งขั้นตอน', verbose_name='วิธีใช้')),
        migrations.AddField('product', 'origin', models.CharField(blank=True, max_length=80, verbose_name='ประเทศที่ผลิต')),
        migrations.AddField('product', 'expiry_date', models.DateField(blank=True, help_text='ใช้เฉพาะเดือนและปี', null=True, verbose_name='วันหมดอายุ')),
        migrations.AddField('product', 'is_featured', models.BooleanField(default=False, verbose_name='แสดงในแบนเนอร์หน้าแรก')),
        migrations.CreateModel(
            name='ProductImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='products/', verbose_name='รูป')),
                ('color', models.CharField(blank=True, help_text='เว้นว่างถ้าใช้กับทุกสี', max_length=50, verbose_name='ใช้กับสี')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='ลำดับ')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='shop.product')),
            ],
            options={'verbose_name': 'รูปสินค้า', 'verbose_name_plural': 'รูปสินค้า', 'ordering': ['sort_order', 'pk']},
        ),
        migrations.CreateModel(
            name='ProductVariant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('color', models.CharField(blank=True, max_length=50, verbose_name='สี')),
                ('size', models.CharField(blank=True, max_length=50, verbose_name='ไซซ์ / ขนาด')),
                ('sku', models.CharField(blank=True, max_length=40, null=True, unique=True, verbose_name='รหัสสินค้า (SKU)')),
                ('price', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='ราคาขาย')),
                ('compare_price', models.DecimalField(blank=True, decimal_places=2, help_text='ใส่เมื่อต้องการแสดงราคาขีดฆ่า', max_digits=10, null=True, verbose_name='ราคาปกติ')),
                ('stock', models.PositiveIntegerField(default=0, verbose_name='สต็อก')),
                ('ready_to_ship', models.BooleanField(default=False, verbose_name='พร้อมส่ง')),
                ('is_active', models.BooleanField(default=True, verbose_name='เปิดขาย')),
                ('sort_order', models.PositiveIntegerField(default=0, verbose_name='ลำดับ')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='variants', to='shop.product')),
            ],
            options={
                'verbose_name': 'ตัวเลือกสินค้า', 'verbose_name_plural': 'ตัวเลือกสินค้า', 'ordering': ['sort_order', 'pk'],
                'constraints': [models.UniqueConstraint(fields=('product', 'color', 'size'), name='unique_variant_option')],
            },
        ),
        migrations.AddField(
            model_name='orderitem', name='variant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='order_items', to='shop.productvariant'),
        ),
        migrations.AddField('orderitem', 'color', models.CharField(blank=True, max_length=50)),
        migrations.AddField('orderitem', 'sku', models.CharField(blank=True, max_length=40)),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.RemoveField('product', 'brand_name'),
        migrations.RemoveField('product', 'old_size'),
        migrations.RemoveField('product', 'price'),
        migrations.RemoveField('product', 'compare_price'),
        migrations.RemoveField('product', 'stock'),
        migrations.RemoveField('product', 'image'),
    ]
