# Rollout: moving a dormitory from the Google form to the app

A checklist for the dormitory administration and whoever runs the app. Do the
steps in order; each one says how to know it is done. The words in «…» are
what the admin screens show.

## 0. Before anything: decisions

- [ ] **Dates of birth (pending policy decision).** The easiest first login
  uses the resident's date of birth as a first-time PIN (DDMMYY). The
  administration must agree to provide the dates for this purpose. What to
  tell them:
  - the date is used once, during the import, to make a hashed first-time
    PIN, and is then thrown away: it is not stored, shown or logged anywhere
    (docs/SECURITY.md);
  - the first-time PIN works only for 14 days and must be replaced by the
    resident's own PIN at the first login;
  - people close to a resident may know their birthday, so for those 14 days
    the account is only as safe as the birthday is secret; the login limits
    stop anyone from trying many dates.
  If the administration says no, leave the column out: every resident gets a
  personal login link instead (more work to hand out, nothing else changes).
- [ ] The pilot gate in `docs/plans/admin-and-payments.md` is done (the
  server, backups, `PIN_PEPPER` stored safely, HTTPS). No real data before.
- [ ] **Cut-over date** agreed: the day the Google form stops taking
  bookings. Put it on the poster's help text and announce it.
- [ ] **Help hours** agreed: where and when someone helps residents in person
  during the first two weeks (e.g. room 105, Mon–Fri 18:00–20:00).

## 1. Prepare the data

- [ ] Get the residents list from the administration as Excel. Columns:
  student code, full name, room; optionally date of birth (DD.MM.YYYY,
  formatted as **text** in Excel) and opening balance (whole rubles, minus
  for an old debt).
- [ ] Save it as CSV and import it: «Жильцы» → «Добавить много жильцов из
  файла». Read the preview: fix every row with an error in the file and
  import again (importing twice never duplicates anyone or any balance).
- [ ] Check the totals: the number of residents and the opening balances
  match the administration's list.

## 2. Poster and help

- [ ] «Настройки» → «Изменить, где получить помощь»: the help hours and place.
- [ ] «Настройки» → «Открыть плакат для печати»: print it in Russian (and in
  English for foreign residents). Hang it in the laundry and at the entrance.
- [ ] Scan the printed QR code with a phone: it opens the app.

## 3. One floor first

- [ ] Invite one floor (or one block) first, for 2–3 days. Watch for
  questions at the help hours and in «Обзор».
- [ ] Fix what confused people (wording on the poster, missing residents)
  before inviting everyone.

## 4. Parallel run (1–2 weeks)

- [ ] Everyone is invited. The Google form stays open, but the app is the
  main way to book; staff copy any form bookings into the app by hand, so
  both show the same slots.
- [ ] Every day: residents list, filter «Вход» → «срок первого PIN-кода
  истёк» and «PIN-кода ещё нет». Give these residents a login link
  (resident's page → «Ещё» → «Сбросить PIN / ссылка для входа»).

## 5. Cut-over

- [ ] On the agreed date, close the Google form and replace it with a link
  to the app.
- [ ] **For anyone who missed it:** a resident who cannot log in (no date of
  birth, first-time PIN expired, forgot the PIN) asks at the help hours and
  gets a login link. The link works once, for 7 days.
- [ ] After two weeks, check «Вход» → everyone not yet logged in, and ask the
  floor heads to remind them.
