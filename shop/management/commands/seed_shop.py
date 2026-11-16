from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from shop.models import Category, Product

CATEGORIES = [
    ('ความสวยความงาม', 'beauty'),
    ('บำรุงผิวหน้า', 'face-care'),
    ('บำรุงผิวกาย', 'body-care'),
    ('ดูแลเส้นผม', 'hair-care'),
    ('อาหารเสริม', 'supplements'),
    ('ดูแลช่องปาก', 'oral-care'),
]

# slug, category slug, name, brand, size, price, compare, stock, new, best, shape, color
PRODUCTS = [
    ('glow-aha-toner', 'face-care', 'โกลว์ ไกลโคลิก แอซิด 7% เอ็กซ์โฟลิเอติ้ง โทนเนอร์ 240 มล.', 'Glow Lab', '240 มล.', 770, 990, 24, False, True, 'dropper', '#f2e3b3'),
    ('glow-niacinamide-serum', 'face-care', 'โกลว์ ไนอาซินาไมด์ 10% เซรั่มลดรอยสิว 30 มล.', 'Glow Lab', '30 มล.', 349, 459, 40, True, True, 'dropper', '#dbe4f7'),
    ('glow-hyaluronic-serum', 'face-care', 'โกลว์ ไฮยาลูรอนิค แอซิด เซรั่มเติมน้ำให้ผิว 30 มล.', 'Glow Lab', '30 มล.', 399, None, 35, False, False, 'dropper', '#d4eadf'),
    ('prime-gel-cleanser', 'face-care', 'ไพรม์ เจลล้างหน้า สูตรอ่อนโยน 150 มล.', 'Prime Forever', '150 มล.', 519, 749, 18, False, True, 'tube', '#c9d8f5'),
    ('prime-moisturiser', 'face-care', 'ไพรม์ มอยส์เจอไรเซอร์ ครีมบำรุงผิวหน้า 50 มล.', 'Prime Forever', '50 มล.', 999, 1499, 12, True, False, 'jar', '#c9d8f5'),
    ('prime-eye-cream', 'face-care', 'ไพรม์ อายครีม ลดริ้วรอยรอบดวงตา 15 มล.', 'Prime Forever', '15 มล.', 659, 949, 9, False, False, 'tube', '#c9d8f5'),
    ('clear-micellar-water', 'beauty', 'เคลียร์ ไมเซลลาร์ คลีนซิ่งวอเตอร์ 500 มล.', 'Clear Skin', '500 มล.', 289, 399, 60, False, True, 'pump', '#f7c9d2'),
    ('clear-sunscreen-spf50', 'beauty', 'เคลียร์ ซันสกรีน SPF50+ PA++++ 50 มล.', 'Clear Skin', '50 มล.', 459, None, 52, True, True, 'tube', '#ffe27a'),
    ('rosé-lip-balm', 'beauty', 'โรเซ่ ลิปบาล์ม บำรุงริมฝีปาก 4.5 กรัม', 'Rosé', '4.5 กรัม', 129, 159, 100, False, False, 'tube', '#f7c9d2'),
    ('rosé-cushion', 'beauty', 'โรเซ่ คุชชั่น ครอบคลุมผิวเนียน 15 กรัม', 'Rosé', '15 กรัม', 590, 790, 0, False, False, 'jar', '#f7c9d2'),
    ('aloe-body-lotion', 'body-care', 'อโล บอดี้โลชั่น ว่านหางจระเข้ 400 มล.', 'Aloe Daily', '400 มล.', 199, 259, 70, False, True, 'pump', '#cfe8cf'),
    ('aloe-shower-gel', 'body-care', 'อโล ครีมอาบน้ำ กลิ่นสดชื่น 500 มล.', 'Aloe Daily', '500 มล.', 169, None, 80, False, False, 'pump', '#cfe8cf'),
    ('shea-hand-cream', 'body-care', 'ชีอา แฮนด์ครีม บำรุงมือ 75 มล.', 'Shea Co.', '75 มล.', 119, 149, 90, True, False, 'tube', '#f3dcc2'),
    ('shea-body-butter', 'body-care', 'ชีอา บอดี้บัตเตอร์ เข้มข้น 200 มล.', 'Shea Co.', '200 มล.', 329, 429, 30, False, False, 'jar', '#f3dcc2'),
    ('herbal-shampoo', 'hair-care', 'เฮอร์บัล แชมพู ลดผมขาดหลุดร่วง 400 มล.', 'Herbal Root', '400 มล.', 249, 329, 45, False, True, 'pump', '#d9d0f0'),
    ('herbal-conditioner', 'hair-care', 'เฮอร์บัล ครีมนวดผม สูตรเข้มข้น 400 มล.', 'Herbal Root', '400 มล.', 249, 329, 38, False, False, 'pump', '#d9d0f0'),
    ('argan-hair-oil', 'hair-care', 'อาร์แกน แฮร์ออยล์ บำรุงผมเสีย 100 มล.', 'Herbal Root', '100 มล.', 359, None, 22, True, False, 'dropper', '#f3dcc2'),
    ('vitc-fizz', 'supplements', 'วิตามินซี ฟิซซี่ เม็ดฟู่ รสส้ม 20 เม็ด', 'Vita Plus', '20 เม็ด', 259, 329, 120, False, True, 'box', '#ffb74d'),
    ('collagen-sachet', 'supplements', 'คอลลาเจน ผงชงดื่ม 14 ซอง', 'Vita Plus', '14 ซอง', 690, 890, 26, True, True, 'box', '#c9d8f5'),
    ('zinc-vitamin', 'supplements', 'ซิงค์ + วิตามินดี3 ผลิตภัณฑ์เสริมอาหาร 60 เม็ด', 'Vita Plus', '60 เม็ด', 349, None, 65, False, False, 'box', '#d4eadf'),
    ('omega3-fish-oil', 'supplements', 'โอเมก้า 3 น้ำมันปลา 1000 มก. 60 แคปซูล', 'Vita Plus', '60 แคปซูล', 450, 590, 8, False, False, 'box', '#ffe27a'),
    ('mint-toothpaste', 'oral-care', 'มิ้นท์ ยาสีฟัน สูตรฟันขาว 160 กรัม', 'Fresh Smile', '160 กรัม', 79, 99, 150, False, True, 'tube', '#d4eadf'),
    ('mint-mouthwash', 'oral-care', 'มิ้นท์ น้ำยาบ้วนปาก ลมหายใจสดชื่น 750 มล.', 'Fresh Smile', '750 มล.', 139, None, 85, False, False, 'pump', '#d4eadf'),
    ('soft-toothbrush-3', 'oral-care', 'ซอฟท์ แปรงสีฟันขนนุ่ม แพ็ก 3 ด้าม', 'Fresh Smile', '3 ด้าม', 99, 129, 200, True, False, 'box', '#c9d8f5'),
]


def bottle_svg(shape, color, brand):
    """Flat, solid-color product illustration (no gradients)."""
    ink = '#0b0b5c'
    label = f'<rect x="140" y="{{y}}" width="120" height="{{h}}" rx="6" fill="#ffffff"/>'
    body = ''
    if shape == 'dropper':
        body = (f'<rect x="185" y="48" width="30" height="46" rx="12" fill="{ink}"/><rect x="170" y="92" width="60" height="26" rx="6" fill="#ffffff" stroke="{ink}" stroke-width="3"/>'
                f'<rect x="130" y="116" width="140" height="240" rx="26" fill="{color}"/>' + label.format(y=190, h=110))
    elif shape == 'pump':
        body = (f'<rect x="188" y="40" width="24" height="46" rx="6" fill="{ink}"/><rect x="170" y="36" width="70" height="16" rx="8" fill="{ink}"/>'
                f'<rect x="165" y="84" width="70" height="30" rx="6" fill="#ffffff" stroke="{ink}" stroke-width="3"/>'
                f'<rect x="125" y="112" width="150" height="250" rx="30" fill="{color}"/>' + label.format(y=190, h=120))
    elif shape == 'tube':
        body = (f'<rect x="150" y="48" width="100" height="40" rx="8" fill="{ink}"/><path d="M140 88h120l-14 270a10 10 0 0 1-10 10h-72a10 10 0 0 1-10-10z" fill="{color}"/>'
                + label.format(y=180, h=110).replace('x="140"', 'x="152"').replace('width="120"', 'width="96"'))
    elif shape == 'jar':
        body = (f'<rect x="105" y="130" width="190" height="60" rx="12" fill="{ink}"/><rect x="115" y="188" width="170" height="160" rx="26" fill="{color}"/>'
                + label.format(y=222, h=84).replace('x="140"', 'x="150"').replace('width="120"', 'width="100"'))
    else:  # box
        body = (f'<rect x="100" y="110" width="200" height="250" rx="10" fill="{color}"/><rect x="100" y="110" width="200" height="40" rx="10" fill="{ink}"/>'
                + label.format(y=190, h=110).replace('x="140"', 'x="130"').replace('width="120"', 'width="140"'))
    brand_txt = (f'<text x="200" y="{ {"jar": 256, "box": 232}.get(shape, 230) }" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="15" font-weight="700" fill="{ink}">{brand}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect width="400" height="400" fill="#f4f4f8"/>'
            f'<ellipse cx="200" cy="372" rx="110" ry="9" fill="#e2e2ea"/>{body}{brand_txt}</svg>')


class Command(BaseCommand):
    help = 'Create sample categories and products (safe to run repeatedly).'

    @transaction.atomic
    def handle(self, *args, **options):
        cats = {}
        for i, (name, slug) in enumerate(CATEGORIES):
            cats[slug], _ = Category.objects.update_or_create(slug=slug, defaults={'name': name, 'order': i})

        created = 0
        for slug, cat, name, brand, size, price, compare, stock, is_new, is_best, shape, color in PRODUCTS:
            slug = slug.replace('é', 'e')
            product, was_created = Product.objects.update_or_create(slug=slug, defaults={
                'category': cats[cat], 'name': name, 'brand': brand, 'size': size,
                'description': f'{name}\n\nแบรนด์: {brand}\nขนาด: {size}\n\nสินค้าตัวอย่างสำหรับทดสอบระบบร้านค้า สามารถแก้ไขข้อมูลได้ที่หน้าผู้ดูแลระบบ',
                'price': Decimal(price), 'compare_price': Decimal(compare) if compare else None,
                'stock': stock, 'is_new': is_new, 'is_best_seller': is_best, 'is_active': True,
            })
            if was_created or not product.image:
                product.image.save(f'{slug}.svg', ContentFile(bottle_svg(shape, color, brand).encode('utf-8')), save=True)
            created += was_created
        self.stdout.write(self.style.SUCCESS(f'{len(CATEGORIES)} categories, {len(PRODUCTS)} products ({created} new)'))
