"""Transactional emails. Sent after the DB transaction commits; a mail failure is logged and never breaks an order."""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

from .templatetags.shop_extras import baht

logger = logging.getLogger('shop')


def _url(path):
    return settings.SITE_URL + path


def _send(to, subject, **ctx):
    to = [t for t in dict.fromkeys(to) if t]
    if not to:
        return
    ctx.update(site_name=settings.SITE_NAME, site_url=settings.SITE_URL)
    try:
        msg = EmailMultiAlternatives(f'[{settings.SITE_NAME}] {subject}', render_to_string('emails/message.txt', ctx),
                                     settings.DEFAULT_FROM_EMAIL, to)
        msg.attach_alternative(render_to_string('emails/message.html', ctx), 'text/html')
        msg.send()
    except Exception:
        logger.exception('Could not send email %r to %s', subject, to)


def _seller_recipients():
    User = get_user_model()
    staff = User.objects.filter(is_staff=True, is_active=True).exclude(email='').values_list('email', flat=True)
    return list(staff) + list(settings.SHOP_NOTIFY_EMAILS)


def _items(order):
    return [(i.name, i.qty, baht(i.line_total)) for i in order.items.all()]


def _totals(order):
    return [('ราคาสินค้า', baht(order.subtotal) + ' บาท'),
            ('ค่าจัดส่ง', (baht(order.shipping_fee) + ' บาท') if order.shipping_fee else 'ฟรี'),
            ('ยอดรวม', baht(order.total) + ' บาท')]


def _later(fn, *args):
    transaction.on_commit(lambda: fn(*args))


# ------------------------------------------------------------------ public API
def order_placed(order):
    _later(_order_placed, order)


def _order_placed(order):
    customer_note = []
    if order.payment_method == order.Payment.TRANSFER:
        customer_note = [f'กรุณาโอนเงิน {baht(order.total)} บาท แล้วแนบสลิปที่หน้าคำสั่งซื้อ',
                         settings.PAYMENT_TRANSFER_INFO]
    _send([order.user.email], f'ยืนยันคำสั่งซื้อ {order.number}',
          heading='ขอบคุณที่สั่งซื้อ', intro=[f'เราได้รับคำสั่งซื้อเลขที่ {order.number} ของคุณเรียบร้อยแล้ว'] + customer_note,
          items=_items(order), rows=_totals(order) + [('วิธีชำระเงิน', order.get_payment_method_display())],
          address=f'{order.full_name} {order.phone}\n{order.address}\n{order.province} {order.postal_code}',
          button=('ดูคำสั่งซื้อ' if order.payment_method == order.Payment.COD else 'แนบสลิปและดูคำสั่งซื้อ', _url(order.get_absolute_url())))
    _send(_seller_recipients(), f'คำสั่งซื้อใหม่ {order.number} ({baht(order.total)} บาท)',
          heading='มีคำสั่งซื้อใหม่', intro=[f'{order.full_name} สั่งซื้อ {len(order.items.all())} รายการ ชำระโดย {order.get_payment_method_display()}'
                                            + (' (รอสลิปโอนเงิน)' if order.payment_method == order.Payment.TRANSFER else ' (พร้อมจัดส่ง)')],
          items=_items(order), rows=_totals(order),
          address=f'{order.full_name} {order.phone}\n{order.address}\n{order.province} {order.postal_code}',
          button=('เปิดในระบบจัดการ', _url(reverse('dashboard:order_detail', args=[order.number]))))


def slip_uploaded(order):
    _later(lambda o: _send(_seller_recipients(), f'ลูกค้าแนบสลิป {o.number}', heading='ลูกค้าแนบสลิปโอนเงิน',
                           intro=[f'{o.full_name} แนบสลิปสำหรับคำสั่งซื้อ {o.number} ยอด {baht(o.total)} บาท กรุณาตรวจสอบและยืนยันการชำระเงิน'],
                           button=('ตรวจสอบสลิป', _url(reverse('dashboard:order_detail', args=[o.number])))), order)


def payment_confirmed(order):
    _later(lambda o: _send([o.user.email], f'ได้รับการชำระเงินแล้ว {o.number}', heading='ได้รับการชำระเงินแล้ว',
                           intro=[f'เราได้รับการชำระเงินสำหรับคำสั่งซื้อ {o.number} แล้ว กำลังเตรียมสินค้าเพื่อจัดส่ง'],
                           rows=_totals(o), button=('ดูคำสั่งซื้อ', _url(o.get_absolute_url()))), order)


def shipped(order, updated=False):
    _later(_shipped, order, updated)


def _shipped(order, updated):
    rows = [('ขนส่ง', order.get_carrier_display()), ('เลขพัสดุ', order.tracking_number)]
    button = ('ติดตามพัสดุ', order.tracking_url) if order.tracking_url else ('ดูคำสั่งซื้อ', _url(order.get_absolute_url()))
    _send([order.user.email], f'{"อัปเดตเลขพัสดุ" if updated else "จัดส่งสินค้าแล้ว"} {order.number}',
          heading='อัปเดตเลขพัสดุ' if updated else 'จัดส่งสินค้าแล้ว',
          intro=[f'คำสั่งซื้อ {order.number} ' + ('มีการอัปเดตข้อมูลการจัดส่ง' if updated else 'ถูกส่งออกจากร้านแล้ว') + ' คุณสามารถใช้เลขพัสดุด้านล่างติดตามสถานะได้'],
          items=_items(order), rows=rows, button=button,
          address=f'{order.full_name} {order.phone}\n{order.address}\n{order.province} {order.postal_code}')


def cancelled(order):
    _later(lambda o: _send([o.user.email], f'ยกเลิกคำสั่งซื้อ {o.number}', heading='คำสั่งซื้อถูกยกเลิก',
                           intro=[f'คำสั่งซื้อ {o.number} ถูกยกเลิกแล้ว หากมีข้อสงสัยหรือชำระเงินไปแล้ว กรุณาติดต่อร้านค้า'],
                           button=('ดูคำสั่งซื้อ', _url(o.get_absolute_url()))), order)
