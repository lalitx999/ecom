import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from shop.models import Order, OrderItem, Product

User = get_user_model()
NAMES = ['สมชาย ใจดี', 'สมหญิง รักสวย', 'วิชัย มั่นคง', 'นภา แสงทอง', 'ปรีชา สุขสันต์', 'มาลี ดอกไม้', 'ธนากร เจริญ', 'ณัฐา พิมพ์ใจ']
PROVINCES = ['กรุงเทพมหานคร', 'นนทบุรี', 'เชียงใหม่', 'ขอนแก่น', 'ภูเก็ต', 'ชลบุรี']


class Command(BaseCommand):
    help = 'DEV ONLY: create demo customers and orders spread over the last N days (does not change stock).'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=60)
        parser.add_argument('--count', type=int, default=90)
        parser.add_argument('--clear', action='store_true', help='delete previously generated demo orders/customers first')
        parser.add_argument('--purge', action='store_true', help='delete demo orders/customers and exit')

    @transaction.atomic
    def handle(self, *args, **o):
        if o['clear'] or o['purge']:
            Order.objects.filter(user__email__endswith='@demo.example.test').delete()
            User.objects.filter(email__endswith='@demo.example.test').delete()
            if o['purge']:
                self.stdout.write(self.style.SUCCESS('ลบข้อมูลตัวอย่างแล้ว'))
                return

        products = list(Product.objects.filter(is_active=True))
        if not products:
            raise CommandError('ไม่มีสินค้า กรุณารัน seed_shop ก่อน')

        rnd = random.Random(7)
        customers = []
        for i, name in enumerate(NAMES, 1):
            email = f'customer{i}@demo.example.test'
            u, created = User.objects.get_or_create(username=email, defaults={'email': email, 'first_name': name})
            if created:
                u.set_unusable_password()  # demo accounts cannot log in
                u.save()
            customers.append(u)

        now = timezone.now()
        for _ in range(o['count']):
            user = rnd.choice(customers)
            when = now - timedelta(days=rnd.random() ** 1.4 * o['days'], minutes=rnd.randint(0, 600))
            picks = rnd.sample(products, rnd.randint(1, 4))
            lines = [(p, rnd.randint(1, 3)) for p in picks]
            subtotal = sum((p.price * q for p, q in lines), Decimal('0'))
            shipping = Decimal('0') if subtotal >= 500 else Decimal('50')
            method = rnd.choice([Order.Payment.COD, Order.Payment.TRANSFER, Order.Payment.TRANSFER])
            age = (now - when).days
            status = rnd.choices(
                [Order.Status.COMPLETED, Order.Status.SHIPPED, Order.Status.PROCESSING, Order.Status.PENDING_PAYMENT, Order.Status.CANCELLED],
                [60, 15, 8, 8, 9] if age > 7 else [10, 25, 30, 25, 10])[0]
            order = Order.objects.create(
                user=user, payment_method=method, status=status, full_name=user.first_name, phone='08' + str(rnd.randint(10000000, 99999999)),
                address=f'{rnd.randint(1, 300)} ถนนตัวอย่าง', province=rnd.choice(PROVINCES), postal_code=str(rnd.randint(10000, 99999)),
                subtotal=subtotal, shipping_fee=shipping, total=subtotal + shipping)
            local = timezone.localtime(when)
            Order.objects.filter(pk=order.pk).update(created_at=when, number=f'LM{local:%y%m%d}{order.pk:05d}')
            OrderItem.objects.bulk_create(OrderItem(order=order, product=p, name=p.name, size=p.size, unit_price=p.price, qty=q, image_url=p.image_url)
                                          for p, q in lines)
        self.stdout.write(self.style.SUCCESS(f"สร้างคำสั่งซื้อตัวอย่าง {o['count']} รายการ"))
