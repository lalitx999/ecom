import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
import json

from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .cart import Cart
from .forms import CheckoutForm, RegisterForm, SlipForm
from .models import Brand, Category, Order, Product, ProductVariant
from .services import SlipNotAllowed, StockError, attach_slip, place_order

PAGE_SIZE = 12


def _products():
    return Product.objects.for_listing()


def home(request):
    qs = _products()
    categories = []
    for c in Category.objects.all():
        items = list(qs.filter(category=c)[:8])
        if items:
            categories.append((c, items))
    return render(request, 'shop/home.html', {
        'featured': qs.filter(is_featured=True)[:5],
        'sale_products': qs.on_sale()[:8],
        'best_products': qs.filter(is_best_seller=True)[:8],
        'new_products': qs.filter(is_new=True)[:8],
        'category_sections': categories,
        'max_discount': max((p.discount_percent for p in qs.on_sale()), default=0),
    })


FILTERS = {
    'sale': ('ลดราคา', lambda qs: qs.on_sale()),
    'best': ('สินค้าขายดี', lambda qs: qs.filter(is_best_seller=True)),
    'new': ('สินค้าใหม่', lambda qs: qs.filter(is_new=True)),
}
SORTS = {
    'new': ('ใหม่ล่าสุด', ('-created_at', 'name')),
    'price_asc': ('ราคาต่ำไปสูง', ('price_min', 'name')),
    'price_desc': ('ราคาสูงไปต่ำ', ('-price_min', 'name')),
}


def product_list(request):
    qs = _products()
    title = 'สินค้าทั้งหมด'

    category = None
    slug = request.GET.get('category', '')
    if slug:
        category = get_object_or_404(Category, slug=slug)
        qs = qs.filter(category=category)
        title = category.name

    brand = None
    brand_slug = request.GET.get('brand', '')
    if brand_slug:
        brand = get_object_or_404(Brand, slug=brand_slug)
        qs = qs.filter(brand=brand)
        title = brand.name if not category else f'{category.name} | {brand.name}'

    size = request.GET.get('size', '').strip()
    if size:
        qs = qs.filter(pk__in=ProductVariant.objects.purchasable().filter(size=size, stock__gt=0).values('product_id'))

    flt = request.GET.get('filter', '')
    if flt in FILTERS:
        title, fn = FILTERS[flt]
        qs = fn(qs)

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(brand__name__icontains=q) | Q(description__icontains=q))
        title = f'ผลการค้นหา "{q}"'

    sort = request.GET.get('sort', 'new')
    if sort not in SORTS:
        sort = 'new'
    qs = qs.with_min_price().order_by(*SORTS[sort][1])

    # options for the brand/size filters come from what is actually for sale in this category
    scope = Product.objects.filter(is_active=True)
    if category:
        scope = scope.filter(category=category)
    brands = Brand.objects.filter(products__in=scope).distinct()
    sizes = list(ProductVariant.objects.purchasable().filter(product__in=scope, stock__gt=0).exclude(size='')
                 .values_list('size', flat=True).distinct())
    sizes.sort(key=size_sort_key)

    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'shop/product_list.html', {
        'page': page,
        'title': title,
        'category': category,
        'brand': brand,
        'brands': brands,
        'size': size,
        'sizes': sizes,
        'q': q,
        'filter': flt,
        'sort': sort,
        'sorts': [(k, v[0]) for k, v in SORTS.items()],
        'querystring': params.urlencode(),
    })


CLOTHING_SIZES = ['XXS', 'XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', 'XXXXL', 'FREE SIZE']


def size_sort_key(size):
    """XS < S < M ... then shoe sizes by number (US 4 < US 4.5 < US 10), then anything else alphabetically."""
    upper = size.upper()
    if upper in CLOTHING_SIZES:
        return (0, CLOTHING_SIZES.index(upper), '')
    digits = ''.join(ch for ch in size if ch.isdigit() or ch == '.')
    try:
        return (1, float(digits), size)
    except ValueError:
        return (2, 0, size)


def product_detail(request, slug):
    product = get_object_or_404(_products(), slug=slug)
    variants = sorted(product.active_variants, key=lambda v: (v.sort_order, size_sort_key(v.size), v.pk))
    sizes = sorted({v.size for v in variants if v.size}, key=size_sort_key)
    colors = list(dict.fromkeys(v.color for v in variants if v.color))
    images = product.image_list
    data = {
        'variants': [{
            'id': v.pk, 'color': v.color, 'size': v.size, 'price': str(v.price),
            'compare': str(v.compare_price) if v.on_sale else '', 'discount': v.discount_percent,
            'stock': Cart.max_qty(v), 'ready': v.ready_to_ship,
        } for v in variants],
        'images': [{'url': i.image.url, 'color': i.color} for i in images],
    }
    selected = product.single_variant or (variants[0] if len(variants) == 1 else None)
    related = _products().filter(category=product.category).exclude(pk=product.pk)[:4]
    return render(request, 'shop/product_detail.html', {
        'product': product,
        'colors': colors,
        'sizes': sizes,
        'images': images,
        'selected': selected,
        'variant_json': json.dumps(data, ensure_ascii=False),
        'related': related,
    })


# ---------------------------------------------------------------- cart
def cart_page(request):
    return render(request, 'shop/cart.html')


def _cart_response(request, cart, message='', ok=True, status=200):
    payload = {
        'ok': ok,
        'message': message,
        'count': len(cart),
        'subtotal': str(cart.subtotal),
        'drawer_html': render_to_string('shop/_cart_drawer.html', {'cart': cart}, request),
    }
    if request.POST.get('page') == '1':
        payload['page_html'] = render_to_string('shop/_cart_page_body.html', {'cart': cart}, request)
    return JsonResponse(payload, status=status)


def _read_variant_and_qty(request, default_qty=1):
    try:
        variant_id = int(request.POST.get('variant_id', ''))
        qty = int(request.POST.get('qty', default_qty))
    except ValueError:
        return None, None
    variant = ProductVariant.objects.purchasable().select_related('product').filter(pk=variant_id).first()
    return variant, qty


@require_POST
def cart_add(request):
    cart = Cart(request)
    variant, qty = _read_variant_and_qty(request)
    if not variant or qty < 1:
        return _cart_response(request, cart, 'ข้อมูลสินค้าไม่ถูกต้อง', ok=False, status=400)
    if not variant.in_stock:
        return _cart_response(request, cart, 'สินค้าหมด', ok=False, status=409)
    clamped = cart.add(variant, qty)
    if clamped:
        return _cart_response(request, cart, f'เพิ่มได้สูงสุด {Cart.max_qty(variant)} ชิ้นตามจำนวนสินค้าในสต็อก')
    return _cart_response(request, cart, 'เพิ่มลงในตะกร้าแล้ว')


@require_POST
def cart_update(request):
    cart = Cart(request)
    variant, qty = _read_variant_and_qty(request)
    if not variant or qty < 0:
        return _cart_response(request, cart, 'ข้อมูลสินค้าไม่ถูกต้อง', ok=False, status=400)
    clamped = cart.set(variant, qty)
    if clamped:
        return _cart_response(request, cart, f'สั่งได้สูงสุด {Cart.max_qty(variant)} ชิ้น')
    return _cart_response(request, cart)


@require_POST
def cart_remove(request):
    cart = Cart(request)
    variant, _ = _read_variant_and_qty(request, default_qty=0)
    if not variant:
        return _cart_response(request, cart, 'ข้อมูลสินค้าไม่ถูกต้อง', ok=False, status=400)
    cart.remove(variant)
    return _cart_response(request, cart, 'นำสินค้าออกจากตะกร้าแล้ว')


# ---------------------------------------------------------------- accounts
def register(request):
    if request.user.is_authenticated:
        return redirect('shop:orders')
    nxt = request.POST.get('next') or request.GET.get('next', '')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)  # session (and the cart in it) is kept
        messages.success(request, 'สมัครสมาชิกเรียบร้อยแล้ว')
        return redirect(nxt if nxt and url_has_allowed_host_and_scheme(nxt, request.get_host()) else 'shop:home')
    return render(request, 'shop/register.html', {'form': form, 'next': nxt})


# ---------------------------------------------------------------- checkout & orders
@login_required
def checkout(request):
    cart = Cart(request)
    if cart.is_empty:
        return redirect('shop:cart')

    last = request.user.orders.first()
    initial = {'full_name': request.user.first_name, 'payment_method': Order.Payment.COD}
    if last:
        initial.update(full_name=last.full_name, phone=last.phone, address=last.address, province=last.province, postal_code=last.postal_code)

    form = CheckoutForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        try:
            order = place_order(request.user, cart, form.cleaned_data)
        except StockError as e:
            cart.sync()
            names = ', '.join(dict.fromkeys(e.names))
            messages.error(request, f'สินค้าบางรายการมีไม่พอตามจำนวนที่เลือก ({names}) เราปรับตะกร้าให้แล้ว กรุณาตรวจสอบอีกครั้ง' if names else 'ตะกร้าว่างเปล่า')
            return redirect('shop:cart')
        cart.clear()
        messages.success(request, 'สั่งซื้อสำเร็จ ขอบคุณที่ใช้บริการ')
        return redirect(order)
    return render(request, 'shop/checkout.html', {'form': form})


@login_required
def order_list(request):
    return render(request, 'shop/order_list.html', {'orders': request.user.orders.all()})


@login_required
def order_detail(request, number):
    order = get_object_or_404(request.user.orders.prefetch_related('items'), number=number)
    slip_form = SlipForm()
    if request.method == 'POST':
        slip_form = SlipForm(request.POST, request.FILES)
        if slip_form.is_valid():
            try:
                attach_slip(order, slip_form.cleaned_data['slip'])
            except SlipNotAllowed as e:
                messages.error(request, str(e))
            else:
                messages.success(request, 'แนบสลิปเรียบร้อยแล้ว ร้านค้าจะตรวจสอบและยืนยันการชำระเงินให้')
            return redirect(order)
        order.refresh_from_db()
    return render(request, 'shop/order_detail.html', {
        'order': order,
        'transfer_info': settings.PAYMENT_TRANSFER_INFO,
        'slip_form': slip_form,
    })


@login_required
def order_slip(request, number):
    """Payment slips are private: only the buyer and staff may view them."""
    order = get_object_or_404(Order, number=number)
    if not order.payment_slip or not (order.user_id == request.user.pk or request.user.is_staff):
        raise Http404
    content_type = mimetypes.guess_type(order.payment_slip.name)[0] or 'application/octet-stream'
    resp = FileResponse(order.payment_slip.open('rb'), content_type=content_type)
    resp['Cache-Control'] = 'private, no-store'
    return resp
