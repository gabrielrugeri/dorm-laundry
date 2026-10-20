"""Resident pages in the admin area. Every name and code here is fake."""

from datetime import timedelta

import pytest
from django.urls import reverse

from apps.accounts import roles
from apps.accounts.models import Resident
from apps.audit.models import AuditEvent
from apps.bookings import services as booking_services
from apps.bookings.availability import local_today
from apps.bookings.models import Booking
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry
from conftest import make_resident

LIST = reverse("manage:residents")


@pytest.fixture
def boss(dormitory):
    return make_staff(dormitory, "boss", role=roles.ADMIN)


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    client.cookies["django_language"] = "en"
    return client


def url(name, resident, **kwargs):
    return reverse(f"manage:{name}", kwargs={"pk": resident.pk, **kwargs})


def owe(resident, amount):
    LedgerEntry.objects.create(resident=resident, kind="adjustment", amount=-amount, note="test")


def listed(client, **params):
    return [r.pk for r in client.get(LIST, params).context["page"]]


# --- List ----------------------------------------------------------------------------


def test_list_filters_and_search(boss_client, resident, other_resident, dormitory, other_dormitory):
    owe(other_resident, 70)
    off = make_resident(dormitory, "S0003", name="Pavel Demin", room="303")
    off.user.is_active = False
    off.user.save()
    make_resident(other_dormitory, "S0009", name="Elsewhere Person", room="909")

    assert sorted(listed(boss_client)) == sorted([resident.pk, other_resident.pk])
    assert listed(boss_client, show="debt") == [other_resident.pk]
    assert listed(boss_client, show="off") == [off.pk]
    assert listed(boss_client, q="testov") == [resident.pk]
    assert listed(boss_client, q="202") == [other_resident.pk]
    assert listed(boss_client, q="s0002") == [other_resident.pk]
    assert listed(boss_client, q="Elsewhere") == []  # other dormitory


def test_list_shows_balance_and_debt(boss_client, other_resident):
    owe(other_resident, 70)
    html = boss_client.get(LIST, {"show": "debt"}).content.decode()
    assert "−70 RUB" in html or "-70 RUB" in html
    assert "owes money" in html


# --- Profile -------------------------------------------------------------------------


def test_profile_answers_good_standing_at_a_glance(boss_client, resident):
    owe(resident, 120)
    response = boss_client.get(url("resident", resident))
    assert response.context["balance"] == -120
    assert response.context["debt_since"] is not None
    html = response.content.decode()
    assert "Ivan Testov" in html and "Room 101" in html
    assert "Owes money since" in html
    assert "Record a payment" in html  # the one primary action


def test_profile_uses_plain_language(boss_client, resident, make_booking):
    make_booking()
    owe(resident, 10)
    html = boss_client.get(url("resident", resident)).content.decode().lower()
    for word in ("ledger", "adjustment", "audit", "utc", "json", "cancelled_by_admin"):
        assert word not in html, word


def test_buttons_exist_only_when_the_action_is_allowed(boss_client, resident, make_booking):
    html = boss_client.get(url("resident", resident)).content.decode()
    assert url("resident_delete", resident) in html  # no history yet
    assert url("resident_login_link", resident) in html

    make_booking()
    resident.user.is_active = False
    resident.user.save()
    html = boss_client.get(url("resident", resident)).content.decode()
    assert url("resident_delete", resident) not in html
    assert url("resident_login_link", resident) not in html
    assert url("resident_deactivate", resident) not in html
    assert url("resident_reactivate", resident) in html


def test_erased_resident_has_no_actions(boss_client, boss, resident):
    from apps.accounts import services

    services.anonymize(actor=boss, resident=resident)
    response = boss_client.get(url("resident", resident))
    html = response.content.decode()
    assert "Former resident" in html
    assert "Ivan Testov" not in html
    assert url("resident_payment", resident) not in html
    assert boss_client.get(url("resident_edit", resident)).status_code == 404
    assert boss_client.get(url("resident_payment", resident)).status_code == 404


# --- Add and edit --------------------------------------------------------------------


def test_add_resident(boss_client, dormitory):
    data = {"full_name": "Olga Primerova", "room": "214", "student_code": "S7777", "language": "ru"}
    response = boss_client.post(reverse("manage:resident_add"), data)
    resident = Resident.objects.get(student_code="S7777")
    assert response.url == url("resident", resident)
    assert resident.dormitory == dormitory
    assert AuditEvent.objects.filter(action="resident.create").count() == 1


def test_student_codes_are_unique_in_the_dormitory(boss_client, resident):
    data = {"full_name": "Copy", "room": "1", "student_code": "s0001", "language": "ru"}
    response = boss_client.post(reverse("manage:resident_add"), data)
    assert response.context["form"].errors["student_code"]


def test_edit_resident(boss_client, resident):
    data = {"full_name": "Ivan Testov", "room": "305", "student_code": "S0001", "language": "en"}
    boss_client.post(url("resident_edit", resident), data)
    resident.refresh_from_db()
    assert (resident.room, resident.language) == ("305", "en")
    assert AuditEvent.objects.get().action == "resident.update"


# --- Money ---------------------------------------------------------------------------


def test_record_payment(boss_client, boss, resident):
    page = boss_client.post(url("resident_payment", resident), {"amount": 300, "note": ""})
    assert page.context["form"].errors["note"]
    assert (
        boss_client.post(url("resident_payment", resident), {"amount": -5, "note": "x"}).status_code
        == 200
    )
    boss_client.post(url("resident_payment", resident), {"amount": 300, "note": "Cash"})
    entry = LedgerEntry.objects.get()
    assert (entry.kind, entry.amount, entry.note, entry.created_by) == ("credit", 300, "Cash", boss)
    assert AuditEvent.objects.get().action == "ledger.payment"


def test_correct_balance(boss_client, resident):
    page = boss_client.post(url("resident_correction", resident), {"amount": 0, "note": "x"})
    assert page.context["form"].errors["amount"]
    boss_client.post(
        url("resident_correction", resident), {"amount": -40, "note": "Double payment"}
    )
    assert LedgerEntry.objects.balance(resident) == -40
    assert AuditEvent.objects.get().action == "ledger.correction"


# --- Login ---------------------------------------------------------------------------


def test_login_link_is_shown_once_and_never_stored(boss_client, resident):
    assert boss_client.get(url("resident_login_link", resident)).status_code == 405
    response = boss_client.post(url("resident_login_link", resident))
    link = response.context["link"]
    assert "/account/activate/" in link
    assert link not in str(list(AuditEvent.objects.values()))
    assert AuditEvent.objects.get().action == "resident.activation_link"


def test_reset_pin_needs_confirmation(boss_client, resident):
    boss_client.get(url("resident_reset_pin", resident))
    resident.user.refresh_from_db()
    assert resident.user.has_usable_password()
    response = boss_client.post(url("resident_reset_pin", resident))
    resident.user.refresh_from_db()
    assert not resident.user.has_usable_password()
    assert response.context["after_reset"]


# --- Access, erase, delete -----------------------------------------------------------


def test_turn_off_access_with_debt_needs_the_checkbox(boss_client, resident):
    owe(resident, 90)
    page = boss_client.get(url("resident_deactivate", resident))
    assert "This resident owes 90 RUB." in page.content.decode()
    boss_client.post(url("resident_deactivate", resident), {})
    resident.user.refresh_from_db()
    assert resident.user.is_active

    boss_client.post(url("resident_deactivate", resident), {"confirm_debt": "on"})
    resident.user.refresh_from_db()
    assert not resident.user.is_active
    assert AuditEvent.objects.get().after == {"balance": -90, "debt_confirmed": True}

    boss_client.post(url("resident_reactivate", resident))
    resident.user.refresh_from_db()
    assert resident.user.is_active


def test_turn_off_without_debt_has_no_checkbox(boss_client, resident):
    page = boss_client.get(url("resident_deactivate", resident))
    assert page.context["debt_form"] is None
    boss_client.post(url("resident_deactivate", resident), {})
    resident.user.refresh_from_db()
    assert not resident.user.is_active


def test_erase_personal_data(boss_client, resident):
    owe(resident, 10)
    boss_client.post(url("resident_erase", resident), {"confirm_debt": "on"})
    resident.refresh_from_db()
    assert resident.is_anonymized and resident.full_name == ""


def test_delete_only_without_history(boss_client, resident, other_resident, make_booking):
    make_booking()
    assert boss_client.get(url("resident_delete", resident)).status_code == 404
    boss_client.post(url("resident_delete", other_resident))
    assert not Resident.objects.filter(pk=other_resident.pk).exists()


# --- Bookings ------------------------------------------------------------------------


@pytest.fixture
def upcoming(resident, machine, slot, dormitory):
    LedgerEntry.objects.create(resident=resident, kind="credit", amount=50, note="x")
    day = local_today(dormitory) + timedelta(days=2)
    return booking_services.book_slots(resident, machine, day, [slot])[0]


def test_cancel_booking_from_the_profile(boss_client, resident, upcoming):
    cancel = url("resident_cancel_booking", resident, group_id=upcoming.group_id)
    assert cancel in boss_client.get(url("resident", resident)).content.decode()
    page = boss_client.post(cancel, {"reason": "", "refund": "full"})
    assert page.context["form"].errors["reason"]
    boss_client.post(cancel, {"reason": "Machine broken", "refund": "full"})
    upcoming.refresh_from_db()
    assert upcoming.status == Booking.Status.CANCELLED_BY_ADMIN
    assert LedgerEntry.objects.balance(resident) == 50
    assert boss_client.get(cancel).status_code == 404  # nothing left to cancel


# --- Export --------------------------------------------------------------------------


def test_payment_history_csv(boss_client, resident):
    LedgerEntry.objects.create(
        resident=resident, kind="credit", amount=200, note="=HYPERLINK(evil)"
    )
    owe(resident, 30)
    response = boss_client.get(url("resident_history_csv", resident))
    assert response["Content-Type"].startswith("text/csv")
    body = response.content.decode("utf-8-sig")
    lines = body.strip().splitlines()
    assert lines[0].startswith("Date;What;")
    assert "'=HYPERLINK(evil)" in body  # neutralised
    assert lines[1].split(";")[2:4] == ["200", "200"]
    assert lines[2].split(";")[2:4] == ["-30", "170"]


# --- Permissions ---------------------------------------------------------------------


ACTION_NAMES = [
    "resident",
    "resident_edit",
    "resident_payment",
    "resident_correction",
    "resident_reset_pin",
    "resident_deactivate",
    "resident_erase",
    "resident_delete",
    "resident_history_csv",
]


@pytest.mark.parametrize("name", ACTION_NAMES)
def test_managers_and_residents_cannot(client, dormitory, resident, other_resident, name):
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(url(name, resident)).status_code == 403
    client.force_login(other_resident.user)
    assert client.get(url(name, resident)).status_code == 403


@pytest.mark.parametrize("name", ACTION_NAMES)
def test_admins_of_other_dormitories_get_404(client, other_dormitory, resident, name):
    client.force_login(make_staff(other_dormitory, "stranger", role=roles.ADMIN))
    assert client.get(url(name, resident)).status_code == 404


def test_admin_pages_are_in_russian_by_default(client, boss, resident):
    client.force_login(boss)  # no language cookie: Russian is the default
    owe(resident, 40)
    html = client.get(url("resident", resident)).content.decode()
    assert "Внести оплату" in html and "Комната 101" in html and "Долг с" in html
    assert "Жильцы" in html and "Журнал изменений" in html  # navigation
    erase = client.get(url("resident_erase", resident)).content.decode()
    assert "Имя, комната и студенческий код будут удалены везде" in erase
    assert "Долг жильца: 40" in erase
