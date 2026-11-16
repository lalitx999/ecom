from shop.models import Order


def badges(request):
    """Counts shown in the back-office sidebar (only computed for staff on /manage/ pages)."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated and user.is_staff and request.path.startswith('/manage/')):
        return {}
    S = Order.Status
    to_ship = Order.objects.filter(status=S.PROCESSING).count()
    slips = Order.objects.filter(status=S.PENDING_PAYMENT).exclude(payment_slip='').count()
    return {'badge_orders': to_ship + slips, 'badge_to_ship': to_ship, 'badge_slips': slips}
