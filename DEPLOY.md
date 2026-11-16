# Deploy checklist (Ubuntu + nginx + gunicorn + PostgreSQL)

1. **Server packages:** `python3`, `python3-venv`, `postgresql`, `nginx`, `certbot`
2. **Database:** create a PostgreSQL user and database, then set `DB_*` in `.env`
3. **Code:** copy the project to `/srv/shop`, then
   ```bash
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp .env.example .env        # fill in every value
   set -a; source .env; set +a
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py collectstatic --noinput
   .venv/bin/python manage.py createsuperuser   # log in with the username or the email
   ```
4. **Folders:** `media/` (product images, public) and `private_media/` (payment slips, private) must be writable by the app user. Do not expose `private_media/` in nginx.
5. **Services:** install `deploy/shop.service.example` and `deploy/nginx.conf.example`, run certbot, `systemctl enable --now shop`
6. **Email:** fill `EMAIL_*` (a transactional provider such as SES, Brevo or Mailgun, or Gmail with an app password). Send yourself a test order and check the seller and customer emails arrive.
7. **Check:** `DJANGO_DEBUG=0 .venv/bin/python manage.py check --deploy`; once HTTPS works everywhere set `SECURE_HSTS_SECONDS=31536000`
8. **Before launch:** change the admin password, remove demo data (`manage.py seed_demo_orders --purge`), put the real bank account in `PAYMENT_TRANSFER_INFO` (config/settings.py), replace sample products
9. **Backups:** nightly `pg_dump ecommerce_db` and a copy of `media/` and `private_media/` to another machine
10. **Known limits:** emails are sent inside the web request (fine for a small shop; move to a queue such as Celery if volume grows); there is no login rate limiting yet (put `limit_req` in nginx for `/login/`)
