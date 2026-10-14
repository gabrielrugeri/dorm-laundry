# Dorm Laundry

Open-source web app for booking washing machines in university dormitories.
Residents see free slots at a glance, book and cancel from their phones, and
pay from a prepaid balance. The key manager sees who should pick up which key.

Pilot: one dormitory, 6 machines, 2-hour slots, 50 RUB per machine per slot.
Works in Russian and English, and loads nothing from third-party servers.

- Scope: [docs/MVP-SPEC.md](docs/MVP-SPEC.md)
- How it works: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Contributor and AI-assistant guide: [docs/CLAUDE.md](docs/CLAUDE.md)

> Status: early development. Data model, admin, demo data and resident
> login/activation are in place; booking screens are next.

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

Then open <http://127.0.0.1:8000/>. The Django admin is at `/admin/`.

### Demo accounts (fake data from `seed_demo`)

| Login | Password | Role |
|---|---|---|
| `admin` | `SEED_DEMO_STAFF_PASSWORD` (default `demo-staff-password`) | admin (superuser) |
| `manager` | same as above | key manager |
| student code `D0001` … `D0020` | PIN `SEED_DEMO_RESIDENT_PIN` (default `123456`) | residents |

Everyone logs in at `/account/login/`: residents with student code and PIN,
staff with username and password. Change these values on any server
reachable by other people.

### Giving residents access

Residents choose their own PIN through a one-time activation link:

1. In the admin, open **Residents**, select residents and run
   **Create activation links** (or **Reset PIN and create activation links**
   if someone forgot their PIN).
2. Give each resident their own link. It works once and expires after 7 days.
3. The resident opens it, chooses a 6-digit PIN and is logged in.

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
