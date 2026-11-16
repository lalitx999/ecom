"""Sales queries shared by the dashboard and the reports page.

Definition used everywhere: sales = orders that are not cancelled (by order date, Asia/Bangkok).
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from shop.models import Order, OrderItem

ZERO = Decimal('0')
LINE_TOTAL = ExpressionWrapper(F('unit_price') * F('qty'), output_field=DecimalField(max_digits=14, decimal_places=2))


def bounds(start, end):
    """Inclusive dates -> aware [start, end + 1 day) datetimes."""
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start, time.min), tz),
            timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min), tz))


def orders_between(start, end):
    a, b = bounds(start, end)
    return Order.objects.filter(created_at__gte=a, created_at__lt=b)


def sales_between(start, end):
    return orders_between(start, end).exclude(status=Order.Status.CANCELLED)


def summarize(qs):
    agg = qs.aggregate(revenue=Sum('total'), goods=Sum('subtotal'), shipping=Sum('shipping_fee'), orders=Count('id'))
    revenue, orders = agg['revenue'] or ZERO, agg['orders'] or 0
    return {
        'revenue': revenue,
        'goods': agg['goods'] or ZERO,
        'shipping': agg['shipping'] or ZERO,
        'orders': orders,
        'aov': (revenue / orders).quantize(Decimal('1')) if orders else ZERO,
    }


def daily_series(start, end):
    rows = {r['d']: r for r in sales_between(start, end).annotate(d=TruncDate('created_at'))
            .values('d').annotate(revenue=Sum('total'), orders=Count('id'))}
    out, d = [], start
    while d <= end:
        r = rows.get(d)
        out.append({'label': d, 'revenue': r['revenue'] if r else ZERO, 'orders': r['orders'] if r else 0})
        d += timedelta(days=1)
    return out


def monthly_series(start, end):
    rows = {r['m'].date().replace(day=1): r for r in sales_between(start, end).annotate(m=TruncMonth('created_at'))
            .values('m').annotate(revenue=Sum('total'), orders=Count('id'))}
    out, d = [], start.replace(day=1)
    while d <= end:
        r = rows.get(d)
        out.append({'label': d, 'revenue': r['revenue'] if r else ZERO, 'orders': r['orders'] if r else 0})
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def with_bars(series):
    peak = max((r['revenue'] for r in series), default=ZERO)
    for r in series:
        r['pct'] = int(r['revenue'] / peak * 100) if peak else 0
    return series


def _items(qs):
    return OrderItem.objects.filter(order__in=qs.values('pk'))


def top_products(qs, limit=10):
    rows = (_items(qs).values('product_id', 'name').annotate(units=Sum('qty'), revenue=Sum(LINE_TOTAL))
            .order_by('-revenue', 'name')[:limit])
    return [{'product_id': r['product_id'], 'name': r['name'], 'qty': r['units'], 'revenue': r['revenue']} for r in rows]


def by_category(qs):
    rows = _items(qs).values('product__category__name').annotate(units=Sum('qty'), revenue=Sum(LINE_TOTAL)).order_by('-revenue')
    return [{'name': r['product__category__name'] or 'อื่น ๆ (สินค้าที่ถูกลบ)', 'qty': r['units'], 'revenue': r['revenue']} for r in rows]


def by_payment(qs):
    return list(qs.values('payment_method').annotate(orders=Count('id'), revenue=Sum('total')).order_by('-revenue'))


def by_status(start, end):
    return list(orders_between(start, end).values('status').annotate(orders=Count('id'), revenue=Sum('total')).order_by('status'))
