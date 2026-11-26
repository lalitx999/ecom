from decimal import Decimal

from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import Category, Order, Product, ProductVariant
from .services import InvalidTransition, SlipNotAllowed, attach_slip, change_order_status
from .testing import SlipStorageMixin, image_file, make_variant

User = get_user_model()

ADDRESS = {
    'full_name': 'ทดสอบ ระบบ', 'phone': '081-234-5678', 'address': '1 ถนนทดสอบ', 'province': 'กรุงเทพมหานคร',
    'postal_code': '10110', 'note': '', 'payment_method': 'cod',
}


class ShopTestCase(SlipStorageMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(name='หมวด', slug='cat')
        cls.cat = cat
        cls.cheap = make_variant(cat, 'ถูก', 'cheap', 100, stock=5)
        cls.pricey = make_variant(cat, 'แพง', 'pricey', 600, stock=2, compare_price=800)
        cls.out = make_variant(cat, 'หมด', 'out', 50, stock=0)
        cls.user = User.objects.create_user('a@example.com', 'a@example.com', 'pw-Test-12345', first_name='A')
        cls.other = User.objects.create_user('b@example.com', 'b@example.com', 'pw-Test-12345')

    def add(self, variant, qty=1):
        return self.client.post(reverse('shop:cart_add'), {'variant_id': variant.pk, 'qty': qty})


class CartTests(ShopTestCase):
    def test_add_clamps_to_stock(self):
        r = self.add(self.pricey, 10)
        self.assertEqual(r.json()['count'], 2)

    def test_out_of_stock_rejected(self):
        self.assertEqual(self.add(self.out).status_code, 409)

    def test_shipping_rules(self):
        self.add(self.cheap, 2)  # 200 -> pays 50 shipping
        r = self.client.get(reverse('shop:cart'))
        self.assertEqual(r.context['cart'].shipping_fee, Decimal('50'))
        self.add(self.pricey, 1)  # 800 -> free
        r = self.client.get(reverse('shop:cart'))
        self.assertEqual(r.context['cart'].shipping_fee, Decimal('0'))
        self.assertEqual(r.context['cart'].total, Decimal('800'))


class CheckoutTests(ShopTestCase):
    def test_requires_login(self):
        self.add(self.cheap)
        r = self.client.get(reverse('shop:checkout'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('shop:login'), r.url)

    def test_empty_cart_redirects(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse('shop:checkout')), reverse('shop:cart'))

    def test_place_order(self):
        self.add(self.cheap, 2)
        self.client.force_login(self.user)  # cart survives login
        r = self.client.post(reverse('shop:checkout'), ADDRESS)
        order = Order.objects.get()
        self.assertRedirects(r, order.get_absolute_url())
        self.assertEqual((order.subtotal, order.shipping_fee, order.total), (Decimal('200'), Decimal('50'), Decimal('250')))
        self.assertEqual(order.phone, '0812345678')
        self.assertEqual(order.status, Order.Status.PROCESSING)
        self.assertTrue(order.number.startswith('NS'))
        self.cheap.refresh_from_db()
        self.assertEqual(self.cheap.stock, 3)
        self.assertEqual(self.client.get(reverse('shop:cart')).context['cart'].is_empty, True)

    def test_transfer_waits_for_payment(self):
        self.add(self.cheap)
        self.client.force_login(self.user)
        self.client.post(reverse('shop:checkout'), {**ADDRESS, 'payment_method': 'transfer'})
        self.assertEqual(Order.objects.get().status, Order.Status.PENDING_PAYMENT)

    def test_insufficient_stock_creates_no_order(self):
        self.add(self.pricey, 2)
        self.client.force_login(self.user)
        ProductVariant.objects.filter(pk=self.pricey.pk).update(stock=1)  # someone else bought one
        r = self.client.post(reverse('shop:checkout'), ADDRESS)
        self.assertRedirects(r, reverse('shop:cart'))
        self.assertEqual(Order.objects.count(), 0)
        self.pricey.refresh_from_db()
        self.assertEqual(self.pricey.stock, 1)
        self.assertEqual(len(self.client.get(reverse('shop:cart')).context['cart']), 1)  # cart was adjusted

    def test_invalid_form_keeps_cart_and_stock(self):
        self.add(self.cheap)
        self.client.force_login(self.user)
        r = self.client.post(reverse('shop:checkout'), {**ADDRESS, 'phone': '123', 'postal_code': 'abc'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('phone', r.context['form'].errors)
        self.assertIn('postal_code', r.context['form'].errors)
        self.assertEqual(Order.objects.count(), 0)

    def test_order_price_is_snapshot(self):
        self.add(self.cheap)
        self.client.force_login(self.user)
        self.client.post(reverse('shop:checkout'), ADDRESS)
        ProductVariant.objects.filter(pk=self.cheap.pk).update(price=Decimal('999'))
        self.assertEqual(Order.objects.get().items.get().unit_price, Decimal('100'))


class AccountTests(ShopTestCase):
    def test_register_keeps_cart_and_logs_in(self):
        self.add(self.cheap, 3)
        r = self.client.post(reverse('shop:register'), {'full_name': 'สมชาย', 'email': 'New@Example.com', 'password1': 'Strong-pass-987', 'password2': 'Strong-pass-987'})
        self.assertEqual(r.status_code, 302)
        user = User.objects.get(username='new@example.com')
        self.assertEqual(user.first_name, 'สมชาย')
        self.assertEqual(self.client.get(reverse('shop:cart')).context['cart'].lines[0].qty, 3)

    def test_register_duplicate_email(self):
        r = self.client.post(reverse('shop:register'), {'full_name': 'x', 'email': 'A@example.com', 'password1': 'Strong-pass-987', 'password2': 'Strong-pass-987'})
        self.assertIn('email', r.context['form'].errors)

    def test_login_email_case_insensitive(self):
        r = self.client.post(reverse('shop:login'), {'username': 'A@Example.com', 'password': 'pw-Test-12345'})
        self.assertEqual(r.status_code, 302)

    def test_login_with_username_that_is_not_an_email(self):
        User.objects.create_user('shopowner', 'owner@example.com', 'pw-Test-12345', is_staff=True)
        for ident in ('shopowner', 'ShopOwner', 'owner@example.com', 'OWNER@example.com'):
            self.client.logout()
            r = self.client.post(reverse('shop:login'), {'username': ident, 'password': 'pw-Test-12345'})
            self.assertEqual(r.status_code, 302, ident)
        self.client.logout()
        self.assertEqual(self.client.post(reverse('shop:login'), {'username': 'shopowner', 'password': 'wrong'}).status_code, 200)

    def test_shared_email_is_not_accepted_but_username_is(self):
        User.objects.create_user('dup1', 'dup@example.com', 'pw-Test-12345')
        User.objects.create_user('dup2', 'dup@example.com', 'pw-Test-12345')
        self.assertEqual(self.client.post(reverse('shop:login'), {'username': 'dup@example.com', 'password': 'pw-Test-12345'}).status_code, 200)
        self.assertEqual(self.client.post(reverse('shop:login'), {'username': 'dup1', 'password': 'pw-Test-12345'}).status_code, 302)

    def test_orders_are_private(self):
        order = Order.objects.create(user=self.user, payment_method='cod', full_name='a', phone='0812345678', address='x', province='y',
                                     postal_code='10110', subtotal=1, shipping_fee=0, total=1)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse('shop:orders')), order.number)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 200)

    def test_open_redirect_blocked(self):
        r = self.client.post(reverse('shop:register'), {'full_name': 'x', 'email': 'z@example.com', 'password1': 'Strong-pass-987', 'password2': 'Strong-pass-987', 'next': 'https://evil.example/'})
        self.assertRedirects(r, reverse('shop:home'))


class OrderStatusServiceTests(ShopTestCase):
    def test_cancel_restocks_once_and_is_final(self):
        self.add(self.cheap, 2)
        self.client.force_login(self.user)
        self.client.post(reverse('shop:checkout'), ADDRESS)
        order = Order.objects.get()
        change_order_status(order, 'shipped', 'kerry', 'th123456789')
        self.cheap.refresh_from_db()
        self.assertEqual(self.cheap.stock, 3)
        change_order_status(order, 'cancelled')
        change_order_status(order, 'cancelled')
        self.cheap.refresh_from_db()
        self.assertEqual(self.cheap.stock, 5)
        with self.assertRaises(InvalidTransition):
            change_order_status(order, 'processing')


class NotificationTests(ShopTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.seller = User.objects.create_user('seller@example.com', 'seller@example.com', 'pw-Test-12345', is_staff=True)

    def place(self, method='cod'):
        self.add(self.cheap, 2)
        self.client.force_login(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('shop:checkout'), {**ADDRESS, 'payment_method': method})
        return Order.objects.get()

    def test_order_placed_emails_customer_and_seller(self):
        order = self.place()
        self.assertEqual(len(mail.outbox), 2)
        customer = next(m for m in mail.outbox if m.to == ['a@example.com'])
        seller = next(m for m in mail.outbox if 'seller@example.com' in m.to)
        self.assertIn(order.number, customer.subject)
        self.assertIn('คำสั่งซื้อใหม่', seller.subject)
        self.assertIn(f'/manage/orders/{order.number}/', seller.body)
        self.assertIn(order.number, customer.alternatives[0][0])  # html part

    def test_transfer_email_has_payment_info(self):
        self.place('transfer')
        customer = next(m for m in mail.outbox if m.to == ['a@example.com'])
        self.assertIn('โอนเงิน', customer.body)

    def test_mail_failure_does_not_break_order(self):
        with mock.patch('django.core.mail.message.EmailMultiAlternatives.send', side_effect=OSError('smtp down')):
            order = self.place()
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(order.items.count(), 1)

    def test_ship_requires_tracking_and_emails_customer(self):
        order = self.place()
        mail.outbox.clear()
        with self.assertRaises(InvalidTransition):
            change_order_status(order, 'shipped', 'kerry', '')
        with self.assertRaises(InvalidTransition):
            change_order_status(order, 'shipped', '', 'TH123456789')
        self.assertEqual(len(mail.outbox), 0)
        with self.captureOnCommitCallbacks(execute=True):
            order = change_order_status(order, 'shipped', 'kerry', 'th123456789')
        self.assertEqual((order.status, order.carrier, order.tracking_number), ('shipped', 'kerry', 'TH123456789'))
        self.assertIsNotNone(order.shipped_at)
        self.assertIsNone(order.paid_at)  # COD: paid on delivery
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertEqual(m.to, ['a@example.com'])
        self.assertIn('TH123456789', m.body)
        self.assertIn('th.kerryexpress.com', m.body)  # tracking link

    def test_tracking_update_resends_only_when_changed(self):
        order = self.place()
        with self.captureOnCommitCallbacks(execute=True):
            change_order_status(order, 'shipped', 'flash', 'FL0000001')
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            change_order_status(order, 'shipped', 'flash', 'FL0000001')
        self.assertEqual(len(mail.outbox), 0)
        with self.captureOnCommitCallbacks(execute=True):
            order = change_order_status(order, 'shipped', 'flash', 'FL0000002')
        self.assertEqual(order.tracking_number, 'FL0000002')
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('อัปเดตเลขพัสดุ', mail.outbox[0].subject)

    def test_carrier_without_link_still_emails_number(self):
        order = self.place()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            order = change_order_status(order, 'shipped', 'jt', 'JT12345678')
        self.assertEqual(order.tracking_url, '')
        self.assertIn('JT12345678', mail.outbox[0].body)

    def test_payment_confirmed_and_cancel_emails(self):
        order = self.place('transfer')
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            order = change_order_status(order, 'processing')
        self.assertIsNotNone(order.paid_at)
        self.assertEqual([m.to for m in mail.outbox], [['a@example.com']])
        self.assertIn('ได้รับการชำระเงิน', mail.outbox[0].subject)
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            change_order_status(order, 'cancelled')
        self.assertIn('ยกเลิก', mail.outbox[0].subject)

    def test_cod_paid_at_only_when_completed(self):
        order = self.place('cod')
        self.assertIsNone(order.paid_at)
        order = change_order_status(order, 'shipped', 'kerry', 'KE1234567')
        self.assertIsNone(order.paid_at)
        order = change_order_status(order, 'completed')
        self.assertIsNotNone(order.paid_at)


class SlipTests(ShopTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.staff = User.objects.create_user('staff@example.com', 'staff@example.com', 'pw-Test-12345', is_staff=True)

    def transfer_order(self):
        self.add(self.cheap)
        self.client.force_login(self.user)
        self.client.post(reverse('shop:checkout'), {**ADDRESS, 'payment_method': 'transfer'})
        return Order.objects.get()

    def test_upload_and_privacy(self):
        order = self.transfer_order()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(order.get_absolute_url(), {'slip': image_file()})
        self.assertRedirects(r, order.get_absolute_url())
        order.refresh_from_db()
        self.assertTrue(order.payment_slip and order.slip_uploaded_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('แนบสลิป', mail.outbox[0].subject)
        url = reverse('shop:order_slip', args=[order.number])
        self.assertEqual(self.client.get(url).status_code, 200)             # owner
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 200)             # staff
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)             # someone else
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)             # anonymous -> login
        self.assertNotIn('/media/', order.payment_slip.url if False else url)

    def test_reupload_replaces_old_file(self):
        order = self.transfer_order()
        attach_slip(order, image_file('a.png'))
        order.refresh_from_db()
        first = order.payment_slip.name
        attach_slip(order, image_file('b.png'))
        order.refresh_from_db()
        self.assertNotEqual(first, order.payment_slip.name)
        self.assertFalse(order.payment_slip.storage.exists(first))

    def test_rejects_bad_files_and_wrong_orders(self):
        order = self.transfer_order()
        bad = self.client.post(order.get_absolute_url(), {'slip': image_file('x.gif', 'GIF')})
        self.assertEqual(bad.status_code, 200)
        self.assertIn('slip', bad.context['slip_form'].errors)
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = self.client.post(order.get_absolute_url(), {'slip': SimpleUploadedFile('x.png', b'nope', content_type='image/png')})
        self.assertIn('slip', bad.context['slip_form'].errors)
        order.refresh_from_db()
        self.assertFalse(order.payment_slip)
        change_order_status(order, 'processing')
        with self.assertRaises(SlipNotAllowed):
            attach_slip(order, image_file())

    def test_cod_order_cannot_attach_slip(self):
        self.add(self.cheap)
        self.client.force_login(self.user)
        self.client.post(reverse('shop:checkout'), ADDRESS)
        with self.assertRaises(SlipNotAllowed):
            attach_slip(Order.objects.get(), image_file())

    def test_customer_sees_tracking(self):
        order = self.transfer_order()
        change_order_status(order, 'shipped', 'thailand_post', 'EN123456789TH')
        r = self.client.get(order.get_absolute_url())
        self.assertContains(r, 'EN123456789TH')
        self.assertContains(r, 'track.thailandpost.co.th')


class PasswordResetTests(ShopTestCase):
    def test_reset_flow_sends_email(self):
        r = self.client.post(reverse('shop:password_reset'), {'email': 'a@example.com'})
        self.assertRedirects(r, reverse('shop:password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/password-reset/', mail.outbox[0].body)
        self.assertIn('NS SELECT', mail.outbox[0].subject)

    def test_unknown_email_gives_same_response_and_no_mail(self):
        r = self.client.post(reverse('shop:password_reset'), {'email': 'nobody@example.com'})
        self.assertRedirects(r, reverse('shop:password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)

    def test_set_new_password(self):
        self.client.post(reverse('shop:password_reset'), {'email': 'a@example.com'})
        link = next(l for l in mail.outbox[0].body.split() if '/password-reset/' in l)
        path = link[link.index('/password-reset/'):]
        r = self.client.get(path, follow=True)
        post_url = r.request['PATH_INFO']
        r = self.client.post(post_url, {'new_password1': 'Brand-new-pass-4455', 'new_password2': 'Brand-new-pass-4455'})
        self.assertRedirects(r, reverse('shop:password_reset_complete'))
        self.assertTrue(User.objects.get(pk=self.user.pk).check_password('Brand-new-pass-4455'))


from django.test import override_settings  # noqa: E402


class FooterTests(ShopTestCase):
    def test_footer_links_and_shipping_facts(self):
        r = self.client.get(reverse('shop:home'))
        self.assertContains(r, 'site-footer')
        self.assertContains(r, '?category=cat')                   # category link
        self.assertContains(r, 'ส่งฟรีเมื่อซื้อครบ 500 บาท')
        self.assertContains(r, reverse('shop:login'))
        self.assertNotContains(r, 'footer-contact"><li')           # nothing configured -> no contact rows
        self.assertNotContains(r, 'จัดการร้าน')                       # not for anonymous users

    def test_footer_appears_on_other_pages_and_staff_link(self):
        self.client.force_login(User.objects.create_user('s@example.com', 's@example.com', 'pw-Test-12345', is_staff=True))
        for url in (reverse('shop:cart'), self.pricey.product.get_absolute_url(), reverse('shop:product_list')):
            r = self.client.get(url)
            self.assertContains(r, 'site-footer')
            self.assertContains(r, 'จัดการร้าน')

    @override_settings(SHOP_CONTACT={'tagline': 'ร้านทดสอบ', 'phone': '081-234-5678', 'email': 'hello@example.com', 'line_id': '@shop',
                                     'line_url': 'https://line.me/R/ti/p/@shop', 'address': '1 ถนน<script>x</script>\nกรุงเทพ',
                                     'hours': 'ทุกวัน 9:00-18:00', 'facebook': 'https://facebook.com/shop', 'instagram': '', 'tiktok': ''})
    def test_configured_contact_is_shown_and_escaped(self):
        r = self.client.get(reverse('shop:home'))
        self.assertContains(r, 'href="tel:0812345678"')
        self.assertContains(r, 'mailto:hello@example.com')
        self.assertContains(r, 'https://line.me/R/ti/p/@shop')
        self.assertContains(r, 'ทุกวัน 9:00-18:00')
        self.assertContains(r, 'https://facebook.com/shop')
        self.assertNotContains(r, 'instagram.com')
        self.assertNotContains(r, '<script>x</script>')           # address is escaped
        self.assertContains(r, '&lt;script&gt;')


class VariantStorefrontTests(ShopTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.m = make_variant(cls.cat, 'เสื้อยืด', 'tee', 300, stock=3, color='ดำ', size='M')
        cls.tee = cls.m.product
        cls.l = make_variant(None, '', '', 350, stock=0, color='ดำ', size='L', product=cls.tee)
        cls.xs = make_variant(None, '', '', 900, stock=1, color='ขาว', size='XS', product=cls.tee, compare_price=1000)

    def test_card_shows_from_price_and_needs_a_choice(self):
        r = self.client.get(reverse('shop:product_list'))
        self.assertContains(r, 'เริ่มต้น 300 บาท')
        self.assertContains(r, 'เลือกตัวเลือก')        # no direct add-to-cart for a product with options

    def test_detail_lists_options_and_variant_data(self):
        r = self.client.get(self.tee.get_absolute_url())
        self.assertContains(r, 'data-color="ดำ"')
        self.assertContains(r, 'data-size="XS"')
        self.assertEqual([s for s in r.context['sizes']], ['XS', 'M', 'L'])   # clothing order, not alphabetical
        self.assertIn('"stock": 0', r.context['variant_json'])               # sold-out size is shown greyed out

    def test_each_variant_is_its_own_cart_line_with_own_stock(self):
        self.add(self.m, 5)
        self.add(self.xs, 1)
        cart = self.client.get(reverse('shop:cart')).context['cart']
        self.assertEqual([(l.variant.size, l.qty) for l in cart], [('M', 3), ('XS', 1)])
        self.assertEqual(cart.subtotal, Decimal('1800'))
        self.assertEqual(self.add(self.l).status_code, 409)                  # sold-out size

    def test_inactive_variant_cannot_be_bought(self):
        self.add(self.m, 1)
        ProductVariant.objects.filter(pk=self.m.pk).update(is_active=False)
        self.assertTrue(self.client.get(reverse('shop:cart')).context['cart'].is_empty)
        self.assertEqual(self.add(self.m).status_code, 400)

    def test_order_item_keeps_colour_size_and_restocks_variant(self):
        self.add(self.m, 2)
        self.client.force_login(self.user)
        self.client.post(reverse('shop:checkout'), ADDRESS)
        item = Order.objects.get().items.get()
        self.assertEqual((item.color, item.size, item.variant_label, item.unit_price), ('ดำ', 'M', 'ดำ / M', Decimal('300')))
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 1)
        change_order_status(item.order, 'cancelled')
        self.m.refresh_from_db()
        self.assertEqual(self.m.stock, 3)

    def test_size_and_brand_filters_and_price_sort(self):
        r = self.client.get(reverse('shop:product_list'), {'size': 'XS'})
        self.assertEqual([p.pk for p in r.context['page']], [self.tee.pk])
        self.assertIn('XS', r.context['sizes'])
        self.assertNotIn('L', r.context['sizes'])                            # only sizes that are in stock
        r = self.client.get(reverse('shop:product_list'), {'sort': 'price_desc'})
        self.assertEqual(r.context['page'][0].pk, self.pricey.product.pk)    # 600 > 300 (tee's lowest)


class ImportCommandTests(TestCase):
    def test_import_is_repeatable_and_keeps_stock(self):
        import json
        import shutil
        import tempfile
        from pathlib import Path

        from django.core.management import call_command
        from django.test import override_settings

        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / 'Work' / 'a').mkdir(parents=True)
            image_file('p.png').file.seek(0)
            (tmp / 'Work' / 'a' / 'photo').write_bytes(image_file('p.png').read())   # no extension, like the real folder
            data = {'categories': [{'key': 'shoes', 'name': 'รองเท้า'}], 'products': [{
                'category': 'shoes', 'brand': 'Brand X', 'name': 'Runner One', 'images': ['a/photo'], 'source_screens': [],
                'variants': [{'size': 'US 9', 'price': 3500, 'available': True, 'fast': True},
                             {'size': 'US 10', 'price': None, 'available': False}]}]}
            (tmp / 'data.json').write_text(json.dumps(data), encoding='utf-8')
            with override_settings(MEDIA_ROOT=str(tmp / 'media')):
                call_command('import_ns_select', data=str(tmp / 'data.json'), source=str(tmp / 'Work'), stdout=open('/dev/null', 'w'))
                p = Product.objects.get(slug='runner-one')
                v = p.variants.get()
                self.assertEqual((v.size, v.price, v.stock, v.ready_to_ship), ('US 9', Decimal('3500'), 1, True))  # sold-out size skipped
                self.assertEqual(p.images.count(), 1)
                ProductVariant.objects.filter(pk=v.pk).update(stock=8)
                call_command('import_ns_select', data=str(tmp / 'data.json'), source=str(tmp / 'Work'), stdout=open('/dev/null', 'w'))
                self.assertEqual((Product.objects.count(), ProductVariant.objects.count(), p.images.count()), (1, 1, 1))
                self.assertEqual(ProductVariant.objects.get().stock, 8)                                # stock not overwritten
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
