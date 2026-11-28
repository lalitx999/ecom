#!/usr/bin/env bash
# Nightly backup: database dump + product images + payment slips, kept for KEEP_DAYS days.
# Install (as the app user):  crontab -e  ->  30 3 * * * /srv/shop/deploy/backup.sh >> /srv/shop/var/backup.log 2>&1
# Copy BACKUP_DIR to another machine as well (rsync / rclone): a backup on the same disk does not survive a dead server.
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/shop}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"

set -a; [ -f "$APP_DIR/.env" ] && . "$APP_DIR/.env"; set +a
export PGPASSWORD="${DB_PASSWORD:-}"

stamp="$(date +%Y%m%d-%H%M)"
mkdir -p "$BACKUP_DIR"
umask 077   # backups contain customer data

pg_dump --no-owner -Fc -h "${DB_HOST:-localhost}" -p "${DB_PORT:-5432}" -U "${DB_USER:?set DB_USER}" "${DB_NAME:-ecommerce_db}" \
  > "$BACKUP_DIR/db-$stamp.dump"
tar -czf "$BACKUP_DIR/files-$stamp.tar.gz" -C "$APP_DIR" media private_media

find "$BACKUP_DIR" -name 'db-*.dump' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'files-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date '+%F %T') backup ok: db-$stamp.dump files-$stamp.tar.gz"

# Restore:
#   pg_restore --clean --no-owner -d ecommerce_db db-YYYYmmdd-HHMM.dump
#   tar -xzf files-YYYYmmdd-HHMM.tar.gz -C /srv/shop
