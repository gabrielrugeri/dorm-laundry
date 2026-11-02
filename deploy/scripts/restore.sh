#!/usr/bin/env bash
# Restore a backup made by backup.sh.
#
#   restore.sh BACKUP_FILE AGE_IDENTITY_FILE [--into-production]
#
# By default it is a RESTORE TEST: the database goes into a separate database
# named dorm_laundry_restore_test and the uploads into
# /srv/dorm-laundry/restore-test/private_media, so nothing in use is touched.
# Check them, then drop the test database. Do this test before the pilot and
# every few months (docs/DEPLOYMENT.md, "Restore test").
#
# --into-production replaces the live database and uploads. Stop the app
# first (systemctl stop dorm-laundry); it asks you to type the database name.
set -euo pipefail
umask 077

usage() { echo "Usage: $0 BACKUP_FILE AGE_IDENTITY_FILE [--into-production]" >&2; exit 2; }
[ $# -ge 2 ] || usage
backup="$1"
identity="$2"
mode="${3:-test}"
[ -f "$backup" ] || { echo "No such backup file: $backup" >&2; exit 2; }
[ -f "$identity" ] || { echo "No such age identity (private key) file: $identity" >&2; exit 2; }

: "${DATABASE_URL:?DATABASE_URL is not set (source /etc/dorm-laundry/env)}"
PRIVATE_MEDIA_ROOT="${PRIVATE_MEDIA_ROOT:-/srv/dorm-laundry/private_media}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "Decrypting"
age --decrypt --identity "$identity" "$backup" | tar --extract --directory="$work"

if [ "$mode" = "--into-production" ]; then
    db_name="${DATABASE_URL##*/}"
    db_name="${db_name%%\?*}"
    if systemctl is-active --quiet dorm-laundry.service; then
        echo "Stop the app first: sudo systemctl stop dorm-laundry" >&2
        exit 1
    fi
    read -r -p "This REPLACES the live database '$db_name' and all uploads. Type the database name to continue: " answer
    [ "$answer" = "$db_name" ] || { echo "Not confirmed. Nothing changed." >&2; exit 1; }
    target_url="$DATABASE_URL"
    media_target="$PRIVATE_MEDIA_ROOT"
elif [ "$mode" = "test" ]; then
    target_url="${DATABASE_URL%/*}/dorm_laundry_restore_test"
    media_target="/srv/dorm-laundry/restore-test/private_media"
    echo "Restore test: database dorm_laundry_restore_test, uploads in $media_target"
    dropdb --if-exists --maintenance-db="$DATABASE_URL" dorm_laundry_restore_test
    createdb --maintenance-db="$DATABASE_URL" dorm_laundry_restore_test
else
    usage
fi

echo "Restoring the database"
pg_restore --clean --if-exists --no-owner --dbname="$target_url" "$work/database.dump"

echo "Restoring the uploads"
mkdir -p "$media_target"
if [ "$mode" = "--into-production" ]; then
    find "$media_target" -mindepth 1 -delete
fi
tar --extract --gzip --file="$work/private_media.tar.gz" --directory="$media_target"

echo "Done. Residents in the restored database:"
psql --dbname="$target_url" --tuples-only --command "SELECT count(*) FROM accounts_resident;"
if [ "$mode" = "test" ]; then
    echo "When you have checked it: dropdb --maintenance-db=\"\$DATABASE_URL\" dorm_laundry_restore_test"
fi
