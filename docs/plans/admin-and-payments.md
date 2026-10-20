# Plan: admin and payment features (approved 2026-10-20)

This records the plan approved by the product owner, so later stages and other
contributors can follow it. Each stage is one branch and one pull request from
`main`; the next stage starts after the previous one is merged.

**Order:** 1a → 1b → 1c → *deployment plan* → 2 → 3 → 4 → 5. Stages 2 and 3
both change `book_machines` and the booking model, so they never run in
parallel. Only the PWA may be built in a separate session.

## Rules for every stage

- Every write goes through a service function that records an audit event in
  the same transaction. Views never save models directly.
- Admin screens live under `/manage/` (admin role, scoped to the admin's
  dormitory, usable on phones). Django admin stays as a fallback: bookings,
  ledger, receipts, audit log and settings are read-only there.
- Money is whole rubles; kopecks are rejected.
- Each stage brings migrations, server-side role checks with tests, ru/en
  strings, no third-party requests, `seed_demo` data, README and `docs/`.

## Stage 1a: audit log and admin-safe bookings

- Append-only `AuditEvent` (who, when, action, target, before/after JSON,
  reason, dormitory); admin-only view at `/manage/history/`.
- Bookings are read-only in Django admin. Actions through the booking service:
  "Cancel with refund rule" and "Cancel with full refund" (allowed outside
  maintenance), both with a mandatory reason and audited.
- Every staff cancellation gets the status `cancelled_by_admin` and a mandatory
  reason; it frees the slot like a resident cancellation.
- Other Django admin edits are audited with before/after values (passwords and
  PINs are never stored, only the fact that they changed).

## Stage 1b: residents

- `/manage/residents/`: search, filters (active, archived, negative balance),
  add, edit (name, room, code, language), deactivate.
- Hard delete only without history (bookings, ledger, receipts, key logs).
  Otherwise anonymize: placeholders for name, room and code, unusable PIN,
  deactivated; old audit snapshots for that resident are blanked too (ids and
  amounts kept). The redaction is itself audited.
- Deactivating or anonymizing a resident with a negative balance shows the
  amount owed and needs explicit confirmation; the amount goes into the audit
  event. No automatic collection.
- Resident page: profile, balance, bookings, ledger statement (CSV export with
  formula-injection protection), receipts, key logs.
- PIN reset only through activation links (no temporary PINs).
- Manual adjustment: ledger `adjustment` with a mandatory note.

## Stage 1c: CSV import of residents

Upload → per-row preview (new / changed / unchanged / error); changed rows show
before/after per field with name changes highlighted. Nothing is written until
confirmed; then one transaction, one audit event per change. Idempotent on the
student code. Bulk activation links, exportable.

## Deployment plan (after 1c is merged)

Feature work pauses for a deployment proposal: Russian VPS, PostgreSQL, HTTPS,
nightly backups including the private media directory, web server body-size
limit equal to the file-size hard ceiling. Goal: a demo instance with fake data
tested from the dormitory network.

## Stage 2: machine maintenance and archiving

- `MachineUnavailability` (maintenance or archive; start, optional end, reason,
  refund choice, created by). A machine's state is derived from these records;
  `active=False` machines migrate to archive records.
- Timezone-aware datetimes (stored UTC, entered and shown in Moscow time). A
  slot `[s, e)` is affected when it overlaps `[start, end)` at all; half-open,
  so a period ending at 12:00 leaves the 12:00 slot free.
- End after start; start not in the past except an explicit "starting now".
  Overlapping periods on one machine are rejected; extend or end instead.
- Shared flow for maintenance, archive and extend: preview of affected future
  bookings (alert block), bookings in progress listed separately for a manual
  decision, a separate "Refund affected residents" box (ticked by default),
  then one transaction. Ending maintenance makes the machine bookable from that
  moment. No restoring archived machines.
- Residents see a highlighted notice; the grid, slot page and `book_machines`
  reject unavailable machines.

## Stage 3: sensitive settings and credit limit

- One global settings row (no per-dormitory overrides yet; read through
  `credit_limit_for(resident)` so an override is easy later): credit limit
  (100; 0 = no debt, empty = unlimited), max per receipt (2000), max credited
  per resident per rolling 30 days (5000), max uploads per resident per day
  (3, accepted uploads only), max file size (10 MB, below a server hard
  ceiling).
- Changing any of them: re-enter password, mandatory reason, audit event with
  old/new values, visible history, sanity bounds, extra confirmation for
  changes above 10× or below 1/10. No retroactive effect.
- Credit limit per individual resident (never pooled by room), checked inside
  the booking transaction.
- Debts report sorted by debt, with the date each current debt began.

## Stage 4: receipt upload with immediate credit

- Trust by default: a valid upload credits the declared amount at once. One
  transaction: file, `Receipt` (status `credited`), one credit ledger entry
  (`UNIQUE(receipt)`), audit event. The resident's row is locked so caps and
  limits cannot be raced.
- Guardrails: per-receipt max, rolling 30-day cap, daily upload limit, whole
  rubles, global duplicate refusal by SHA-256 of the original bytes
  (`UNIQUE(sha256)`). Refused uploads are audited outside the rolled-back
  transaction.
- File security: type checked by magic bytes (PDF, JPEG, PNG, WebP; HEIC
  refused), images re-encoded with Pillow (EXIF stripped), private storage
  outside public paths, random names, served only to the owner or admins with
  `nosniff` and `attachment`. Managers cannot see receipts.
- Receipts reference the resident by id only. The hash stays when a file is
  later deleted for retention, so duplicates stay blocked. No automatic
  deletion yet.

## Stage 5: receipt audit, voiding, reconciliation

- `/manage/receipts/`: filters, file viewer, the resident's balance and ledger.
  Automatic flags (repeats, large amounts, spending right after a credit,
  negative balance, earlier voids, near caps) never block anything.
- Void with mandatory reason: a `reversal` ledger entry (`UNIQUE(receipt)`),
  idempotent, may leave a negative balance (credit limit then applies).
- Reconciliation report per day, week, month and resident, with manual
  credits and adjustments in separate columns; CSV export.
- Docs for the administration: "Trust model" and "Pending policy decisions"
  (receipt retention, debt settlement on departure; receipt files usually
  contain the sender's name and stay until retention deletion).
