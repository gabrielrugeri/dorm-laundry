# MVP specification

Goal: a working, deployed demo (with fake data) that the dormitory administration can try on their phones, to approve a pilot.

## Problems being solved
1. Double-booking / overwritten reservations (today: Google Form + spreadsheet).
2. Hard to see availability at a glance.
3. No payment control or proof of payment tied to usage.
4. Key pick-up/return is tracked in a paper notebook.

## In scope (MVP)
**Resident**
- Log in with student code + personal PIN (set on first access via an activation link/code issued by admin).
- Availability grid: day × time slot, showing number of free machines per slot (7 days ahead, configurable).
- Book a machine for one slot, or for 2+ consecutive slots on the same machine (one booking per slot, 50 RUB each).
- Cancel a booking (rule: up to X hours before start gets a refund; X configurable, default 2h).
- "My bookings" list, with "Add to calendar" (.ics) after booking.
- Balance screen: current balance and transaction history.
- Language switch RU/EN. Mobile-first, installable PWA.

**Manager (keys)**
- Today's view by time: which machine, which slot, who (name + room) should be picking up the key.
- One-tap "key taken" / "key returned" with automatic timestamp; optional note.
- Shows overdue returns.

**Admin**
- Manage residents (import from CSV: code, name, room), reset PIN, deactivate.
- Credit balance manually (after confirming payment received), with a note; all as ledger transactions.
- View/modify/cancel any booking; see key log.
- Django admin may be used for the first version, with a simple custom dashboard if time allows.

**Platform**
- Multi-dormitory data model (only one dormitory is configured in the pilot).
- Seed command with fake demo data.
- Deployed on a server reachable from inside Russia without VPN; tested from the dorm network.

## Out of scope (later phases)
- Receipt upload and AI/OCR pre-screening (Phase 4). In MVP the admin credits balance manually. *Optional stretch:* resident uploads a receipt image, admin approves and credits.
- Push/e-mail notifications.
- Online payment integration.
- Reports/analytics.
- Other dormitories.

## Key rules
- A machine/slot can have at most one active booking (DB constraint).
- Booking requires balance ≥ price; price is deducted at booking, refunded on valid cancellation.
- Consecutive booking is atomic: either all selected slots are booked or none.
- Residents cannot see other residents' names or rooms. No lookup by student code.
- Slots are configured per dormitory (`TimeSlot`: start time, duration 2h). **Open question: exact slot hours.**

## Data model (draft)
- `Dormitory(name, timezone, price_per_slot)`
- `TimeSlot(dormitory, start_time, duration_minutes)`
- `Machine(dormitory, label, active)`
- `Resident(user, dormitory, student_code, full_name, room, language)`
- `Booking(machine, date, slot, resident, status[active|cancelled|completed], group_id, created_at)` — unique on active (machine, date, slot)
- `LedgerEntry(resident, amount, kind[credit|booking|refund|adjustment], booking?, note, created_by, created_at)`
- `KeyLog(booking, taken_at, returned_at, recorded_by, note)`
- Roles via Django groups: resident, manager, admin.

## Screens
1. Login / first-time activation
2. Availability grid (home)
3. Booking confirmation (select consecutive slots, machine choice)
4. My bookings (+ .ics)
5. Balance and history
6. Manager: today's key schedule
7. Admin: residents, credits, bookings, key log

## Acceptance criteria
- Two phones booking the same machine/slot at the same moment: exactly one succeeds.
- Booking 2 consecutive slots shows one confirmation and charges 100 RUB.
- A resident cannot find another resident's name or room through any screen or URL.
- The manager can tell from the "today" screen who has the key at any given hour.
- Works on a mobile browser in RU and EN, with no requests to third-party domains (check the browser network tab).
- Loads and works from the dormitory Wi-Fi without VPN.

## Demo plan for the administration
- Deployed demo URL with fake residents and a short guided scenario (book, cancel, manager flow, admin credit).
- One-page proposal: problem, demo, pilot (1 dormitory, 4 weeks), what the administration needs to provide (resident list, slot hours, hosting preference), data handling and privacy.
- Pilot success measures: zero double-bookings, % of bookings paid via balance, manager time spent logging keys.

## Open questions
- Exact slot hours and days of operation?
- Cancellation/refund policy the administration accepts?
- Maximum number of consecutive slots in one booking? (No limit in the MVP.)
- Who confirms payments and how is balance topped up (bank transfer, cash at the desk)?
- Hosting: our own server vs. university infrastructure? Personal-data requirements for Russia (152-FZ)?
- Current notebook format used by the manager (photo of a page would help).
