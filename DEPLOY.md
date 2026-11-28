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
4. **Folders:** `media/` (product images, public), `private_media/` (payment slips, private) and `var/` (cache) must be writable by the app user. Do not expose `private_media/` in nginx.
5. **Services:** install `deploy/shop.service.example` and `deploy/nginx.conf.example`, run certbot, `systemctl enable --now shop`
6. **Email:** fill `EMAIL_*` (a transactional provider such as SES, Brevo or Mailgun, or Gmail with an app password). Send yourself a test order and check the seller and customer emails arrive.
7. **Check:** `DJANGO_DEBUG=0 .venv/bin/python manage.py check --deploy`; once HTTPS works everywhere set `SECURE_HSTS_SECONDS=31536000`
8. **Shop settings:** log in as the superuser and fill in `/manage/settings/` (bank account, PromptPay, contact details, shipping fee, logo). Finish and publish the draft pages in `/manage/pages/` (return policy, privacy policy, terms).
9. **Before launch:** change the admin password, run `manage.py import_ns_select` (or add products in /manage/) and set real stock per variant
10. **Backups:** `deploy/backup.sh` (database + media + payment slips, keeps 14 days). Add it to cron: `30 3 * * * /srv/shop/deploy/backup.sh >> /srv/shop/var/backup.log 2>&1` and copy `/srv/shop/backups` to another machine. Test a restore once (commands are at the bottom of the script).
11. **Known limits:** emails are sent inside the web request (fine for a small shop). Login and password-reset are rate limited in Django (5 wrong passwords per account / 20 per IP in 15 minutes); this relies on `TRUST_X_REAL_IP=1` behind nginx and a cache directory writable by the app user (`var/cache`).
