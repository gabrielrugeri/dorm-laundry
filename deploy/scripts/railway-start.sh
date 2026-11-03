#!/usr/bin/env bash
# Start command of the demo image on Railway (see Dockerfile and
# docs/DEPLOY-RAILWAY.md).
#
# Railway mounts the volume for uploaded files at /app/private_media owned by
# root. When started as root, this script gives that folder to the
# unprivileged "app" user and then runs everything else as "app". It then
# puts back the demo's placeholder files (only when DEMO_MODE=true; the
# pre-deploy step cannot write to the volume) and starts gunicorn.
set -euo pipefail

media="${PRIVATE_MEDIA_ROOT:-/app/private_media}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$media"
    chown app:app "$media"
    exec setpriv --reuid=app --regid=app --init-groups "$0" "$@"
fi

python manage.py seed_demo_files
exec gunicorn config.wsgi
