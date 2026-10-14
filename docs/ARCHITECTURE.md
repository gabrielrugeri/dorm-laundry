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
| No double-booking | partial `UNIQUE(machine, date, slot) WHERE status <> 'cancelled'` |
| No double charge / refund | `UNIQUE(booking, kind)` for `booking` and `refund` ledger entries |
| Money signs make sense | `CHECK`: credit/refund > 0, booking < 0, adjustment ≠ 0 |
| Only charges/refunds point to bookings | `CHECK` on `LedgerEntry.booking` |
| Key returned after taken | `CHECK` on `KeyLog` |
| Unique student code, slot start, machine label | per-dormitory `UNIQUE` constraints |

Rows that other rows depend on are deleted with `PROTECT`. Deactivate them
instead (`User.is_active`, `Machine.active`, `TimeSlot.active`).

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

## Consecutive slots

Booking several consecutive slots creates one `Booking` per slot, all sharing
a `group_id`. The group is charged and confirmed as one unit by the booking
service (next feature). The key log belongs to the group's first booking, and
the key is due at the end of the group's last non-cancelled slot.

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
- **Language:** logging in, or activating, switches the interface to the
  resident's saved language.

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

## Translations

- Default language is Russian; English is the alternative. The language is
  switched with a cookie through Django's `set_language` view; URLs have no
  language prefix.
- CI runs `makemessages` and then `scripts/check_translations.py`. The build
  fails if any Russian string is untranslated or fuzzy.
