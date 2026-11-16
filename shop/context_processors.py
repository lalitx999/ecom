from django.conf import settings

from .cart import Cart
from .models import Category


def site(request):
    return {
        'SITE_NAME': settings.SITE_NAME,
        'nav_categories': Category.objects.all(),
        'cart': Cart(request),
        'CONTACT': settings.SHOP_CONTACT,
        'SHIPPING_FEE': settings.SHIPPING_FEE,
        'FREE_SHIPPING_THRESHOLD': settings.FREE_SHIPPING_THRESHOLD,
    }
