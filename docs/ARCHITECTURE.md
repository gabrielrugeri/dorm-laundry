# Architecture

A plain server-rendered Django app. HTMX adds partial page updates, Tailwind
provides styles, and there is no SPA framework. Scope is in [MVP-SPEC.md](MVP-SPEC.md).

## Project layout

```
config/settings/   base.py (shared), dev.py, prod.py, test.py
apps/
  core/            base pages, seed_demo command
  accounts/        User, Resident, StaffProfile, roles
  dorms/           Dormitory, TimeSlot, Machine
  bookings/        Booking
  ledger/          LedgerEntry (money)
  keylog/          KeyLog (key pick-up / return)
templates/         base.html and shared templates
assets/css/        Tailwind source (compiled into static/css/app.css)
static/vendor/     third-party JS we serve ourselves (htmx)
locale/            ru / en translation catalogs
scripts/           tailwind.py, check_translations.py
```

## Data model

```
Dormitory ─┬─ TimeSlot      (start_time, duration; per dormitory)
           ├─ Machine
           ├─ Resident ──── User (login)
           └─ StaffProfile ─ User (manager / admin)

Booking: machine + date + slot + resident   (one row per slot)
LedgerEntry: resident ± amount [→ booking]  (append-only)
KeyLog: first booking of a group → taken_at / returned_at
```

Everything belongs to a `Dormitory`, and every query must be scoped by it.
Staff are scoped through `StaffProfile.dormitory`.

## Rules enforced by the database

| Rule | How |
|---|---|
| No double-booking | partial `UNIQUE(machine, date, slot) WHERE status NOT IN ('cancelled', 'cancelled_by_admin')` |
| Admin cancellations explain themselves | `CHECK`: `cancelled_by_admin` needs a non-empty `cancel_reason` |
| No double charge / refund | `UNIQUE(booking, kind)` for `booking` and `refund` ledger entries |
| Money signs make sense | `CHECK`: credit/refund > 0, booking < 0, adjustment ≠ 0 |
| Only charges/refunds point to bookings | `CHECK` on `LedgerEntry.booking` |
| Key returned after taken | `CHECK` on `KeyLog` |
| Unique student code, slot start, machine number | per-dormitory `UNIQUE` constraints |

Rows that other rows depend on are deleted with `PROTECT`. Deactivate them
instead (`User.is_active`, `Machine.active`, `TimeSlot.active`).

## Audit log and admin safety

- `apps/audit`: every admin action is an `AuditEvent` (who, when, action code,
  target, before/after JSON snapshots, reason, dormitory). Events are
  append-only; the application never edits or deletes them (the only planned
  exception is blanking personal data when a resident is anonymized).
- Write paths call `apps.audit.services.record()` inside the same transaction
  as the change, with `snapshot()` before and after. Snapshots never contain
  passwords or PINs, and activation links are never stored.
- Action codes and their translated names are in `apps/audit/actions.py`.
- Django admin: bookings, the audit log and existing ledger entries are
  read-only. Bookings are cancelled with the actions "Cancel with refund rule"
  and "Cancel with full refund" (confirmation page, mandatory reason), which
  call the booking service. Manual credits and adjustments go through
  `apps.ledger.services.add_manual_entry` (mandatory note). Every other admin
  edit, including inline rows, is recorded by the `AuditedAdmin` mixin.
- `/manage/` (admin role only) is our own admin area; `/manage/history/` shows
  the dormitory's audit log with filters. Later stages add residents, imports,
  machines, settings and receipts there (see `docs/plans/admin-and-payments.md`).

## Residents in the admin area

- `/manage/residents/`: list with search (name, room, student code) and filters
  (active, owe money, access turned off), ordered by room in natural order
  (`room_key`: 210 < 301-1 < 301-2 < 1010), then name; the Room, Name and
  Balance headers sort (`?sort=`, `-` reverses). `/manage/residents/<id>/`: the
  profile, built to answer "is this resident in good standing?" (balance,
  debt since, upcoming bookings, recent payments; full history collapsed).
- Actions call `apps/accounts/services.py` (create, update, deactivate,
  reactivate, anonymize, delete) and `apps/ledger/services.py`
  (`add_manual_entry`). Money goes through one "Change balance" screen: type
  (payment received = `credit`, correction = `adjustment`, so reconciliation
  keeps them apart), add or subtract, amount, and a note (required for
  corrections). A subtracted payment is a negative `credit` ("payment taken
  back"), so it stays in the payments column.
  Each writes its audit event in the same transaction.
- Residents with history (bookings or money) are never deleted; access is
  turned off, or personal data is erased (`anonymize`): name, room and code
  are blanked, also in old audit snapshots (ids and amounts kept), access and
  PIN are turned off, and bookings and money stay. Turning off or erasing a
  resident in debt needs an explicit confirmation; the debt is recorded in
  the audit event.
- "Reset PIN / login link" (one action, with a warning page) shows a
  one-time link once and never stores it. The current PIN keeps working until
  the link is used, so a mistaken click locks nobody out; setting the new PIN
  invalidates the link (and logging in with the old PIN does too, since the
  token covers the last login). The payment history downloads as an Excel-friendly CSV with
  protection against formula injection.
- CSV import (`apps/accounts/importing.py`, pages in `apps/manage/resident_import.py`):
  `preview()` compares each row with the dormitory's residents by student
  code (new / changed with before and after / unchanged / error) and writes
  nothing; `apply()` repeats the comparison and, in one transaction, creates
  and updates residents through the resident services, skipping error rows.
  The previewed file stays in the admin's session (tied to their dormitory
  and a one-time token) until it is confirmed. Excel files are read as UTF-8
  (with or without BOM) or Windows-1251, separated by ";" or ",". Login links
  for the new residents are generated when downloaded and never stored.
- `apps/audit/display.py` shows audit snapshots in plain words (no field
  names, codes, ids or UTC times) on the change history page.

## Money

- Amounts are whole rubles (`int`).
- The balance is `LedgerEntry.objects.balance(resident)`, the sum of the
  resident's entries. It is never stored.
- Ledger entries are never edited or deleted. A mistake is corrected with an
  `adjustment` entry.
- `Booking.price_rub` keeps the price that was charged, so a refund returns
  exactly that amount even if the price changes later.

## Time

- `USE_TZ = True`: datetimes are stored in UTC.
- `Booking.date` is the local calendar date and `TimeSlot.start_time` is local
  time in the dormitory's timezone.
- `Booking.starts_at` / `ends_at` (UTC) are derived from those two on save.
  Queries such as "today", "overdue" and the cancellation cutoff use them.
- Pages behind `resident_required` / `staff_required` render in the
  dormitory's timezone (the decorator activates it), so every time residents
  see is Moscow time.
- Calendar files (`.ics`) also use Moscow wall-clock time
  (`DTSTART;TZID=Europe/Moscow:…` with a VTIMEZONE of UTC+03:00), not UTC.
  The Google Calendar link uses UTC (`…Z`), the Outlook link local time with
  its offset (`+03:00`); all three come from one `calendar.Event`.

## Booking service

`apps/bookings/services.py` is the only code that creates or cancels
bookings. Views and the admin call it instead of saving `Booking` or
`LedgerEntry` rows themselves. Each function raises a `BookingError` subclass
when the action is not allowed; its `message` is translated and safe to show
to residents.

- `book_machines(resident, machines, day, slots)` books one or more machines
  for the same consecutive slots. Slots are consecutive when they are
  neighbours among the dormitory's active slots and each one ends exactly when
  the next one starts. Each machine gets its own group: one `Booking` per slot,
  sharing a `group_id`, and one ledger charge per slot. Everything happens in
  one transaction with one balance check for the whole amount (machines ×
  slots × price): either everything is booked and charged, or nothing is. The
  day must be within `booking_horizon_days` (today counts as day 1) and the
  first slot must not have started. `book_slots(resident, machine, day, slots)`
  is the same for one machine.
- `cancel_booking(booking, actor=user, reason="", full_refund=False)` cancels
  one slot. The owner can cancel (status `cancelled`), and so can a manager or
  admin of the same dormitory (status `cancelled_by_admin`, with a mandatory
  `reason` that the resident sees, recorded in the audit log). Cancelling at
  least `cancellation_cutoff_hours` before the start refunds `price_rub`;
  later cancellations free the machine but are not refunded. Admins (not
  managers) may pass `full_refund=True` to refund regardless of the cutoff. A
  booking that has started cannot be cancelled.
- `cancel_group(group_id, actor=user, …)` cancels a group's slots that have not
  started; each one follows the refund rule on its own.
- Check "is this booking cancelled?" with `booking.is_cancelled` or
  `status__in=Booking.CANCELLED_STATUSES`, never `status == "cancelled"`.
- `refund_due(booking)` tells the UI whether cancelling now would be refunded.

Ledger entries made because a resident booked or cancelled have
`created_by = None`. When staff cancel, the refund records the staff user.

Concurrency:

- Two residents booking the same slot: the partial unique index lets only
  one insert commit, and the other request gets `SlotUnavailable`.
- One resident sending two bookings at once: `book_machines` locks the resident's
  row (`SELECT ... FOR UPDATE`) before checking the balance, so the second
  request sees the balance after the first one's charge. SQLite serialises
  all writes anyway (`IMMEDIATE` transactions).
- Cancelling twice: the booking row is locked and its status checked, and
  `UNIQUE(booking, kind)` on the ledger refuses a second refund.

These cases have real multi-threaded tests in
`apps/bookings/tests/test_races.py`, marked `postgres`. They run in the
PostgreSQL CI job, or locally with `DATABASE_URL` set to a PostgreSQL database.

There is no limit on how many consecutive slots one booking may take. That is
an open question for the dormitory administration.

## Machines and slots

- Machines have a **number**; pages show them as "Machine 3" / «Машина 3» in
  the selected language (`Machine.name`). Nothing about a machine is stored
  as English text.
- Slots are data (`TimeSlot`), set per dormitory in the admin. The demo uses
  seven two-hour slots from 10:00 to midnight. A slot may end exactly at
  midnight; it is shown as 22:00–00:00 and its calendar event ends at 00:00
  of the next day.

## Resident screens

All are behind `resident_required` and use only the resident's own data.

| URL | What |
|---|---|
| `/?day=…&length=N` | Schedule: pick a day (today … booking horizon) and a length ("How long?": N slots in a row). Lists only start times where at least one machine is free for all N slots, with how many machines are; the resident's own bookings of the day are listed above. Tabs swap only the grid with htmx; plain links work without JavaScript. |
| `/book/<date>/<slot>/?length=N` | Every machine, with checkboxes for those free for all N slots; the others are greyed out and say why (booked, free only until HH:MM, out of service). Ticking several machines books them all with `book_machines()`; a small script shows the running total. Service errors are shown on the form. |
| `/bookings/confirmed/?g=…` | What was just booked: one item per machine. Machines booked together for the same time share one "Add to calendar" menu (one event); otherwise each item has its own. |
| `/bookings/` | Upcoming bookings (one row per group) and the last 30 days of past and cancelled ones. |
| `/bookings/<group>/` | One booking; "Add to calendar" menu and a link to cancelling. |
| `/bookings/<group>/cancel/` | States per slot whether it will be refunded, then `cancel_group()` on POST. |
| `/bookings/<group>/calendar.ics` | Calendar file (`apps/bookings/ics.py`, no dependency), named `laundry-<CODE>-YYYY-MM-DD-HH-HH-M<n>.ics`. |
| `/bookings/calendar.ics?g=…` | One calendar file for machines booked together (`…-M1-M3.ics` lists every machine number). |
| `/balance/` | The resident's name and room, balance, and history: one line per booking (see below), 20 lines per page. |

- **"Add to calendar"** (`apps/bookings/calendar.py`) is a menu of three
  plain links: Google Calendar and Outlook.com (prefilled "new event" pages,
  opened in a new tab with `rel="noopener noreferrer"`) and the `.ics` file
  for Apple Calendar and everything else (Yandex Calendar imports it too; it
  has no documented prefilled link). Our pages load nothing from Google or
  Microsoft, so the CSP stays self-only; the event text names the machines,
  time and dormitory, never the resident. `Dormitory.code` (e.g. `DEM`,
  set by superusers in `/admin/`) goes into the file name.
- *Later option, not built:* a personal calendar feed
  (`/calendar/<token>.ics`) with a random, hashed, revocable token, so new
  bookings appear by themselves. Trade-offs: the URL works like a password;
  Google refreshes feeds only every 12–24 hours (cancellations show late);
  Google fetches the feed from abroad, so the server must be reachable from
  outside Russia.
- **Balance history lines** (`apps/ledger/history.py`): the ledger keeps one
  entry per slot, so partial cancellations and refunds stay exact. For
  display, adjacent entries with the same booking group and kind become one
  line ("Машина 1, 29 октября 14:00–18:00: −100 ₽") with the per-slot entries
  under «Подробнее». A later partial cancellation is its own refund line.

- `apps/bookings/availability.py` answers the grid's questions with counts,
  never with other residents' bookings. `groups.py` turns the slots booked
  together into one item and returns 404 for anyone else's group.
- The navigation (bottom bar on phones) shows the balance on every page, from
  the `apps.ledger.context_processors.resident_balance` context processor.
- `apps/bookings/tests/test_privacy.py` visits every resident page and calendar
  file and checks that another resident's name, room and code never appear.

## Consecutive slots and keys

The key log belongs to the group's first booking, and the key is due at the end
of the group's last non-cancelled slot.

## Manager's key screen

`/staff/` (managers and admins, `staff_required`) is the key schedule.

**On hold:** while `KEYS_ENABLED` is false (the default), the key schedule
and key actions return 404 and "Keys" leaves the admin navigation. `/staff/`
then sends admins to `/manage/` and shows managers a short "not available
yet" page. The tests in `apps/keylog/tests/` switch it on.

- **Days:** yesterday, today and tomorrow. One row per booking group: time,
  machine, the resident's **name and room** (staff-only), and the key status:
  waiting, taken, returned, or overdue.
- **One button per row:** "Key taken", then "Key returned", with an optional
  note. "Undo" reverts the latest tap within 10 minutes; older corrections go
  through the admin (Key log). htmx swaps the whole schedule after each tap;
  without JavaScript it is a normal POST and redirect.
- **"Keys out now":** every key taken and not returned, from any day, overdue
  ones first. This answers "who has the key right now".
- `apps/keylog/services.py` (`take_key`, `return_key`, `undo_last`) is the only
  code that changes KeyLog rows. Times come from the server clock, the staff
  member is recorded in `recorded_by`, and only active staff of the booking's
  dormitory may act. `apps/keylog/schedule.py` builds the rows.
- **Open question:** one key per machine, or one key for the laundry room?
  Tracking per booking works either way.

## Login and activation

- **Residents** log in with student code + 6-digit PIN
  (`apps.accounts.backends.ResidentBackend`). The PIN is the user's password,
  stored hashed. Until the pilot has more than one dormitory, the dormitory
  comes from the `DEFAULT_DORMITORY_SLUG` setting.
- **Staff** log in on the same form with username and password
  (Django's `ModelBackend`).
- **No hints:** every failed login shows the same message. Unknown codes cost
  the same hashing time as wrong PINs, so the form cannot reveal which codes
  exist.
- **Lockout:** `LOGIN_MAX_FAILURES` failures for one code from one IP block
  login for `LOGIN_LOCKOUT_SECONDS` (`apps/accounts/ratelimit.py`). The default
  cache is per process; use a shared cache when running several workers.
  Behind a proxy, the real client IP must reach `REMOTE_ADDR`.
- **Activation links** are Django password-reset tokens (no extra table). They
  are valid for `PASSWORD_RESET_TIMEOUT` (7 days) and stop working once the
  PIN is set. Admins create them, or reset a PIN, with actions on the
  Residents admin page.
- **Language:** the resident chooses it themselves in the header menu; the
  choice is saved on their profile (`Resident.language`) as well as in the
  cookie, and logging in or activating on any device switches to it. Admins
  do not set it (no field in the resident form; a CSV "language" column is
  ignored).
- **How long a login lasts** (`apps/accounts/sessions.py`): residents 30 days
  from their last visit (the session is refreshed at most once a day, to avoid
  a database write per request); staff 12 hours from logging in, not
  extended by activity. Trade-off: a lost or shared phone stays logged in as
  the resident for up to a month, but a resident's session can only book,
  cancel and see their own bookings and balance, and residents won't put up
  with typing a PIN every day. Staff pages show residents' names and rooms,
  so a forgotten staff login must end the same day.
- **Header menu:** "Name · room" for residents (only their own), the username
  for staff; it holds My balance, the language switch and Log out.

## Roles and privacy

- Roles are the Django groups `resident`, `manager` and `admin`, created by a
  migration. Use `apps.accounts.roles.has_role()` to check them.
- Protect views with `resident_required`, `staff_required` or
  `role_required(...)` from `apps/accounts/decorators.py`. They require login,
  check the role, and set `request.dormitory`; scope every query by it.
- No URL outside the admin takes a student code. A test enforces this.
- Residents' names and rooms are shown only to managers and admins. Pages that
  residents see show only free/occupied (and "yours").

## Front-end

- No CDNs or third-party requests. htmx is vendored in `static/vendor/`.
  Tailwind is compiled locally with the standalone CLI
  (`scripts/tailwind.py`, pinned version, verified by SHA256).
- Pages use the system font stack, so no font files are needed.
- WhiteNoise serves static files in production.

## Deployment readiness

Provider-neutral pieces every deployment uses (targets and gates are in
`docs/plans/admin-and-payments.md`):

- **`DEMO_MODE`**: a banner on every page («Демо: все имена и данные здесь
  вымышленные»), `<meta name="robots" content="noindex">`, an `X-Robots-Tag`
  header and a `robots.txt` that disallows everything.
- **Start guard**: `config/settings/prod.py` raises at startup when
  `DEMO_MODE=false` and `PILOT_READY` is not `true`, so an instance without the
  demo banner cannot start before the pilot gate is passed.
- **`/healthz`**: 200 when the app and the database answer, 503 otherwise; no
  login, exempt from the HTTPS redirect (platform health checks may use HTTP).
- **Shared cache** in production: `DatabaseCache` in PostgreSQL (run
  `manage.py createcachetable` on deploy), so the login lockout counts
  failures across all server workers.
- **Request size**: `RequestSizeLimitMiddleware` answers 413 above
  `MAX_UPLOAD_BYTES_HARD` (default 20 MB); the web server limit must match.
- **Content-Security-Policy** (`SecurityHeadersMiddleware`): `default-src
  'self'` and scripts and styles only from our own static files, so the
  browser itself blocks anything from another domain (hard rule 1). Templates
  must not contain inline scripts or `on…=` handlers (a test checks this);
  behaviour lives in `static/js/app.js` and is wired with `data-*` attributes.
  Django admin (superusers only) is allowed inline styles.
- `DJANGO_READ_DOT_ENV=false` makes settings ignore a local `.env` file
  (servers use real environment variables).
- **Railway demo** (`Dockerfile`, `gunicorn.conf.py`,
  `config/settings/railway.py`, guide in `docs/DEPLOY-RAILWAY.md`): CSS,
  translations and static files are built into the image; `manage.py
  predeploy` runs migrate, createcachetable and (demo only) the idempotent
  `seed_demo`. The Railway settings refuse to start without `DEMO_MODE=true`,
  and `seed_demo` on a server refuses the demo passwords published in the
  README. CI builds and smoke-tests the image.

## Translations

- Default language is Russian; English is the alternative. The language is
  switched with a cookie through `accounts:set_language` (Django's
  `set_language`, plus saving a resident's choice); URLs have no language
  prefix.
- CI runs `makemessages` and then `scripts/check_translations.py`. The build
  fails if any Russian string is untranslated or fuzzy.

### Adding a language

Nothing in the code depends on the language: all text goes through gettext,
and the language switch and `Resident.language` read `settings.LANGUAGES`.
To add one (Kazakh as an example):

1. Add `("kk", _("Kazakh"))` to `LANGUAGES` in `config/settings/base.py`, then
   run `python manage.py makemigrations` (the `Resident.language` choices change).
2. `python manage.py makemessages -l kk`, translate
   `locale/kk/LC_MESSAGES/django.po`, then `python manage.py compilemessages`.
3. Add `-l kk` to the `makemessages` commands in CI, the README and
   `docs/CLAUDE.md`, and make `scripts/check_translations.py` check the new
   catalog too (today it checks Russian only).

A right-to-left language (Arabic, Hebrew) would also need `dir="rtl"` on
`<html>` and a check of the layouts.
