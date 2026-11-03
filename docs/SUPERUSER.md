# For superusers (developers running the app)

Dormitory admins and managers do everything in the app's own pages
(`/manage/`, the key schedule). A **superuser** is a developer with access to
the server. This page lists what only a superuser does, and how.

Everything below runs **on the server**, inside the app:

- Railway: `railway ssh -- python manage.py …` (docs/DEPLOY-RAILWAY.md,
  section 8);
- the pilot VPS: `sudo -u dorm-laundry bash -c 'set -a; . /etc/dorm-laundry/env; set +a; cd /srv/dorm-laundry/app && /srv/dorm-laundry/venv/bin/python manage.py …'`.

## Your own superuser account

```bash
python manage.py createsuperuser
```

Only superusers can open Django admin (`/admin/`). Never give a superuser
account to dormitory staff, and never make a dormitory account a superuser.

## Dormitory admins and managers

There is no page for this on purpose: a dormitory has one or two admins, and
creating them is rare. Use `manage.py dormitory_admin`.

**Create** an admin (or `--role manager` for a key manager):

```bash
python manage.py dormitory_admin create --dormitory demo --username olga --role admin --name "Ольга Комендантова"
```

It prints a **one-time link** where the person chooses their own password:
nobody else, you included, ever knows it. The link works once and for 7
days. Send it **privately** (in person, or a direct message), never in a
group chat. The person then logs in with the username and that password.

- The dormitory is given by its **slug** (Django admin → Dormitories).
- The name is shown in the header («Имя · Общежитие»). Usernames are unique,
  ignoring upper/lower case.

**Forgot the password, or the link expired:** print a new link (the old
password keeps working until the new one is set):

```bash
python manage.py dormitory_admin link --username olga
```

**Someone leaves:** switch the account off. They are logged out on every
device at once; everything they did stays in the history.

```bash
python manage.py dormitory_admin deactivate --username olga --reason "Left the job"
```

To switch an account back on, use Django admin (Users → the user → Active)
and then give them a new link.

**The links need the app's public address.** On Railway it is the generated
domain by default. Elsewhere set `PUBLIC_BASE_URL` (e.g.
`https://laundry.example.ru`) in the environment, or pass
`--base-url https://…` to `create` and `link`.

Every action is recorded in the change history (`/manage/history/`): account
created, link created, switched off, password chosen.

## Technical limits (Django admin only)

Django admin → "Money and upload rules". Dormitory admins change the money
rules on `/manage/settings/`; these limits are read-only for them and can be
changed only here, each time with a reason that goes into the history:

| Setting | Default | What it does |
|---|---|---|
| Largest receipt file, MB | 10 | Never above the server's own limit (`MAX_UPLOAD_BYTES_HARD`). |
| Wrong PINs before an account is locked | 5 | Then the account waits (next row). |
| First account lock, seconds | 60 | Each further lock doubles… |
| Longest account lock, seconds | 1800 | …up to this. |
| Wrong PINs from one address before waits start | 30 per 15 min | A whole dormitory may share one address: keep it generous. |
| Longest wait for one address, seconds | 10 | |
| Wrong PINs from one address per hour before blocking | 1000 | Then the address waits until the hour is over. |
| Days a first-time PIN stays valid | 14 | The date-of-birth PIN from the import. |

Details: docs/SECURITY.md.

## Secrets you look after

- `DJANGO_SECRET_KEY` signs logins and links. Changing it logs everyone out
  and invalidates every link.
- `PIN_PEPPER` is mixed into every resident PIN. **Losing or changing it
  makes every PIN invalid** (residents then need login links). Keep it in the
  password manager, apart from the database backups (docs/SECURITY.md).
- The backup decryption key stays offline (docs/DEPLOYMENT.md, section 6).

## Other commands

| Command | When |
|---|---|
| `python manage.py predeploy` | Every deploy (Railway runs it). Migrations, cache table, expired first-time PINs, demo data in demo mode. |
| `python manage.py expire_initial_pins` | Daily (systemd timer on the VPS) and every deploy. Safe any time. |
| `python manage.py seed_demo` | Demo only (`DEMO_MODE=true`): fake data. Changes nothing once the demo exists. |
| `python manage.py check --deploy` | After changing settings: must report no errors. |
