from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from . import notify
from .models import Order, OrderItem, Product


class StockError(Exception):
    def __init__(self, names):
        self.names = names
        super().__init__(', '.join(names))


@transaction.atomic
def place_order(user, cart, data):
    """Create an order from the session cart.

    Rows are locked with SELECT ... FOR UPDATE (ordered by pk to avoid deadlocks) so two buyers
    can never both take the last item. Raises StockError if anything is no longer available.
    """
    wanted = {int(pk): qty for pk, qty in cart.data.items() if qty > 0}
    products = {p.pk: p for p in Product.objects.select_for_update().filter(pk__in=wanted, is_active=True).order_by('pk')}

    problems = []
    for pk, qty in wanted.items():
        p = products.get(pk)
        if p is None:
            problems.append('สินค้าที่ไม่พร้อมจำหน่าย')
        elif p.stock < qty:
            problems.append(p.name)
    if problems:
        raise StockError(problems)
    if not wanted:
        raise StockError([])

    subtotal = sum((products[pk].price * qty for pk, qty in wanted.items()), Decimal('0'))
    shipping = Decimal('0') if subtotal >= settings.FREE_SHIPPING_THRESHOLD else Decimal(settings.SHIPPING_FEE)
    method = data['payment_method']
    order = Order.objects.create(
        user=user,
        status=Order.Status.PENDING_PAYMENT if method == Order.Payment.TRANSFER else Order.Status.PROCESSING,
        payment_method=method,
        full_name=data['full_name'], phone=data['phone'], address=data['address'],
        province=data['province'], postal_code=data['postal_code'], note=data.get('note', ''),
        subtotal=subtotal, shipping_fee=shipping, total=subtotal + shipping,
    )
    for pk, qty in wanted.items():
        p = products[pk]
        OrderItem.objects.create(order=order, product=p, name=p.name, size=p.size, unit_price=p.price, qty=qty, image_url=p.image_url)
        p.stock -= qty
        p.save(update_fields=['stock'])
    notify.order_placed(order)
    return order


class InvalidTransition(Exception):
    pass


@transaction.atomic
def change_order_status(order, new_status, carrier='', tracking_number=''):
    """Move an order to a new status and send the matching emails.

    - shipped needs a carrier and tracking number; the customer is emailed automatically
    - re-saving a shipped order with a different tracking number updates it and emails the customer again
    - cancelling returns the items to stock; a cancelled order is final
    """
    S = Order.Status
    order = Order.objects.select_for_update().get(pk=order.pk)
    tracking_number = tracking_number.strip().upper()

    if order.status == S.CANCELLED and new_status != S.CANCELLED:
        raise InvalidTransition('คำสั่งซื้อที่ยกเลิกแล้วไม่สามารถเปลี่ยนสถานะได้')
    if new_status == S.SHIPPED and not (carrier and tracking_number):
        raise InvalidTransition('กรุณาเลือกขนส่งและกรอกเลขพัสดุก่อนบันทึกสถานะ "จัดส่งแล้ว"')

    if new_status == order.status:
        if new_status == S.SHIPPED and (carrier, tracking_number) != (order.carrier, order.tracking_number):
            order.carrier, order.tracking_number = carrier, tracking_number
            order.save(update_fields=['carrier', 'tracking_number'])
            notify.shipped(order, updated=True)
        return order

    old = order.status
    now = timezone.now()
    if new_status == S.CANCELLED:
        for item in order.items.exclude(product=None).select_related('product'):
            Product.objects.filter(pk=item.product_id).update(stock=F('stock') + item.qty)
    if new_status in (S.PROCESSING, S.SHIPPED, S.COMPLETED) and order.paid_at is None and not (
            order.payment_method == Order.Payment.COD and new_status != S.COMPLETED):
        order.paid_at = now
    if new_status == S.SHIPPED:
        order.carrier, order.tracking_number = carrier, tracking_number
        order.shipped_at = order.shipped_at or now

    order.status = new_status
    order.save()

    if new_status == S.PROCESSING and old == S.PENDING_PAYMENT:
        notify.payment_confirmed(order)
    elif new_status == S.SHIPPED:
        notify.shipped(order)
    elif new_status == S.CANCELLED:
        notify.cancelled(order)
    return order


class SlipNotAllowed(Exception):
    pass


@transaction.atomic
def attach_slip(order, image):
    """Customer uploads a transfer slip; only while the order is waiting for payment."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.payment_method != Order.Payment.TRANSFER or order.status != Order.Status.PENDING_PAYMENT:
        raise SlipNotAllowed('คำสั่งซื้อนี้ไม่สามารถแนบสลิปได้')
    old = order.payment_slip.name if order.payment_slip else None
    order.payment_slip = image
    order.slip_uploaded_at = timezone.now()
    order.save(update_fields=['payment_slip', 'slip_uploaded_at'])
    if old:
        order.payment_slip.storage.delete(old)
    notify.slip_uploaded(order)
    return order
