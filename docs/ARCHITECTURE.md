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

## Booking service

`apps/bookings/services.py` is the only code that creates or cancels
bookings. Views and the admin call it instead of saving `Booking` or
`LedgerEntry` rows themselves. Each function raises a `BookingError` subclass
when the action is not allowed; its `message` is translated and safe to show
to residents.

- `book_slots(resident, machine, day, slots)` books one or more consecutive
  slots on one machine. Slots are consecutive when they are neighbours among the
  dormitory's active slots and each one ends exactly when the next one starts.
  It creates one `Booking` per slot, all sharing a `group_id`, and charges one
  ledger entry per slot, all in one transaction: either everything is booked
  and charged, or nothing is. The day must be within `booking_horizon_days`
  (today counts as day 1) and the first slot must not have started.
- `cancel_booking(booking, actor=user)` cancels one slot. The owner can cancel,
  and so can a manager or admin of the same dormitory. Cancelling at least
  `cancellation_cutoff_hours` before the start refunds `price_rub`. Later
  cancellations are allowed and free the machine, but are not refunded. A
  booking that has started cannot be cancelled. Staff cannot override the
  refund rule; corrections go through an `adjustment` ledger entry.
- `cancel_group(group_id, actor=user)` cancels a group's slots that have not
  started; each one follows the refund rule on its own.
- `refund_due(booking)` tells the UI whether cancelling now would be refunded.

Ledger entries made because a resident booked or cancelled have
`created_by = None`. When staff cancel, the refund records the staff user.

Concurrency:

- Two residents booking the same slot: the partial unique index lets only
  one insert commit, and the other request gets `SlotUnavailable`.
- One resident sending two bookings at once: `book_slots` locks the resident's
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

## Consecutive slots and keys

The key log belongs to the group's first booking, and the key is due at the end
of the group's last non-cancelled slot.

## Roles and privacy

- Roles are the Django groups `resident`, `manager` and `admin`, created by a
  migration. Use `apps.accounts.roles.has_role()` to check them.
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
