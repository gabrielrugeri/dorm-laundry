# Dorm Laundry

Open-source web app for booking washing machines in university dormitories.
Residents see free slots at a glance, book and cancel from their phones, and
pay from a prepaid balance. (Key handling for a key manager exists but is on
hold: switched off unless `KEYS_ENABLED=true`.)

Pilot: one dormitory, 6 machines, 2-hour slots, 50 RUB per machine per slot.
Works in Russian and English, and loads nothing from third-party servers.

- Scope: [docs/MVP-SPEC.md](docs/MVP-SPEC.md)
- How it works: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Contributor and AI-assistant guide: [docs/CLAUDE.md](docs/CLAUDE.md)

> Status: early development. Residents can log in, see free machines, book,
> cancel, export bookings to their calendar and see their balance. Key
> handling is on hold (`KEYS_ENABLED=false` by default). Admins manage residents at
> `/manage/residents/` (payments, balance corrections, login links, turning
> access off, erasing personal data, importing a list from a CSV file) and see every admin action in the change
> history at `/manage/history/`. The admin and payment features in
> [docs/plans/admin-and-payments.md](docs/plans/admin-and-payments.md) are in
> progress.

## Requirements

- Python 3.12+
- GNU gettext, only to update translations (`makemessages` / `compilemessages`).
  On Linux: `apt install gettext`. On macOS: `brew install gettext`. On Windows,
  install it from <https://mlocati.github.io/articles/gettext-iconv-windows.html>.
- PostgreSQL in production. Development uses SQLite.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env               # optional in development
python scripts/tailwind.py build   # downloads the Tailwind CLI once, builds CSS
python manage.py compilemessages   # needs gettext
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Then open <http://127.0.0.1:8000/>. Dormitory admins work at `/manage/`.
On a phone the site can be installed on the home screen (it shows how); it
follows the phone's dark mode, or the choice in the header menu.
Django admin (`/admin/`) is for developers only: create a superuser with
`python manage.py createsuperuser`.

### Demo accounts (fake data from `seed_demo`)

| Login | Password | Role |
|---|---|---|
| `admin` | `SEED_DEMO_STAFF_PASSWORD` (default `demo-staff-password`) | dormitory admin (`/manage/`) |
| `manager` | same as above | key manager (sees a "not available yet" page while key handling is on hold) |
| student code `D0001` … `D0020` | PIN `SEED_DEMO_RESIDENT_PIN` (default `123456`) | residents |

Everyone logs in at `/account/login/`: residents with student code and PIN,
staff with username and password. Change these values on any server
reachable by other people.

### Giving residents access

Admins manage residents at `/manage/residents/` (in Russian by default):

1. **Add a resident** (name, room, student code), or open an existing one.
2. On the resident's page, open **More → Reset PIN / login link**
   («Ещё → Сбросить PIN / ссылка для входа»). Give the link to that resident
   only. It works once and expires after 7 days; the link is shown once and
   never stored. Any current PIN keeps working until the link is used.
3. The resident opens it, chooses a 6-digit PIN and is logged in.

If someone forgets their PIN: the same action, **More → Reset PIN / login
link**, then give them the new link.

Money: **Change balance** («Изменить баланс») on the resident's page records a
payment received or a correction, adding or subtracting, with a preview of the
new balance.

**Many residents at once:** on the resident list, **Add many residents from a
file** («Добавить много жильцов из файла»). Save the list from Excel as CSV with
the columns student code, full name and room. You first see a preview (new,
will change, no changes, errors) and nothing changes until you press
**Import**. Afterwards you can download the login links of the new residents
as one file. Importing the same file again changes nothing. A fake example to
try with the demo data: [docs/examples/residents-import-demo.csv](docs/examples/residents-import-demo.csv).

## Deployment

- **Public demo (fake data only):** Railway, step by step in
  [docs/DEPLOY-RAILWAY.md](docs/DEPLOY-RAILWAY.md). Always `DEMO_MODE=true`;
  hosted outside Russia, so it may be unreachable from some Russian networks.
- **Pilot (real data):** Russian hosting, only after every item of the pilot
  gate in [docs/plans/admin-and-payments.md](docs/plans/admin-and-payments.md)
  is done. Production settings refuse to start with `DEMO_MODE=false` unless
  `PILOT_READY=true`.

## Everyday commands

| Task | Command |
|---|---|
| Run tests | `pytest` |
| Also run the PostgreSQL-only race tests | `DATABASE_URL=postgres://user:pass@localhost:5432/laundry pytest` |
| Lint and format | `ruff check . && ruff format .` |
| Rebuild CSS while editing | `python scripts/tailwind.py watch` |
| Update translations | `python manage.py makemessages -l ru -l en`, translate `locale/ru/LC_MESSAGES/django.po`, then `python scripts/check_translations.py && python manage.py compilemessages` |
| Add a dependency | add it to `requirements.in` (or `requirements-dev.in`), then `pip-compile requirements.in && pip-compile requirements-dev.in` |

## Configuration

All settings that differ between machines are environment variables. They are
documented in [.env.example](.env.example). `manage.py` uses
`config.settings.dev` by default, while WSGI/ASGI default to
`config.settings.prod`.

## Contributing

- Branch from `main` as `feat/…`, `fix/…`, `chore/…` or `docs/…`, and open a
  pull request. CI must pass.
- Keep commits small, with messages in the imperative mood, e.g.
  `feat(bookings): add cancellation`.
- Every user-facing string must be translatable and translated into Russian.
- Never commit real personal data or secrets.

## License

[MIT](LICENSE)
