#!/usr/bin/env bash
# Send an alert e-mail through an authenticated SMTP account (a Russian mail
# provider; mail sent straight from a VPS usually lands in spam). Used by
# dorm-laundry-alert@.service when the app or the backup fails, and by hand
# to test the setup:
#
#   alert.sh "Test alert" ""
#
# Needs msmtp; settings come from /etc/dorm-laundry/backup.env.
set -euo pipefail

: "${ALERT_EMAIL_TO:?ALERT_EMAIL_TO is not set}"
: "${ALERT_SMTP_HOST:?ALERT_SMTP_HOST is not set}"
: "${ALERT_SMTP_USER:?ALERT_SMTP_USER is not set}"
: "${ALERT_SMTP_PASSWORD_FILE:?ALERT_SMTP_PASSWORD_FILE is not set}"
subject="${1:-Dorm Laundry alert}"
unit="${2:-}"

body="$subject

Server: $(hostname)
Time: $(TZ=Europe/Moscow date '+%Y-%m-%d %H:%M %Z')"
if [ -n "$unit" ]; then
    body="$body

Last log lines of $unit:
$(journalctl --unit "$unit" --lines 30 --no-pager 2>/dev/null || echo '(journal not readable)')"
fi

printf 'To: %s\nFrom: %s\nSubject: [Dorm Laundry] %s\n\n%s\n' \
    "$ALERT_EMAIL_TO" "$ALERT_SMTP_USER" "$subject" "$body" \
    | msmtp --host="$ALERT_SMTP_HOST" --port="${ALERT_SMTP_PORT:-465}" \
        --tls=on --tls-starttls="${ALERT_SMTP_STARTTLS:-off}" --auth=on \
        --user="$ALERT_SMTP_USER" --passwordeval="cat $ALERT_SMTP_PASSWORD_FILE" \
        --from="$ALERT_SMTP_USER" "$ALERT_EMAIL_TO"
