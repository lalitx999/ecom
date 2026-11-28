"""Simple fixed-window rate limits stored in the Django cache (no extra packages).

Login: after LOGIN_MAX_PER_ACCOUNT wrong passwords for one account, or LOGIN_MAX_PER_IP from one address, further
attempts are refused for LOGIN_WINDOW seconds. A successful login clears that account's counter.
Password reset: limited per IP (visible error) and per e-mail (silently not sent, so nobody can probe addresses).

The cache must be shared by all web workers in production (see CACHES in settings: file-based by default).
"""
import hashlib

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.dispatch import receiver

LOGIN_MAX_PER_ACCOUNT = 5
LOGIN_MAX_PER_IP = 20
LOGIN_WINDOW = 15 * 60
RESET_MAX_PER_IP = 5
RESET_MAX_PER_EMAIL = 3
RESET_WINDOW = 60 * 60


def client_ip(request):
    """Behind nginx REMOTE_ADDR is 127.0.0.1, so trust X-Real-IP (set by our nginx config) when told to."""
    if request is None:
        return 'unknown'
    if getattr(settings, 'TRUST_X_REAL_IP', False) and request.META.get('HTTP_X_REAL_IP'):
        return request.META['HTTP_X_REAL_IP'].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _key(kind, value):
    return f'rl:{kind}:' + hashlib.sha256(str(value).strip().lower().encode()).hexdigest()[:32]


def hit(key, window):
    if cache.add(key, 1, window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, window)
        return 1


def count(key):
    return cache.get(key, 0)


# ---- login ----
def login_blocked(request, username):
    return (count(_key('login-user', username)) >= LOGIN_MAX_PER_ACCOUNT
            or count(_key('login-ip', client_ip(request))) >= LOGIN_MAX_PER_IP)


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    hit(_key('login-user', credentials.get('username', '')), LOGIN_WINDOW)
    hit(_key('login-ip', client_ip(request)), LOGIN_WINDOW)


@receiver(user_logged_in)
def _on_logged_in(sender, request, user, **kwargs):
    cache.delete(_key('login-user', user.get_username()))
    if user.email:
        cache.delete(_key('login-user', user.email))


# ---- password reset ----
def reset_ip_blocked(request):
    return count(_key('reset-ip', client_ip(request))) >= RESET_MAX_PER_IP


def reset_allowed(request, email):
    """Record one reset request. Returns False when this address already received too many e-mails."""
    hit(_key('reset-ip', client_ip(request)), RESET_WINDOW)
    return hit(_key('reset-email', email), RESET_WINDOW) <= RESET_MAX_PER_EMAIL
