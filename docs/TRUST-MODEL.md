# How payments are trusted (for the dormitory administration)

This page explains, without technical terms, how residents' money moves in
Dorm Laundry, what the app checks and what only a person can check, and
which decisions the administration still has to make.

## The short version

- Residents pay the administration directly (bank transfer, SBP, cash). The
  app never touches money; it only keeps the balance.
- A resident who paid sends the receipt in the app. **The balance is topped
  up at once**: residents do not wait for anyone to approve it.
- The administration **checks receipts afterwards**, against the bank
  statement. A receipt that turns out to be wrong is **voided**: the money is
  taken back from the resident's balance, with a reason everyone on the
  admin team can see.
- Every money movement is kept forever and can be traced: who, when, how
  much and why. Nothing is ever edited or deleted.

This is "trust by default": it keeps the laundry running without daily
approvals, and the checks below keep the risk small.

## What the app checks automatically

When a resident sends a receipt, the app refuses it if:

- the amount is more than the **largest amount per receipt** (2000 ₽ unless
  changed under «Настройки»);
- it would bring more than the **30-day limit** into the resident's balance
  from receipts (5000 ₽);
- the resident already sent the **daily number of receipts** (3);
- the file is too large, or is not a PDF or a picture;
- **the same file was already sent**, by this resident or anyone else.

Each refusal is written down in the change history.

The app also **marks** receipts worth a closer look. Marks never block
anything; they only help decide what to check first:

- the same amount sent again within 2 days;
- a large amount (80% of the maximum or more);
- the money spent on bookings right after the receipt;
- the resident is in debt now;
- the resident had receipts voided before;
- the resident is close to the 30-day limit.

Separately, residents can go into debt only up to the **credit limit**
(100 ₽). A voided receipt can leave a resident in debt; they then cannot
book beyond the limit until they pay.

## What only a person can check

The app cannot see the bank account, so it cannot know whether a payment
really arrived. A receipt can be edited or invented. That is why:

- the **money report** («Чеки» → «Отчёт по деньгам») adds up, for any period,
  the money from receipts and the payments recorded by admins **in separate
  columns**: compare each with the bank statement;
- each payment carries the resident's **payment purpose**
  («Стирка, комн. 301-2, код 00111598»), so a transfer on the statement can
  be matched to a resident;
- the receipt file and the resident's recent money movements are shown side
  by side on the receipt's page.

Suggested routine: once a week, open the report for the week, compare the
"Receipts" total with the bank statement, and open the marked receipts.

## Voiding a receipt

«Аннулировать чек» on the receipt's page. A reason is required (for example
"no such payment on the bank statement") and a confirmation tick. The
resident sees "receipt voided" and the amount taken back in their balance.
Voiding cannot be undone; if it was a mistake, the resident sends the
receipt again or an admin records the payment with «Изменить баланс».

## Who sees what

- **Residents** see only their own balance, bookings and receipts.
- **Admins** see residents' receipts and money in their own dormitory.
- **Key managers never see receipts or payment details.**
- Receipt files are never public: the app hands them only to the resident
  who sent them and to admins of their dormitory.

## Decisions the administration still has to make

These are not decided by the app; until they are, the app keeps everything.

1. **How long to keep receipt files.** Receipt pictures usually show the
   sender's full name and part of their card or account. Proposed: delete
   the files 12 months after upload. The amount and the file's fingerprint
   stay, so the same receipt can still never be sent twice. Automatic
   deletion is not built yet.
2. **Debts when a resident moves out.** The app shows the debt and asks for
   confirmation before turning off access or erasing personal data, but it
   does not collect anything. Who settles a remaining debt, and how?
3. **Formalities for personal data (152-FZ).** The university is the
   operator of residents' personal data; the administration confirms the
   paperwork before real data is entered.
4. **Rules for several dormitories.** The money and receipt rules are the
   same for all dormitories today; an admin of any dormitory changes them for
   all. Decide whether each dormitory should have its own.
5. **Hosting for the pilot** (a Russian VPS or the university's servers) and
   the address.
