# Backlog

Ideas agreed as useful but not scheduled. Each needs a short plan and an
approval before work starts (docs/CLAUDE.md, Workflow).

## "English + Russian" interface option

A third language choice for foreign residents who are learning Russian: the
English interface, with the Russian term in small type under the **main
labels and buttons only** (navigation, «Записаться», «Отменить», «Баланс»…),
so they learn the words staff and notices use. Not under every sentence: that
would double the text on a phone screen. Needs a way to mark which strings
get the second line, and the same contrast and size checks as the rest.

## Calendar feed

Today each booking can be added to a calendar once (Google, Outlook, `.ics`
file). A personal feed URL (`webcal://…`) that a calendar app subscribes to
would show every booking and remove cancelled ones by itself. The URL must
contain a secret token (revocable from the resident's menu), must never
include names or rooms, and must not be guessable.

## A /manage/ page for admin accounts

Today superusers create and switch off dormitory admin and manager accounts
(docs/SUPERUSER.md, `manage.py dormitory_admin`). A page where a dormitory
admin can invite a manager would remove that step. It needs: an invitation
link instead of a password, roles limited to their own dormitory, a
confirmation step, and the change history.

## Per-dormitory rules

The money and upload rules (credit limit, receipt limits) and the login
limits are the same for every dormitory today (`GlobalSettings`). With a
second dormitory, some may need their own values. `rules.credit_limit_for()`
is the one place where an override would go; the settings page would show
which values are the dormitory's own and which are the default.
