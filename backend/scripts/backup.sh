#!/usr/bin/env bash
# Nightly backup: the database (compressed pg_dump) plus uploaded files
# (company logos), keeping the last N days.
#
#   BACKUP_DIR=/var/backups/erp KEEP_DAYS=14 ./scripts/backup.sh
#
# Cron (02:30 every night):
#   30 2 * * * cd /srv/erp && ./backend/scripts/backup.sh >> /var/log/erp-backup.log 2>&1
#
# Restore:
#   gunzip -c erp-YYYY-MM-DD_HHMM.sql.gz | docker compose exec -T postgres psql -U erp -d erp
#   tar -xzf media-YYYY-MM-DD_HHMM.tar.gz -C backend/
#
# Copy the backup directory off the server (rsync, S3, Backblaze) — a backup
# on the same disk as the database is not a backup.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$ROOT/backups}"
KEEP_DAYS="${KEEP_DAYS:-14}"
STAMP="$(date +%F_%H%M)"
mkdir -p "$BACKUP_DIR"

cd "$ROOT"
docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-erp}" -d "${POSTGRES_DB:-erp}" --no-owner \
  | gzip > "$BACKUP_DIR/erp-$STAMP.sql.gz"

# An empty or truncated dump must fail loudly, not rotate out the good ones.
if [ "$(gzip -dc "$BACKUP_DIR/erp-$STAMP.sql.gz" | head -c 200 | wc -c)" -lt 100 ]; then
  echo "backup FAILED: dump is empty" >&2
  rm -f "$BACKUP_DIR/erp-$STAMP.sql.gz"
  exit 1
fi

if [ -d "$ROOT/backend/media" ]; then
  tar -czf "$BACKUP_DIR/media-$STAMP.tar.gz" -C "$ROOT/backend" media
fi

find "$BACKUP_DIR" -name 'erp-*.sql.gz' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'media-*.tar.gz' -mtime +"$KEEP_DAYS" -delete
echo "$(date -Is) backup ok: $(du -h "$BACKUP_DIR/erp-$STAMP.sql.gz" | cut -f1) -> $BACKUP_DIR/erp-$STAMP.sql.gz"
