# Plan: demo feedback (approved 2026-10-29)

The product owner tested the Railway demo. This records the plan that was
approved, with the recommended answers to its open questions. All rules in
`docs/CLAUDE.md` still apply (self-only CSP, ledger integrity, privacy, admin
UI principles). Each part is its own pull request with tests, ru/en strings,
`seed_demo` updates and docs.

**Order:** keys on hold → A (UX fixes, three PRs: a, b, c) → B (PWA) →
Stage 3 → Stage 4 + "How to pay" → Stage 5 → Dashboard → Stage 2
(maintenance). Stages 2–5 are described in
[admin-and-payments.md](admin-and-payments.md).

## A(a): key handling on hold

- `KEYS_ENABLED` setting (environment, default `false`). While false: no
  "Keys" in the navigation, key schedule and key actions return 404, `/staff/`
  sends admins to `/manage/` and shows managers "Not available yet".
- Code and tests stay; key tests run with the setting on.
- `docs/MVP-SPEC.md` marks key handling as on hold.

## A(b): resident UX

1. **"Add to calendar" menu** per booking group: Google Calendar and
   Outlook.com (prefilled event links, plain navigation, new tab,
   `rel="noopener noreferrer"`) and "Apple / other" (.ics). One place builds
   the event data so all three agree; one event per booking group. Event text
   has machine, time and dormitory only, never the resident's name. Check
   during implementation whether Yandex Calendar has a documented prefill link.
   *Later option, not built:* a personal calendar feed with a secret, hashed,
   revocable token (trade-offs: the URL is a password; Google refreshes every
   12–24 h; Google fetches from abroad).
2. **.ics file name** `laundry-<CODE>-YYYY-MM-DD-HH-HH-M<n>.ics`; several
   machines list every number (`M1-M3` = machines 1 and 3, `M1-M2-M3`). The
   combined multi-machine event is offered on the confirmation page right
   after booking. New `Dormitory.code` (2–8 uppercase letters/digits, unique,
   superusers only); a migration fills existing rows from the slug.
3. **Balance page grouping (display only):** adjacent ledger entries with the
   same booking group and kind become one line ("Машина 1, 29 октября
   14:00–18:00: −100 ₽") with an expandable detail. Storage stays one entry
   per slot. Pagination by display lines.
4. **Name and room** on the balance page.
5. **Identity menu** in the header ("Name · room"): My balance, language,
   log out. Staff see their username and role. The language switch moves
   there (it stays on the login page).
6. **Names:** one field, shown as stored in every language. `seed_demo` and
   the demo CSV use Cyrillic names plus two foreign residents in Latin script.
7. **Language:** no selector in the admin resident form (CSV column ignored);
   the resident's own choice is saved on their profile and in the cookie.
8. **Sessions:** residents 30 days, extended while in use (refreshed at most
   once a day); admins and managers 12 hours from login. Trade-off documented
   in `ARCHITECTURE.md`.

## A(c): admin UX

9. **Residents list:** natural sort by room (210 < 301-1 < 301-2 < 1010),
   then name; sortable column headers.
10. **"Reset PIN / login link"** replaces both actions, with the warning page.
    The old PIN keeps working until the link is used; using it sets the new
    PIN. Audited.
11. **"Change balance"** replaces "Record a payment" and "Correct the
    balance": type (Payment received / Correction), direction (Add /
    Subtract), "Amount, ₽", live preview "Баланс: 120 ₽ → 170 ₽". Note
    required for corrections. A subtracted payment is stored as a negative
    payment (kind `credit`, sign check relaxed) so reconciliation keeps it in
    the payments column.

## B: PWA

- Manifest, Apple meta tags, placeholder icons (192, 512, maskable,
  180×180 apple-touch-icon), service worker at `/sw.js` caching only the
  offline page and its assets; nothing personal is ever cached. CSP gains
  `manifest-src 'self'` and `worker-src 'self'`.
- iOS: `viewport-fit=cover` + safe-area insets, `overscroll-behavior: none`,
  `touch-action: manipulation` (pinch zoom stays), 16 px inputs, fixed bottom
  navigation for residents without layout jumps.
- Install guide only when not standalone, dismissible: iOS Safari
  illustrations, Android `beforeinstallprompt` button, in-app browsers
  (Telegram, Instagram, VK, Facebook) asked to open Safari/Chrome.
- Dark mode: colour tokens, light/dark/system switch remembered per user
  (`accounts.UserPreferences(user, theme)`) and in a cookie. *As built:* the
  server writes the choice into `<html data-theme>`, so no blocking script is
  needed; the language stays on `Resident.language` (moving it was not
  needed for anything requested). WCAG AA contrast tested for every token pair and checked on every
  screen.

## Stage 4 addition: "How to pay"

- `dorms.PaymentDetails` per dormitory: recipient, bank, SBP phone, optional
  QR image (re-saved with Pillow), optional `https://` payment link, optional
  BIK / account / INN with format and check-digit validation, payment purpose
  prefix.
- Editing is a sensitive setting (Stage 3 mechanism). Payment purpose has a
  fixed format with the admin-editable prefix: «Стирка, комн. 301-2, код
  00111598». Copy buttons on every field; linked from the balance and receipt
  pages. `seed_demo` uses obviously fake details.

## Dashboard (after Stage 5)

- Big numbers: received this month vs last month, total debt and debtors,
  occupancy this week, voided receipts this month.
- Charts as server-side SVG (no library, no CDN): occupancy heatmap
  (weekday × slot), payments per week, usage per machine; each with a text
  summary and a table.
- `seed_demo` generates eight weeks of history through the real services.
  Occupancy must leave out maintenance periods once Stage 2 lands.

## Railway demo

New seed data (Cyrillic names, history) needs a fresh database: delete and
re-add Postgres, then redeploy (`docs/DEPLOY-RAILWAY.md`, section 8).
Migrations run on the existing database without a reset.

## Decisions on the open questions

1. A subtracted payment is a negative payment (kind `credit`).
2. File names list every machine number.
3. Managers get 12-hour sessions; with keys off they see "Not available yet".
4. Calendar: Google, Outlook.com, Apple / other (.ics).
5. Payment purpose: fixed format, editable prefix.
6. Package A is split into three PRs.
