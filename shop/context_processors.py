from django.conf import settings

from .cart import Cart
from .models import Category, Page, ShopSettings


def site(request):
    shop = ShopSettings.load()
    return {
        'SITE_NAME': settings.SITE_NAME,
        'SITE_TAGLINE': settings.SITE_TAGLINE,
        'SITE_SLOGAN': settings.SITE_SLOGAN,
        'SHOP': shop,
        'nav_categories': Category.objects.all(),
        'footer_pages': Page.objects.filter(is_published=True, show_in_footer=True),
        'cart': Cart(request),
        'SHIPPING_FEE': shop.shipping_fee,
        'FREE_SHIPPING_THRESHOLD': shop.free_shipping_threshold,
    }
