# Deploying the pilot (real data) on a Russian VPS

The runbook for the pilot: one dormitory, real residents, on a server in
Russia. For the public demo with fake data, see
[DEPLOY-RAILWAY.md](DEPLOY-RAILWAY.md) instead.

> **No real resident data until every item of the [pilot gate](#pilot-gate)
> is done.** The app enforces this: with `DEMO_MODE=false` it refuses to
> start unless `PILOT_READY=true` is set, and you set that only at the end.

Everything below assumes Ubuntu 24.04 LTS and the paths used by the files in
`deploy/`. Commands are run as a user with `sudo` unless stated otherwise.

## What you need

| Thing | Notes |
|---|---|
| A VPS in Russia | Timeweb Cloud, Selectel or the university's servers. 2 vCPU, 2 GB RAM, 20 GB disk is plenty. |
| A domain | e.g. `laundry.example.ru`, its A record pointing to the VPS. |
| Off-site storage | An S3-compatible bucket at a Russian provider, separate from the VPS, for backups. |
| An SMTP account | At a Russian mail provider, for alert e-mails (mail sent straight from a VPS lands in spam). |
| Two people | Each with their own SSH key to the server, and each holding a copy of the backup decryption key. |

## Files in `deploy/`

| File | Goes to | What it does |
|---|---|---|
| `nginx/dorm-laundry.conf` | `/etc/nginx/sites-available/` | HTTPS, static files, upload limit 20 MB, private files never served. |
| `systemd/dorm-laundry.service` | `/etc/systemd/system/` | gunicorn on a local socket, sandboxed. |
| `systemd/dorm-laundry-backup.service` + `.timer` | `/etc/systemd/system/` | Nightly backup at 03:30 Moscow time. |
| `systemd/dorm-laundry-alert@.service` | `/etc/systemd/system/` | E-mails when the app or the backup fails. |
| `scripts/deploy.sh` | (run from the checkout) | Updates the app and restarts it. |
| `scripts/backup.sh` | (run by the timer) | Database + uploads, encrypted with `age`, copied off-site with `rclone`. |
| `scripts/restore.sh` | (run by hand) | Restore test, or a real restore. |
| `scripts/alert.sh` | (run by the alert unit) | Sends the e-mail through SMTP. |
| `env.example` | `/etc/dorm-laundry/env` | App settings (secrets). |
| `backup.env.example` | `/etc/dorm-laundry/backup.env` | Backup and alert settings. |

## 1. Server basics

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install -y nginx postgresql python3.12-venv git gettext curl \
    certbot age rclone msmtp ufw unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades   # security updates
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

- Log in with SSH keys only: in `/etc/ssh/sshd_config` set
  `PasswordAuthentication no`, then `sudo systemctl reload ssh`.
- Give the second person their own account and key (`adduser`, `usermod -aG
  sudo`). **Check:** both of you can log in.

## 2. User, folders, database

```bash
sudo adduser --system --group --home /srv/dorm-laundry dorm-laundry
sudo usermod -aG dorm-laundry www-data          # nginx may use gunicorn's socket
sudo -u dorm-laundry mkdir -p /srv/dorm-laundry/{private_media,backups}
sudo chmod 750 /srv/dorm-laundry/private_media /srv/dorm-laundry/backups

sudo -u postgres createuser --pwprompt dorm_laundry
sudo -u postgres createdb --owner dorm_laundry dorm_laundry
```

Let the app user restart its own service (used by `deploy.sh`), nothing else:

```bash
echo 'dorm-laundry ALL=(root) NOPASSWD: /bin/systemctl restart dorm-laundry.service' \
    | sudo tee /etc/sudoers.d/dorm-laundry && sudo chmod 440 /etc/sudoers.d/dorm-laundry
```

## 3. The app

```bash
sudo -u dorm-laundry git clone https://github.com/gabrielrugeri/dorm-laundry.git /srv/dorm-laundry/app
sudo -u dorm-laundry python3.12 -m venv /srv/dorm-laundry/venv

sudo mkdir -p /etc/dorm-laundry
sudo cp /srv/dorm-laundry/app/deploy/env.example /etc/dorm-laundry/env
sudo cp /srv/dorm-laundry/app/deploy/backup.env.example /etc/dorm-laundry/backup.env
sudo chown -R root:dorm-laundry /etc/dorm-laundry && sudo chmod 750 /etc/dorm-laundry
sudo chmod 640 /etc/dorm-laundry/env /etc/dorm-laundry/backup.env
sudoedit /etc/dorm-laundry/env      # fill in every value
```

Generate the secret key with
`python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.
Keep `DEMO_MODE=false` and **`PILOT_READY=false`** for now.

## 4. nginx and HTTPS

```bash
sudo cp /srv/dorm-laundry/app/deploy/nginx/dorm-laundry.conf /etc/nginx/sites-available/dorm-laundry
sudoedit /etc/nginx/sites-available/dorm-laundry   # replace laundry.example.ru (3 places)
sudo mkdir -p /var/www/letsencrypt
```

Get the certificate first with a temporary HTTP-only site (comment out the
`server { listen 443 ... }` block), then:

```bash
sudo ln -s /etc/nginx/sites-available/dorm-laundry /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt -d laundry.example.ru
```

Uncomment the HTTPS block, `sudo nginx -t && sudo systemctl reload nginx`.
certbot renews by itself (`systemctl list-timers | grep certbot`).

## 5. systemd units and the first deploy

```bash
sudo cp /srv/dorm-laundry/app/deploy/systemd/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dorm-laundry.service dorm-laundry-backup.timer
```

The first deploy needs the app to be allowed to start, which it is not yet
(`PILOT_READY=false`). For the setup only, start it as a demo **with no
data**: temporarily set `DEMO_MODE=true` in `/etc/dorm-laundry/env`, then:

```bash
sudo -u dorm-laundry /srv/dorm-laundry/app/deploy/scripts/deploy.sh origin/main
```

**Check:** `https://laundry.example.ru/healthz` shows `{"status": "ok"}`, the
login page has the yellow «Демо» banner. Do **not** run `seed_demo` here and
do not enter anyone's real data while the banner is on.

Create the first admin (a superuser only for developers; the dormitory admin
gets the "admin" role in `/admin/` → Users):

```bash
cd /srv/dorm-laundry/app && sudo -u dorm-laundry bash -c \
  'set -a; . /etc/dorm-laundry/env; set +a; DJANGO_SETTINGS_MODULE=config.settings.prod \
   /srv/dorm-laundry/venv/bin/python manage.py createsuperuser'
```

## 6. Backups and alerts

1. **The decryption key stays offline.** On a laptop (not the server):
   `age-keygen -o dorm-laundry-backup.key`. It prints the public key
   (`age1...`). Give a copy of the key file to the second person; store both
   copies safely (e.g. a password manager and an encrypted USB stick).
2. Put the **public** key into `BACKUP_AGE_RECIPIENT` in
   `/etc/dorm-laundry/backup.env`.
3. Off-site storage: `sudo rclone config --config /etc/dorm-laundry/rclone.conf`
   (an S3 remote named `s3backup`), then
   `sudo chown root:dorm-laundry /etc/dorm-laundry/rclone.conf && sudo chmod 640 /etc/dorm-laundry/rclone.conf`.
4. Alerts: put the SMTP password into `/etc/dorm-laundry/smtp-password`
   (mode 640, group dorm-laundry) and fill in the `ALERT_*` values.
5. Test both:

```bash
sudo systemctl start dorm-laundry-backup.service && journalctl -u dorm-laundry-backup -n 20
sudo -u dorm-laundry bash -c 'set -a; . /etc/dorm-laundry/backup.env; set +a; \
  /srv/dorm-laundry/app/deploy/scripts/alert.sh "Test alert" ""'
```

**Check:** "Backup done" in the log, the file is in the bucket, and the test
e-mail arrived.

## 7. Restore test

On the server, with the key brought over just for the test (then deleted):

```bash
sudo -u dorm-laundry bash -c 'set -a; . /etc/dorm-laundry/env; set +a; \
  /srv/dorm-laundry/app/deploy/scripts/restore.sh \
  /srv/dorm-laundry/backups/dorm-laundry-<stamp>.tar.age /tmp/dorm-laundry-backup.key'
shred -u /tmp/dorm-laundry-backup.key
```

It restores into a **separate** database (`dorm_laundry_restore_test`) and
folder; nothing in use is touched. **Check:** it prints the number of
residents, and a receipt file opens from
`/srv/dorm-laundry/restore-test/private_media`. Then drop the test database.
Repeat every few months.

A real restore (`--into-production`) needs the app stopped and asks you to
type the database name.

## 8. Monitoring

- **Uptime:** an external checker on `https://laundry.example.ru/healthz`
  (expects HTTP 200). Prefer one with nodes in Russia: checkers abroad may
  report false outages when foreign traffic is filtered.
- **Backup heartbeat:** optionally set `BACKUP_HEARTBEAT_URL` to the checker's
  heartbeat URL, so a backup that silently stops running raises an alert.
- **Failures:** the app and the backup units e-mail through
  `dorm-laundry-alert@` when they fail.
- **Logs:** `journalctl -u dorm-laundry -f` (app), `/var/log/nginx/`.

## Pilot gate

Only when **every** line is done (and noted with the date and who checked):

| Item | How to check |
|---|---|
| Russian hosting | The VPS provider and region are in Russia. |
| HTTPS | `https://` opens without warnings; `http://` redirects. |
| Encrypted off-site backups | Section 6: the nightly file is in the bucket; the server has only the public key. |
| Restore test done | Section 7, with the date written down. |
| Monitoring and alerts | Section 8: an uptime check is active; the test alert e-mail arrived. |
| Second person with access | They have logged in with their own key and hold a copy of the backup key. |
| Receipt retention decided | The administration decided how long receipt files are kept (`docs/TRUST-MODEL.md`). |
| 152-FZ formalities | Confirmed by the administration (the university is the operator). |
| `check --deploy` clean | `deploy.sh` stops on any warning, so a successful deploy is the check. |

Then go live:

1. In `/etc/dorm-laundry/env` set `DEMO_MODE=false` and `PILOT_READY=true`.
2. Deploy: `sudo -u dorm-laundry /srv/dorm-laundry/app/deploy/scripts/deploy.sh <tag>`.
3. **Check:** no «Демо» banner; `/healthz` ok; an admin can log in.
4. Add the dormitory, its slots and machines in `/admin/` (developers), give
   the dormitory admin their role, then the admin imports the residents
   (`/manage/residents/import/`) and fills in «Как оплатить».

## Everyday tasks

- **New version:** tag the release on GitHub, then
  `sudo -u dorm-laundry /srv/dorm-laundry/app/deploy/scripts/deploy.sh v1.2.0`.
- **Roll back:** run the same command with the previous tag. Migrations are
  not undone automatically; if a release changed the database, restore the
  backup taken before it instead (section 7, `--into-production`).
- **Status:** `systemctl status dorm-laundry`, `systemctl list-timers dorm-laundry-backup`.
- **Upload limit:** `MAX_UPLOAD_BYTES_HARD` in `/etc/dorm-laundry/env` and
  `client_max_body_size` in the nginx config must stay equal.
