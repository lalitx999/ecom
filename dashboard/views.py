import csv
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Min, ProtectedError, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from shop.models import Brand, Category, Order, Product, ProductVariant
from shop import notify
from shop.services import InvalidTransition, change_order_status

from . import reports
from .forms import CategoryForm, ImageFormSet, OrderStatusForm, ProductForm, SetPasswordForm, UserForm, VariantFormSet
from .permissions import staff_required, superuser_required

User = get_user_model()
LOW_STOCK = 5
PER_PAGE = 20


def paginate(request, qs, per_page=PER_PAGE):
    page = Paginator(qs, per_page).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return page, params.urlencode()


def csv_response(filename, header, rows):
    """UTF-8 with BOM so Excel opens Thai text correctly. Cells that could be read as formulas are neutralised."""
    resp = HttpResponse(content_type='text/csv; charset=utf-8')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    resp.write('﻿')
    w = csv.writer(resp)

    def safe(v):
        if isinstance(v, str) and v[:1] in ('=', '+', '-', '@', '\t', '\r'):
            return "'" + v
        return v
    w.writerow(header)
    for row in rows:
        w.writerow([safe(v) for v in row])
    return resp


def parse_date(value, default):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------ dashboard
@staff_required
def home(request):
    today = timezone.localdate()
    start = today - timedelta(days=29)
    prev_start, prev_end = start - timedelta(days=30), start - timedelta(days=1)

    cur = reports.summarize(reports.sales_between(start, today))
    prev = reports.summarize(reports.sales_between(prev_start, prev_end))
    delta = None
    if prev['revenue']:
        delta = int((cur['revenue'] - prev['revenue']) / prev['revenue'] * 100)

    return render(request, 'dashboard/home.html', {
        'today': reports.summarize(reports.sales_between(today, today)),
        'month': cur,
        'delta': delta,
        'to_process': Order.objects.filter(status=Order.Status.PROCESSING).count(),
        'pending_payment': Order.objects.filter(status=Order.Status.PENDING_PAYMENT).count(),
        'slips_waiting': Order.objects.filter(status=Order.Status.PENDING_PAYMENT).exclude(payment_slip='').count(),
        'low_stock_count': _low_variants().count(),
        'customers': User.objects.filter(is_staff=False).count(),
        'series': reports.with_bars(reports.daily_series(start, today)),
        'recent_orders': Order.objects.select_related('user')[:8],
        'low_stock': _low_variants().select_related('product').order_by('stock', 'product__name')[:8],
        'top_products': reports.top_products(reports.sales_between(start, today), 5),
        'range_start': start, 'range_end': today, 'LOW_STOCK': LOW_STOCK,
    })


# ------------------------------------------------------------ products
def _low_variants():
    return ProductVariant.objects.filter(is_active=True, product__is_active=True, stock__lte=LOW_STOCK)


@staff_required
def product_list(request):
    active = Q(variants__is_active=True)
    qs = (Product.objects.select_related('category', 'brand').prefetch_related('images')
          .annotate(stock_sum=Sum('variants__stock', filter=active), price_min=Min('variants__price', filter=active),
                    price_max=Max('variants__price', filter=active), variant_count=Count('variants', filter=active),
                    low_count=Count('variants', filter=active & Q(variants__stock__lte=LOW_STOCK))))
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(brand__name__icontains=q) | Q(variants__sku__icontains=q)).distinct()
    cat = request.GET.get('category', '')
    if cat.isdigit():
        qs = qs.filter(category_id=int(cat))
    state = request.GET.get('state', '')
    qs = {
        'active': qs.filter(is_active=True),
        'inactive': qs.filter(is_active=False),
        'low': qs.filter(low_count__gt=0, stock_sum__gt=0),
        'out': qs.filter(Q(stock_sum=0) | Q(stock_sum__isnull=True)),
    }.get(state, qs)
    sort = request.GET.get('sort', 'new')
    qs = qs.order_by({'new': '-created_at', 'name': 'name', 'stock': 'stock_sum', 'price': '-price_max'}.get(sort, '-created_at'), 'name')
    page, qstr = paginate(request, qs)
    return render(request, 'dashboard/product_list.html', {
        'page': page, 'querystring': qstr, 'q': q, 'cat': cat, 'state': state, 'sort': sort,
        'categories': Category.objects.all(), 'LOW_STOCK': LOW_STOCK,
    })


@staff_required
def product_form(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else Product()
    data, files = (request.POST, request.FILES) if request.method == 'POST' else (None, None)
    form = ProductForm(data, files, instance=product)
    variants = VariantFormSet(data, instance=product, prefix='variants')
    images = ImageFormSet(data, files, instance=product, prefix='images')
    if request.method == 'POST' and form.is_valid() and variants.is_valid() and images.is_valid():
        with transaction.atomic():
            saved = form.save()
            variants.instance = images.instance = saved
            variants.save()
            images.save()
        messages.success(request, f'บันทึกสินค้า "{saved.name}" แล้ว')
        return redirect('dashboard:product_edit', pk=saved.pk) if '_continue' in request.POST else redirect('dashboard:products')
    return render(request, 'dashboard/product_form.html', {
        'form': form, 'variants': variants, 'images': images, 'product': product if product.pk else None,
        'brands': Brand.objects.values_list('name', flat=True),
    })


@staff_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        name = product.name
        product.delete()
        messages.success(request, f'ลบสินค้า "{name}" แล้ว')
        return redirect('dashboard:products')
    return render(request, 'dashboard/confirm_delete.html', {
        'title': 'ลบสินค้า', 'object_name': product.name, 'back': 'dashboard:products',
        'warning': 'ประวัติคำสั่งซื้อเดิมจะยังอยู่ แต่สินค้านี้และตัวเลือกทั้งหมดจะหายจากร้านถาวร หากต้องการเพียงซ่อนสินค้า ให้ปิด "แสดงสินค้า" แทน',
    })


@staff_required
@require_POST
def product_quick(request, pk):
    """Ajax: toggle visibility straight from the product list."""
    product = get_object_or_404(Product, pk=pk)
    if 'is_active' in request.POST:
        product.is_active = request.POST['is_active'] == '1'
        product.save(update_fields=['is_active'])
    return JsonResponse({'ok': True, 'is_active': product.is_active, 'message': 'บันทึกแล้ว'})


@staff_required
@require_POST
def variant_quick(request, pk):
    """Ajax: update one variant's stock (low-stock table on the dashboard)."""
    variant = get_object_or_404(ProductVariant, pk=pk)
    try:
        stock = int(request.POST.get('stock', ''))
    except ValueError:
        stock = -1
    if not 0 <= stock <= 1_000_000:
        return JsonResponse({'ok': False, 'message': 'จำนวนสต็อกไม่ถูกต้อง', 'stock': variant.stock}, status=400)
    variant.stock = stock
    variant.save(update_fields=['stock'])
    return JsonResponse({'ok': True, 'stock': variant.stock, 'message': 'บันทึกแล้ว'})


# ------------------------------------------------------------ categories
@staff_required
def category_list(request):
    return render(request, 'dashboard/category_list.html', {'categories': Category.objects.annotate(n=Count('products'))})


@staff_required
def category_form(request, pk=None):
    category = get_object_or_404(Category, pk=pk) if pk else None
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        messages.success(request, f'บันทึกหมวดหมู่ "{saved.name}" แล้ว')
        return redirect('dashboard:categories')
    return render(request, 'dashboard/category_form.html', {'form': form, 'category': category})


@staff_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        try:
            category.delete()
        except ProtectedError:
            messages.error(request, 'ลบไม่ได้ เพราะยังมีสินค้าอยู่ในหมวดหมู่นี้ กรุณาย้ายหรือลบสินค้าก่อน')
        else:
            messages.success(request, f'ลบหมวดหมู่ "{category.name}" แล้ว')
        return redirect('dashboard:categories')
    return render(request, 'dashboard/confirm_delete.html', {'title': 'ลบหมวดหมู่', 'object_name': category.name, 'back': 'dashboard:categories'})


# ------------------------------------------------------------ orders
def _filtered_orders(request):
    qs = Order.objects.select_related('user')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(number__icontains=q) | Q(full_name__icontains=q) | Q(phone__icontains=q) | Q(user__email__icontains=q))
    status = request.GET.get('status', '')
    if status in Order.Status.values:
        qs = qs.filter(status=status)
    pay = request.GET.get('payment', '')
    if pay in Order.Payment.values:
        qs = qs.filter(payment_method=pay)
    d_from = parse_date(request.GET.get('from'), None)
    d_to = parse_date(request.GET.get('to'), None)
    if d_from:
        qs = qs.filter(created_at__gte=reports.bounds(d_from, d_from)[0])
    if d_to:
        qs = qs.filter(created_at__lt=reports.bounds(d_to, d_to)[1])
    return qs, {'q': q, 'status': status, 'payment': pay, 'from': d_from, 'to': d_to}


@staff_required
def order_list(request):
    qs, filters = _filtered_orders(request)
    if request.GET.get('export') == 'csv':
        return orders_csv(qs)
    page, qstr = paginate(request, qs)
    return render(request, 'dashboard/order_list.html', {
        'page': page, 'querystring': qstr, 'f': filters,
        'statuses': Order.Status.choices, 'payments': Order.Payment.choices,
    })


def orders_csv(qs):
    rows = ((o.number, timezone.localtime(o.created_at).strftime('%Y-%m-%d %H:%M'), o.full_name, o.user.email, o.phone, o.address,
             o.province, o.postal_code, o.get_payment_method_display(), o.get_status_display(), o.subtotal, o.shipping_fee, o.total)
            for o in qs.iterator())
    return csv_response('orders.csv', ['เลขที่คำสั่งซื้อ', 'วันที่', 'ชื่อผู้รับ', 'อีเมล', 'โทรศัพท์', 'ที่อยู่', 'จังหวัด', 'รหัสไปรษณีย์',
                                       'วิธีชำระเงิน', 'สถานะ', 'ราคาสินค้า', 'ค่าจัดส่ง', 'ยอดรวม'], rows)


@staff_required
def order_detail(request, number):
    order = get_object_or_404(Order.objects.select_related('user').prefetch_related('items'), number=number)
    form = OrderStatusForm(request.POST or None, initial={
        'status': order.status, 'carrier': order.carrier, 'tracking_number': order.tracking_number})
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            before = (order.status, order.carrier, order.tracking_number)
            order = change_order_status(order, d['status'], d['carrier'], d['tracking_number'])
        except InvalidTransition as e:
            messages.error(request, str(e))
        else:
            if d['status'] == Order.Status.SHIPPED:
                messages.success(request, 'บันทึกการจัดส่งแล้ว และส่งอีเมลเลขพัสดุให้ลูกค้าเรียบร้อย')
            else:
                messages.success(request, f'อัปเดตสถานะเป็น "{order.get_status_display()}" แล้ว')
        return redirect('dashboard:order_detail', number=number)
    return render(request, 'dashboard/order_detail.html', {
        'order': order, 'form': form, 'final': order.status == Order.Status.CANCELLED})


@staff_required
@require_POST
def order_confirm_payment(request, number):
    order = get_object_or_404(Order, number=number)
    if order.status != Order.Status.PENDING_PAYMENT:
        messages.error(request, 'คำสั่งซื้อนี้ไม่ได้อยู่ในสถานะรอชำระเงิน')
    else:
        change_order_status(order, Order.Status.PROCESSING)
        messages.success(request, 'ยืนยันการชำระเงินแล้ว และส่งอีเมลแจ้งลูกค้าเรียบร้อย')
    return redirect('dashboard:order_detail', number=number)


@staff_required
@require_POST
def order_resend_shipping(request, number):
    order = get_object_or_404(Order, number=number)
    if order.status != Order.Status.SHIPPED or not order.tracking_number:
        messages.error(request, 'ส่งอีเมลซ้ำได้เฉพาะคำสั่งซื้อที่จัดส่งแล้วและมีเลขพัสดุ')
    else:
        notify.shipped(order)
        messages.success(request, f'ส่งอีเมลเลขพัสดุไปที่ {order.user.email} อีกครั้งแล้ว')
    return redirect('dashboard:order_detail', number=number)


# ------------------------------------------------------------ users (superuser only)
@superuser_required
def user_list(request):
    qs = User.objects.annotate(
        order_count=Count('orders', distinct=True),
        spent=Sum('orders__total', filter=~Q(orders__status=Order.Status.CANCELLED)),
    )
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q))
    role = request.GET.get('role', '')
    qs = {'customer': qs.filter(is_staff=False), 'staff': qs.filter(is_staff=True, is_superuser=False),
          'superuser': qs.filter(is_superuser=True)}.get(role, qs)
    status = request.GET.get('status', '')
    qs = {'active': qs.filter(is_active=True), 'inactive': qs.filter(is_active=False)}.get(status, qs)
    page, qstr = paginate(request, qs.order_by('-date_joined'))
    return render(request, 'dashboard/user_list.html', {'page': page, 'querystring': qstr, 'q': q, 'role': role, 'status': status})


@superuser_required
def user_form(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    form = UserForm(request.POST or None, instance=user, editing_self=bool(user and user.pk == request.user.pk))
    if request.method == 'POST' and form.is_valid():
        saved = form.save()
        messages.success(request, f'บันทึกผู้ใช้ "{saved.email}" แล้ว')
        return redirect('dashboard:users')
    return render(request, 'dashboard/user_form.html', {'form': form, 'target': user})


@superuser_required
def user_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = SetPasswordForm(request.POST or None, user=target)
    if request.method == 'POST' and form.is_valid():
        target.set_password(form.cleaned_data['password1'])
        target.save(update_fields=['password'])
        messages.success(request, f'ตั้งรหัสผ่านใหม่ให้ {target.email} แล้ว')
        return redirect('dashboard:users')
    return render(request, 'dashboard/user_password.html', {'form': form, 'target': target})


@superuser_required
def user_delete(request, pk):
    target = get_object_or_404(User, pk=pk)
    blocked = None
    if target.pk == request.user.pk:
        blocked = 'ไม่สามารถลบบัญชีของตัวเองได้'
    elif target.orders.exists():
        blocked = 'ผู้ใช้นี้มีประวัติคำสั่งซื้อ จึงลบไม่ได้ กรุณาปิดการใช้งานบัญชีแทน'
    if request.method == 'POST':
        if blocked:
            messages.error(request, blocked)
        else:
            target.delete()
            messages.success(request, f'ลบผู้ใช้ "{target.email}" แล้ว')
        return redirect('dashboard:users')
    return render(request, 'dashboard/confirm_delete.html', {
        'title': 'ลบผู้ใช้', 'object_name': target.email, 'back': 'dashboard:users', 'blocked': blocked})


# ------------------------------------------------------------ reports
@staff_required
def report(request):
    today = timezone.localdate()
    start = parse_date(request.GET.get('from'), today.replace(day=1))
    end = parse_date(request.GET.get('to'), today)
    if end < start:
        start, end = end, start
    if (end - start).days > 730:
        start = end - timedelta(days=730)
        messages.error(request, 'เลือกช่วงเวลาได้ไม่เกิน 2 ปี ระบบปรับวันที่เริ่มต้นให้แล้ว')
    group = request.GET.get('group') or ('day' if (end - start).days <= 62 else 'month')
    group = 'month' if group == 'month' else 'day'

    sales = reports.sales_between(start, end)
    series = reports.daily_series(start, end) if group == 'day' else reports.monthly_series(start, end)
    products = reports.top_products(sales, limit=1000)

    export = request.GET.get('export')
    if export == 'periods':
        return csv_response(f'sales-{start}-{end}.csv', ['ช่วงเวลา', 'จำนวนคำสั่งซื้อ', 'ยอดขาย (บาท)'],
                            [(r['label'].strftime('%Y-%m' if group == 'month' else '%Y-%m-%d'), r['orders'], r['revenue']) for r in series])
    if export == 'products':
        return csv_response(f'products-{start}-{end}.csv', ['สินค้า', 'จำนวนที่ขาย (ชิ้น)', 'ยอดขาย (บาท)'],
                            [(r['name'], r['qty'], r['revenue']) for r in products])
    if export == 'orders':
        return orders_csv(reports.orders_between(start, end))

    pay_labels = dict(Order.Payment.choices)
    status_labels = dict(Order.Status.choices)
    return render(request, 'dashboard/report.html', {
        'start': start, 'end': end, 'group': group,
        'summary': reports.summarize(sales),
        'series': reports.with_bars(series),
        'products': products[:20],
        'categories': reports.by_category(sales),
        'payments': [{**r, 'label': pay_labels.get(r['payment_method'], r['payment_method'])} for r in reports.by_payment(sales)],
        'statuses': [{**r, 'label': status_labels.get(r['status'], r['status'])} for r in reports.by_status(start, end)],
        'month_start': today.replace(day=1), 'today': today,
        'last30_start': today - timedelta(days=29),
    })
