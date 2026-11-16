import io
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from shop.models import Category, Order, OrderItem, Product
from shop.testing import SlipStorageMixin, image_file

User = get_user_model()


def png(size=(20, 20)):
    buf = io.BytesIO()
    Image.new('RGB', size, '#0b0b5c').save(buf, 'PNG')
    return SimpleUploadedFile('p.png', buf.getvalue(), content_type='image/png')


class Base(SlipStorageMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cat = Category.objects.create(name='หมวด', slug='cat')
        cls.p1 = Product.objects.create(category=cls.cat, name='สินค้า A', slug='a', price=Decimal('100'), stock=10)
        cls.p2 = Product.objects.create(category=cls.cat, name='สินค้า B', slug='b', price=Decimal('300'), stock=2)
        cls.root = User.objects.create_superuser('root@example.com', 'root@example.com', 'pw-Test-12345', first_name='Root')
        cls.staff = User.objects.create_user('staff@example.com', 'staff@example.com', 'pw-Test-12345', is_staff=True)
        cls.cust = User.objects.create_user('cust@example.com', 'cust@example.com', 'pw-Test-12345', first_name='ลูกค้า')

    def make_order(self, user=None, status='processing', total=Decimal('250'), days_ago=0, items=((1, 2),), payment='cod'):
        o = Order.objects.create(user=user or self.cust, payment_method=payment, status=status, full_name='ผู้รับ', phone='0812345678',
                                 address='=cmd|calc', province='กรุงเทพมหานคร', postal_code='10110',
                                 subtotal=total - Decimal('50'), shipping_fee=Decimal('50'), total=total)
        Order.objects.filter(pk=o.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
        for which, qty in items:
            p = self.p1 if which == 1 else self.p2
            OrderItem.objects.create(order=o, product=p, name=p.name, unit_price=p.price, qty=qty)
        o.refresh_from_db()
        return o


class AccessTests(Base):
    URLS = ['dashboard:home', 'dashboard:products', 'dashboard:product_new', 'dashboard:categories', 'dashboard:orders', 'dashboard:reports']

    def test_anonymous_redirected_to_login(self):
        for name in self.URLS + ['dashboard:users']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn(reverse('shop:login'), r.url)

    def test_customer_forbidden(self):
        self.client.force_login(self.cust)
        for name in self.URLS + ['dashboard:users']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)

    def test_staff_access_but_not_users(self):
        self.client.force_login(self.staff)
        for name in self.URLS:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get(reverse('dashboard:users')).status_code, 403)

    def test_inactive_staff_blocked(self):
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        self.client.force_login(self.staff)
        self.assertNotEqual(self.client.get(reverse('dashboard:home')).status_code, 200)

    def test_quick_endpoint_requires_post_and_staff(self):
        url = reverse('dashboard:product_quick', args=[self.p1.pk])
        self.client.force_login(self.cust)
        self.assertEqual(self.client.post(url, {'stock': 1}).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 405)


class ProductTests(Base):
    def setUp(self):
        self.client.force_login(self.staff)

    def data(self, **kw):
        d = {'name': 'โลชั่น ใหม่', 'category': self.cat.pk, 'brand': 'X', 'size': '100 มล.', 'description': 'd', 'price': '199',
             'compare_price': '', 'stock': '5', 'is_active': 'on', 'slug': ''}
        d.update(kw)
        return d

    def test_create_with_image_and_auto_slug(self):
        r = self.client.post(reverse('dashboard:product_new'), {**self.data(), 'image': png()})
        self.assertRedirects(r, reverse('dashboard:products'))
        p = Product.objects.get(name='โลชั่น ใหม่')
        self.assertTrue(p.slug)
        self.assertTrue(p.image.name.startswith('products/'))
        self.assertTrue(p.is_active and not p.is_new)
        self.assertEqual(self.client.get(f'/products/{p.slug}/').status_code, 200)  # live on the storefront
        p.image.delete(save=False)

    def test_slug_unique_suffix(self):
        for _ in range(2):
            self.client.post(reverse('dashboard:product_new'), self.data(name='ซ้ำ'))
        self.assertEqual(sorted(Product.objects.filter(name='ซ้ำ').values_list('slug', flat=True)), ['ซ้ำ', 'ซ้ำ-2'])

    def test_validation(self):
        r = self.client.post(reverse('dashboard:product_new'), self.data(price='0'))
        self.assertIn('price', r.context['form'].errors)
        r = self.client.post(reverse('dashboard:product_new'), self.data(price='100', compare_price='90'))
        self.assertIn('compare_price', r.context['form'].errors)
        r = self.client.post(reverse('dashboard:product_new'), self.data(stock='-1'))
        self.assertIn('stock', r.context['form'].errors)
        r = self.client.post(reverse('dashboard:product_new'), {**self.data(), 'image': SimpleUploadedFile('x.png', b'not an image', content_type='image/png')})
        self.assertIn('image', r.context['form'].errors)

    def test_edit(self):
        r = self.client.post(reverse('dashboard:product_edit', args=[self.p1.pk]), self.data(name='ชื่อใหม่', slug='a', price='150', compare_price='200', is_new='on'))
        self.assertRedirects(r, reverse('dashboard:products'))
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.name, self.p1.price, self.p1.discount_percent, self.p1.is_new), ('ชื่อใหม่', Decimal('150'), 25, True))

    def test_quick_update(self):
        url = reverse('dashboard:product_quick', args=[self.p1.pk])
        self.assertEqual(self.client.post(url, {'stock': '42'}).json()['stock'], 42)
        self.assertEqual(self.client.post(url, {'stock': '-3'}).status_code, 400)
        self.assertEqual(self.client.post(url, {'stock': 'abc'}).status_code, 400)
        self.client.post(url, {'is_active': '0'})
        self.p1.refresh_from_db()
        self.assertEqual((self.p1.stock, self.p1.is_active), (42, False))
        self.assertEqual(self.client.get('/products/a/').status_code, 404)  # hidden from the shop

    def test_delete_keeps_order_history(self):
        order = self.make_order()
        self.client.post(reverse('dashboard:product_delete', args=[self.p1.pk]))
        self.assertFalse(Product.objects.filter(pk=self.p1.pk).exists())
        self.assertEqual(order.items.get().name, 'สินค้า A')

    def test_list_filters(self):
        r = self.client.get(reverse('dashboard:products'), {'state': 'low'})
        self.assertEqual([p.pk for p in r.context['page']], [self.p2.pk])
        r = self.client.get(reverse('dashboard:products'), {'q': 'สินค้า A'})
        self.assertEqual([p.pk for p in r.context['page']], [self.p1.pk])


class CategoryTests(Base):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_crud_and_protected_delete(self):
        self.client.post(reverse('dashboard:category_new'), {'name': 'ใหม่', 'slug': '', 'order': 5})
        c = Category.objects.get(name='ใหม่')
        self.client.post(reverse('dashboard:category_edit', args=[c.pk]), {'name': 'ชื่อแก้', 'slug': c.slug, 'order': 1})
        c.refresh_from_db()
        self.assertEqual(c.name, 'ชื่อแก้')
        self.client.post(reverse('dashboard:category_delete', args=[self.cat.pk]))  # has products
        self.assertTrue(Category.objects.filter(pk=self.cat.pk).exists())
        self.client.post(reverse('dashboard:category_delete', args=[c.pk]))
        self.assertFalse(Category.objects.filter(pk=c.pk).exists())


class OrderTests(Base):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_status_change_and_cancel_restock(self):
        o = self.make_order()
        url = reverse('dashboard:order_detail', args=[o.number])
        r = self.client.post(url, {'status': 'shipped'})  # no carrier/tracking -> rejected
        self.assertIn('carrier', r.context['form'].errors)
        self.assertIn('tracking_number', r.context['form'].errors)
        o.refresh_from_db()
        self.assertEqual(o.status, 'processing')
        r = self.client.post(url, {'status': 'shipped', 'carrier': 'kerry', 'tracking_number': 'bad id!'})
        self.assertIn('tracking_number', r.context['form'].errors)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(url, {'status': 'shipped', 'carrier': 'kerry', 'tracking_number': 'th9988776655'})
        o.refresh_from_db()
        self.assertEqual((o.status, o.carrier, o.tracking_number), ('shipped', 'kerry', 'TH9988776655'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['cust@example.com'])
        self.client.post(url, {'status': 'cancelled'})
        self.p1.refresh_from_db()
        self.assertEqual(self.p1.stock, 12)
        self.client.post(url, {'status': 'processing'})  # final
        o.refresh_from_db()
        self.assertEqual(o.status, 'cancelled')

    def test_filters(self):
        a = self.make_order(status='completed')
        b = self.make_order(status='pending_payment', days_ago=10)
        r = self.client.get(reverse('dashboard:orders'), {'status': 'pending_payment'})
        self.assertEqual([o.pk for o in r.context['page']], [b.pk])
        d = (timezone.localdate() - timedelta(days=3)).isoformat()
        r = self.client.get(reverse('dashboard:orders'), {'from': d})
        self.assertEqual([o.pk for o in r.context['page']], [a.pk])
        r = self.client.get(reverse('dashboard:orders'), {'q': a.number})
        self.assertEqual([o.pk for o in r.context['page']], [a.pk])

    def test_csv_export_is_excel_safe(self):
        self.make_order()
        r = self.client.get(reverse('dashboard:orders'), {'export': 'csv'})
        self.assertEqual(r['Content-Type'], 'text/csv; charset=utf-8')
        body = r.content.decode('utf-8')
        self.assertTrue(body.startswith('﻿'))
        self.assertIn("'=cmd|calc", body)  # formula injection neutralised


class UserTests(Base):
    def setUp(self):
        self.client.force_login(self.root)

    def form(self, **kw):
        d = {'full_name': 'คนใหม่', 'email': 'New@Example.com', 'role': 'staff', 'is_active': 'on', 'password1': 'Strong-pass-987', 'password2': 'Strong-pass-987'}
        d.update(kw)
        return d

    def test_create_staff(self):
        self.client.post(reverse('dashboard:user_new'), self.form())
        u = User.objects.get(username='new@example.com')
        self.assertTrue(u.is_staff and not u.is_superuser and u.check_password('Strong-pass-987'))

    def test_duplicate_email_and_weak_password(self):
        r = self.client.post(reverse('dashboard:user_new'), self.form(email='CUST@example.com'))
        self.assertIn('email', r.context['form'].errors)
        r = self.client.post(reverse('dashboard:user_new'), self.form(password1='12345678', password2='12345678'))
        self.assertIn('password1', r.context['form'].errors)

    def test_cannot_demote_or_deactivate_self(self):
        self.client.post(reverse('dashboard:user_edit', args=[self.root.pk]), {'full_name': 'Root2', 'email': 'root@example.com', 'role': 'customer'})
        self.root.refresh_from_db()
        self.assertTrue(self.root.is_superuser and self.root.is_active)
        self.assertEqual(self.root.first_name, 'Root2')

    def test_deactivated_user_cannot_login(self):
        self.client.post(reverse('dashboard:user_edit', args=[self.cust.pk]), {'full_name': 'x', 'email': 'cust@example.com', 'role': 'customer'})
        self.client.logout()
        r = self.client.post(reverse('shop:login'), {'username': 'cust@example.com', 'password': 'pw-Test-12345'})
        self.assertEqual(r.status_code, 200)

    def test_set_password(self):
        self.client.post(reverse('dashboard:user_password', args=[self.cust.pk]), {'password1': 'Another-pass-5521', 'password2': 'Another-pass-5521'})
        self.cust.refresh_from_db()
        self.assertTrue(self.cust.check_password('Another-pass-5521'))

    def test_delete_rules(self):
        self.make_order()
        self.client.post(reverse('dashboard:user_delete', args=[self.cust.pk]))
        self.assertTrue(User.objects.filter(pk=self.cust.pk).exists())  # has orders
        self.client.post(reverse('dashboard:user_delete', args=[self.root.pk]))
        self.assertTrue(User.objects.filter(pk=self.root.pk).exists())  # self
        self.client.post(reverse('dashboard:user_delete', args=[self.staff.pk]))
        self.assertFalse(User.objects.filter(pk=self.staff.pk).exists())


class ReportTests(Base):
    def setUp(self):
        self.client.force_login(self.staff)
        self.make_order(status='completed', total=Decimal('250'), items=((1, 2),))
        self.make_order(status='processing', total=Decimal('650'), items=((2, 2),), days_ago=1)
        self.make_order(status='cancelled', total=Decimal('9999'), items=((1, 9),))
        self.make_order(status='shipped', total=Decimal('1000'), days_ago=400, items=((1, 1),))

    def test_cancelled_excluded_from_sales(self):
        d = {'from': (timezone.localdate() - timedelta(days=30)).isoformat(), 'to': timezone.localdate().isoformat()}
        r = self.client.get(reverse('dashboard:reports'), d)
        self.assertEqual(r.context['summary']['revenue'], Decimal('900'))
        self.assertEqual(r.context['summary']['orders'], 2)
        self.assertEqual(r.context['summary']['aov'], Decimal('450'))
        self.assertEqual([(p['name'], p['qty']) for p in r.context['products']], [('สินค้า B', 2), ('สินค้า A', 2)])
        self.assertEqual(len(r.context['series']), 31)
        statuses = {s['status'] for s in r.context['statuses']}
        self.assertIn('cancelled', statuses)

    def test_monthly_grouping_and_range_swap(self):
        r = self.client.get(reverse('dashboard:reports'), {'from': timezone.localdate().isoformat(), 'to': (timezone.localdate() - timedelta(days=500)).isoformat(), 'group': 'month'})
        self.assertEqual(r.context['group'], 'month')
        self.assertEqual(r.context['summary']['revenue'], Decimal('1900'))
        self.assertTrue(r.context['start'] < r.context['end'])

    def test_exports(self):
        d = {'from': (timezone.localdate() - timedelta(days=30)).isoformat(), 'to': timezone.localdate().isoformat()}
        for kind in ('periods', 'products', 'orders'):
            r = self.client.get(reverse('dashboard:reports'), {**d, 'export': kind})
            self.assertEqual(r.status_code, 200, kind)
            self.assertIn('attachment', r['Content-Disposition'])

    def test_bad_dates_fall_back(self):
        self.assertEqual(self.client.get(reverse('dashboard:reports'), {'from': 'garbage', 'to': '2026-13-45'}).status_code, 200)

    def test_dashboard_numbers(self):
        r = self.client.get(reverse('dashboard:home'))
        self.assertEqual(r.context['month']['revenue'], Decimal('900'))
        self.assertEqual(r.context['to_process'], 1)
        self.assertEqual(r.context['low_stock_count'], 1)  # product B has stock 2


class PaymentAndShippingFlowTests(Base):
    def setUp(self):
        self.client.force_login(self.staff)

    def test_confirm_payment_emails_customer(self):
        o = self.make_order(status='pending_payment', payment='transfer')
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(reverse('dashboard:order_confirm_payment', args=[o.number]))
        self.assertRedirects(r, reverse('dashboard:order_detail', args=[o.number]))
        o.refresh_from_db()
        self.assertEqual(o.status, 'processing')
        self.assertIsNotNone(o.paid_at)
        self.assertEqual([m.to for m in mail.outbox], [['cust@example.com']])
        self.assertEqual(self.client.get(reverse('dashboard:order_confirm_payment', args=[o.number])).status_code, 405)

    def test_confirm_payment_only_for_pending(self):
        o = self.make_order(status='shipped')
        self.client.post(reverse('dashboard:order_confirm_payment', args=[o.number]))
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_shipping_email(self):
        o = self.make_order(status='processing')
        self.client.post(reverse('dashboard:order_resend_shipping', args=[o.number]))
        self.assertEqual(len(mail.outbox), 0)  # not shipped yet
        Order.objects.filter(pk=o.pk).update(status='shipped', carrier='flash', tracking_number='FL0000009')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('dashboard:order_resend_shipping', args=[o.number]))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('FL0000009', mail.outbox[0].body)

    def test_customers_cannot_use_new_endpoints(self):
        o = self.make_order(status='pending_payment')
        self.client.force_login(self.cust)
        for name in ('dashboard:order_confirm_payment', 'dashboard:order_resend_shipping'):
            self.assertEqual(self.client.post(reverse(name, args=[o.number])).status_code, 403)

    def test_badges_and_slip_visible_to_staff(self):
        o = self.make_order(status='pending_payment', payment='transfer')
        from shop.services import attach_slip
        attach_slip(o, image_file())
        self.make_order(status='processing')
        r = self.client.get(reverse('dashboard:home'))
        self.assertEqual(r.context['badge_orders'], 2)
        self.assertEqual(r.context['slips_waiting'], 1)
        detail = self.client.get(reverse('dashboard:order_detail', args=[o.number]))
        self.assertContains(detail, '/slip/')
        self.assertEqual(self.client.get(reverse('shop:order_slip', args=[o.number])).status_code, 200)
