#!/usr/bin/env bash
# Deploy a version of the app on the pilot VPS. Run as the dorm-laundry user:
#
#   sudo -u dorm-laundry /srv/dorm-laundry/app/deploy/scripts/deploy.sh [git-ref]
#
# git-ref defaults to origin/main; a tag such as v1.2.0 is better for the
# pilot. Steps: fetch and check out, install pinned requirements, build CSS,
# compile translations, collect static files, migrate, Django's deployment
# check, restart gunicorn, then wait for /healthz. Stops at the first error;
# the running app keeps serving until the restart.
set -euo pipefail

APP_DIR="${APP_DIR:-/srv/dorm-laundry/app}"
VENV="${VENV:-/srv/dorm-laundry/venv}"
ENV_FILE="${ENV_FILE:-/etc/dorm-laundry/env}"
SOCKET="${SOCKET:-/run/dorm-laundry/gunicorn.sock}"
REF="${1:-origin/main}"

log() { printf '\n== %s\n' "$*"; }

cd "$APP_DIR"
set -a
# shellcheck source=/dev/null
. "$ENV_FILE"
set +a
export DJANGO_SETTINGS_MODULE=config.settings.prod DJANGO_READ_DOT_ENV=false

log "Fetching $REF"
git fetch --tags --prune origin
git checkout --quiet --detach "$REF"
git log -1 --format='%h %s'

log "Installing pinned requirements"
"$VENV/bin/pip" install --quiet --requirement requirements.txt

log "Building CSS, translations and static files"
"$VENV/bin/python" scripts/tailwind.py build
"$VENV/bin/python" manage.py compilemessages --verbosity 0
"$VENV/bin/python" manage.py collectstatic --noinput --verbosity 0

log "Updating the database"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py createcachetable
"$VENV/bin/python" manage.py expire_initial_pins

log "Checking production settings"
"$VENV/bin/python" manage.py check --deploy --fail-level WARNING

log "Restarting the app"
sudo /bin/systemctl restart dorm-laundry.service

log "Waiting for /healthz"
# Straight to gunicorn's socket: nginx on port 80 would redirect to HTTPS.
for _ in $(seq 1 30); do
    if curl --fail --silent --max-time 3 --unix-socket "$SOCKET" \
        --header "Host: ${DJANGO_ALLOWED_HOSTS%%,*}" http://localhost/healthz >/dev/null; then
        log "Deployed $(git rev-parse --short HEAD). Healthy."
        exit 0
    fi
    sleep 1
done
echo "The app did not answer /healthz after the restart. See: journalctl -u dorm-laundry -n 100" >&2
exit 1
