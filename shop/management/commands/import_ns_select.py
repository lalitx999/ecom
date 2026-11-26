"""Import the NS SELECT catalogue from data/ns_select_products.json (made from the photos in Work/).

Safe to run again: products are matched by slug and variants by (colour, size). On a re-run prices and
flags are updated, but stock is never overwritten and images are only added to products that have none.
"""
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from PIL import Image, ImageOps

from shop.models import Brand, Category, Product, ProductImage, ProductVariant
from shop.text import make_slug, unique_slug

CATEGORY_NAMES = {'skincare-set': 'ชุดบำรุงผิว', 'clothing': 'เสื้อผ้า', 'shoes': 'รองเท้า'}
MAX_IMAGE_SIDE = 1200
STOCK_IF_AVAILABLE = 1  # the screenshots show prices, not quantities: adjust real stock in the back office


def to_decimal(value):
    return None if value is None else Decimal(str(value))


def jpeg_bytes(path):
    """Any of PNG/JPEG/WebP (even without an extension) -> RGB JPEG no larger than MAX_IMAGE_SIDE."""
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGBA')
            bg = Image.new('RGB', img.size, 'white')
            bg.paste(img, mask=img.split()[-1])
            img = bg
        else:
            img = img.convert('RGB')
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=86, optimize=True)
        return buf.getvalue()


class Command(BaseCommand):
    help = 'นำเข้าสินค้า NS SELECT จาก data/ns_select_products.json และรูปในโฟลเดอร์ Work/'

    def add_arguments(self, parser):
        parser.add_argument('--data', default=str(settings.BASE_DIR / 'data' / 'ns_select_products.json'))
        parser.add_argument('--source', default=str(settings.BASE_DIR / 'Work'), help='โฟลเดอร์รูปต้นฉบับ')

    def handle(self, *args, **opts):
        data_path, source = Path(opts['data']), Path(opts['source'])
        if not data_path.exists():
            raise CommandError(f'ไม่พบไฟล์ข้อมูล {data_path}')
        if not source.is_dir():
            raise CommandError(f'ไม่พบโฟลเดอร์รูป {source}')
        catalogue = json.loads(data_path.read_text(encoding='utf-8'))

        with transaction.atomic():
            categories = {}
            for order, c in enumerate(catalogue['categories'], start=1):
                name = CATEGORY_NAMES.get(c['key'], c['name'])
                cat, _ = Category.objects.update_or_create(slug=c['key'], defaults={'name': name, 'order': order})
                categories[c['key']] = cat

            counts = {'products': 0, 'variants': 0, 'images': 0}
            for item in catalogue['products']:
                created_variants, created_images = self.import_product(item, categories, source)
                counts['products'] += 1
                counts['variants'] += created_variants
                counts['images'] += created_images

        self.stdout.write(self.style.SUCCESS(
            f"นำเข้าแล้ว {counts['products']} สินค้า | ตัวเลือกใหม่ {counts['variants']} | รูปใหม่ {counts['images']}"))

    # ------------------------------------------------------------------
    def brand_for(self, name):
        if not name:
            return None
        brand = Brand.objects.filter(name__iexact=name).first()
        return brand or Brand.objects.create(name=name, slug=unique_slug(Brand, name, None, 'brand'))

    def import_product(self, item, categories, source):
        slug = make_slug(item['name'])[:50].strip('-')
        expiry = None
        if item.get('expiry'):
            y, m = item['expiry'].split('-')[:2]
            expiry = date(int(y), int(m), 1)
        product, _ = Product.objects.update_or_create(slug=slug, defaults={
            'category': categories[item['category']],
            'brand': self.brand_for(item.get('brand')),
            'name': item['name'],
            'description': item.get('description', ''),
            'set_contents': '\n'.join(item.get('set_contents', [])),
            'how_to_use': '\n'.join(item.get('how_to_use', [])),
            'origin': item.get('origin', ''),
            'expiry_date': expiry,
            'is_active': True,
        })

        created_variants = 0
        for order, row in enumerate(self.variant_rows(item)):
            _, created = ProductVariant.objects.update_or_create(
                product=product, color=row['color'], size=row['size'],
                defaults={'price': row['price'], 'compare_price': row['compare'], 'ready_to_ship': row['ready'],
                          'is_active': True, 'sort_order': order},
                create_defaults={'price': row['price'], 'compare_price': row['compare'], 'ready_to_ship': row['ready'],
                                 'is_active': True, 'sort_order': order, 'stock': row['stock']},
            )
            created_variants += created

        created_images = 0
        if not product.images.exists():
            colors = self.image_colors(item)
            for order, rel in enumerate(item.get('images', [])):
                path = source / rel
                if not path.exists():
                    self.stderr.write(f'  ไม่พบรูป {path}')
                    continue
                img = ProductImage(product=product, color=colors[order] if colors else '', sort_order=order)
                img.image.save(f'{slug}-{order + 1}.jpg', ContentFile(jpeg_bytes(path)), save=True)
                created_images += 1
        return created_variants, created_images

    def variant_rows(self, item):
        """Turn the JSON variants into rows of colour/size/price/stock.

        - no variants (skincare sets, clothing 1): one row with the regular price as the crossed-out price
        - sizes the screenshot shows as unavailable have no price and are skipped
        - colours seen in the screenshot but without their own prices get the shown colour's prices and stock 0
        - a colour-less row on a product with several colours (one price for all) is repeated for every colour
        """
        if not item.get('variants'):
            price, regular = to_decimal(item.get('price_net')), to_decimal(item.get('price_regular'))
            if price is None:
                price, regular = regular, None
            return [{'color': '', 'size': '', 'price': price, 'compare': regular if regular and regular > price else None,
                     'stock': STOCK_IF_AVAILABLE, 'ready': False}]

        seen = item.get('colors_seen', [])
        rows, keys = [], set()

        def add(color, size, price, stock, ready):
            if (color, size) not in keys:
                keys.add((color, size))
                rows.append({'color': color, 'size': size, 'price': price, 'compare': None, 'stock': stock, 'ready': ready})

        priced = [v for v in item['variants'] if v.get('price') is not None and v.get('available', True)]
        for v in priced:
            stock = STOCK_IF_AVAILABLE
            if v.get('color'):
                add(v['color'], v.get('size') or '', to_decimal(v['price']), stock, v.get('fast', False))
            elif seen:
                for c in seen:
                    add(c, v.get('size') or '', to_decimal(v['price']), stock, v.get('fast', False))
            else:
                add('', v.get('size') or '', to_decimal(v['price']), stock, v.get('fast', False))
        shown = {v.get('color') for v in priced if v.get('color')}
        for c in seen:
            if shown and c not in shown:
                for v in priced:
                    add(c, v.get('size') or '', to_decimal(v['price']), 0, False)
        return rows

    def image_colors(self, item):
        """When each photo is a different colour of a one-price product (clothing 6), tag photos with their colour."""
        seen, images = item.get('colors_seen', []), item.get('images', [])
        if seen and len(seen) == len(images) and all(not v.get('color') for v in item.get('variants', [])):
            return seen
        return None
