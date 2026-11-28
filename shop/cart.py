from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from .models import ProductVariant, ShopSettings


@dataclass
class CartLine:
    variant: ProductVariant
    qty: int
    limited: bool = False  # quantity was clamped to available stock

    @property
    def product(self):
        return self.variant.product

    @property
    def max_qty(self):
        return Cart.max_qty(self.variant)

    @property
    def total(self):
        return self.variant.price * self.qty

    @property
    def saving(self):
        if self.variant.on_sale:
            return (self.variant.compare_price - self.variant.price) * self.qty
        return Decimal('0')


class Cart:
    """Session-backed cart: {variant_id: qty}. Stock and price are always read fresh from the DB."""

    def __init__(self, request):
        self.session = request.session
        self.data = self.session.setdefault(settings.CART_SESSION_KEY, {})
        self._lines = None

    # --- mutation -------------------------------------------------------
    def _save(self):
        self.session.modified = True
        self._lines = None

    @staticmethod
    def max_qty(variant):
        return max(0, min(variant.stock, settings.CART_MAX_QTY))

    def add(self, variant, qty=1):
        """Add qty to the line. Returns True when the request was clamped to stock."""
        key = str(variant.pk)
        wanted = self.data.get(key, 0) + qty
        allowed = self.max_qty(variant)
        self.data[key] = min(wanted, allowed)
        if self.data[key] <= 0:
            self.data.pop(key, None)
        self._save()
        return wanted > allowed

    def set(self, variant, qty):
        key = str(variant.pk)
        allowed = self.max_qty(variant)
        if qty <= 0 or allowed == 0:
            self.data.pop(key, None)
        else:
            self.data[key] = min(qty, allowed)
        self._save()
        return qty > allowed

    def remove(self, variant):
        self.data.pop(str(variant.pk), None)
        self._save()

    def clear(self):
        self.session[settings.CART_SESSION_KEY] = {}
        self.data = self.session[settings.CART_SESSION_KEY]
        self._save()

    # --- reading --------------------------------------------------------
    @property
    def lines(self):
        if self._lines is None:
            ids = [int(k) for k in self.data if str(k).isdigit()]
            variants = {v.pk: v for v in ProductVariant.objects.purchasable().filter(pk__in=ids)
                        .select_related('product').prefetch_related('product__images')}
            lines = []
            for key, qty in self.data.items():
                variant = variants.get(int(key)) if str(key).isdigit() else None
                if not variant or variant.stock <= 0:
                    continue
                allowed = self.max_qty(variant)
                lines.append(CartLine(variant, min(qty, allowed), limited=qty > allowed))
            lines.sort(key=lambda l: (l.product.name, l.variant.sort_order, l.variant.pk))
            self._lines = lines
        return self._lines

    def __iter__(self):
        return iter(self.lines)

    def __len__(self):
        """Total item quantity (shown in the header badge)."""
        return sum(l.qty for l in self.lines)

    @property
    def subtotal(self):
        return sum((l.total for l in self.lines), Decimal('0'))

    @property
    def savings(self):
        return sum((l.saving for l in self.lines), Decimal('0'))

    @property
    def shipping_fee(self):
        if self.is_empty:
            return Decimal('0')
        return ShopSettings.load().shipping_for(self.subtotal)

    @property
    def total(self):
        return self.subtotal + self.shipping_fee

    @property
    def free_shipping_gap(self):
        """How much more to spend for free shipping (0 when already free or empty)."""
        if self.is_empty:
            return Decimal('0')
        if self.shipping_fee == 0:
            return Decimal('0')
        return max(Decimal('0'), ShopSettings.load().free_shipping_threshold - self.subtotal)

    def sync(self):
        """Rewrite the session so it matches what is really purchasable (clamp qty, drop unavailable)."""
        self.data.clear()
        for line in self.lines:
            self.data[str(line.variant.pk)] = line.qty
        self._save()

    @property
    def is_empty(self):
        return not self.lines
