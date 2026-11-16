from decimal import Decimal

from django import template

register = template.Library()


@register.filter
def baht(value):
    """770 -> '770', 1499.5 -> '1,499.50'"""
    if value is None or value == '':
        return ''
    value = Decimal(value)
    if value == value.to_integral_value():
        return f'{int(value):,}'
    return f'{value:,.2f}'


@register.simple_tag
def icon(name, size=24, cls=''):
    from django.templatetags.static import static
    from django.utils.html import format_html
    return format_html(
        '<svg class="icon {}" width="{}" height="{}" aria-hidden="true"><use href="{}#{}"></use></svg>',
        cls, size, size, static('img/icons.svg'), name,
    )
