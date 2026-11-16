from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from .models import Product


@dataclass
class CartLine:
    product: Product
    qty: int
    limited: bool = False  # quantity was clamped to available stock

    @property
    def total(self):
        return self.product.price * self.qty

    @property
    def saving(self):
        if self.product.on_sale:
            return (self.product.compare_price - self.product.price) * self.qty
        return Decimal('0')


class Cart:
    """Session-backed cart: {product_id: qty}. Stock and price are always read fresh from the DB."""

    def __init__(self, request):
        self.session = request.session
        self.data = self.session.setdefault(settings.CART_SESSION_KEY, {})
        self._lines = None

    # --- mutation -------------------------------------------------------
    def _save(self):
        self.session.modified = True
        self._lines = None

    @staticmethod
    def max_qty(product):
        return max(0, min(product.stock, settings.CART_MAX_QTY))

    def add(self, product, qty=1):
        """Add qty to the line. Returns True when the request was clamped to stock."""
        key = str(product.pk)
        wanted = self.data.get(key, 0) + qty
        allowed = self.max_qty(product)
        self.data[key] = min(wanted, allowed)
        if self.data[key] <= 0:
            self.data.pop(key, None)
        self._save()
        return wanted > allowed

    def set(self, product, qty):
        key = str(product.pk)
        allowed = self.max_qty(product)
        if qty <= 0 or allowed == 0:
            self.data.pop(key, None)
        else:
            self.data[key] = min(qty, allowed)
        self._save()
        return qty > allowed

    def remove(self, product):
        self.data.pop(str(product.pk), None)
        self._save()

    def clear(self):
        self.session[settings.CART_SESSION_KEY] = {}
        self.data = self.session[settings.CART_SESSION_KEY]
        self._save()

    # --- reading --------------------------------------------------------
    @property
    def lines(self):
        if self._lines is None:
            ids = [int(k) for k in self.data]
            products = {p.pk: p for p in Product.objects.filter(pk__in=ids, is_active=True)}
            lines = []
            for key, qty in self.data.items():
                product = products.get(int(key))
                if not product or product.stock <= 0:
                    continue
                allowed = self.max_qty(product)
                lines.append(CartLine(product, min(qty, allowed), limited=qty > allowed))
            lines.sort(key=lambda l: l.product.name)
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
        if self.is_empty or self.subtotal >= settings.FREE_SHIPPING_THRESHOLD:
            return Decimal('0')
        return Decimal(settings.SHIPPING_FEE)

    @property
    def total(self):
        return self.subtotal + self.shipping_fee

    @property
    def free_shipping_gap(self):
        """How much more to spend for free shipping (0 when already free or empty)."""
        if self.is_empty:
            return Decimal('0')
        return max(Decimal('0'), Decimal(settings.FREE_SHIPPING_THRESHOLD) - self.subtotal)

    def sync(self):
        """Rewrite the session so it matches what is really purchasable (clamp qty, drop unavailable)."""
        self.data.clear()
        for line in self.lines:
            self.data[str(line.product.pk)] = line.qty
        self._save()

    @property
    def is_empty(self):
        return not self.lines
