#!/usr/bin/env bash
# Nightly backup of the pilot: the PostgreSQL database and the private
# uploads (receipts, QR code), encrypted with `age` BEFORE they leave the
# server, then copied off-site with `rclone` (e.g. a Russian S3-compatible
# storage). Run by dorm-laundry-backup.timer; settings in
# /etc/dorm-laundry/backup.env (see deploy/backup.env.example).
#
# Encryption uses the administration's age PUBLIC key: the server can make
# backups but cannot read them. The private key is kept offline by two
# people and is needed only to restore (deploy/scripts/restore.sh).
set -euo pipefail
umask 077

: "${DATABASE_URL:?DATABASE_URL is not set}"
: "${BACKUP_AGE_RECIPIENT:?BACKUP_AGE_RECIPIENT (age public key) is not set}"
: "${BACKUP_RCLONE_REMOTE:?BACKUP_RCLONE_REMOTE (e.g. s3backup:dorm-laundry) is not set}"
PRIVATE_MEDIA_ROOT="${PRIVATE_MEDIA_ROOT:-/srv/dorm-laundry/private_media}"
BACKUP_DIR="${BACKUP_DIR:-/srv/dorm-laundry/backups}"
KEEP_LOCAL_DAYS="${BACKUP_KEEP_LOCAL_DAYS:-7}"
KEEP_REMOTE_DAYS="${BACKUP_KEEP_REMOTE_DAYS:-35}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Dumping the database"
pg_dump --format=custom --no-owner --dbname="$DATABASE_URL" --file="$work/database.dump"

echo "Packing the private uploads"
tar --create --gzip --file="$work/private_media.tar.gz" --directory="$PRIVATE_MEDIA_ROOT" .

echo "Encrypting"
archive="$BACKUP_DIR/dorm-laundry-$stamp.tar.age"
tar --create --directory="$work" database.dump private_media.tar.gz \
    | age --recipient "$BACKUP_AGE_RECIPIENT" --output "$archive"

echo "Copying off-site to $BACKUP_RCLONE_REMOTE"
rclone copy --no-traverse "$archive" "$BACKUP_RCLONE_REMOTE/"
# Make sure the copy is really there (size check) before cleaning up.
rclone check --one-way --size-only "$BACKUP_DIR" "$BACKUP_RCLONE_REMOTE" \
    --include "$(basename "$archive")"

echo "Removing old copies (local > ${KEEP_LOCAL_DAYS} days, off-site > ${KEEP_REMOTE_DAYS} days)"
find "$BACKUP_DIR" -name 'dorm-laundry-*.tar.age' -mtime +"$KEEP_LOCAL_DAYS" -delete
rclone delete --min-age "${KEEP_REMOTE_DAYS}d" --include 'dorm-laundry-*.tar.age' "$BACKUP_RCLONE_REMOTE"

echo "Backup done: $(basename "$archive") ($(du -h "$archive" | cut -f1))"
if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
    # Optional: tell an uptime checker the backup ran (it alerts if it does not).
    curl --fail --silent --max-time 10 "$BACKUP_HEARTBEAT_URL" >/dev/null || true
fi
