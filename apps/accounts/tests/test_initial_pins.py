"""First-time PINs from the date of birth, through the residents import.
Every name, code and date here is fake."""

import logging
from datetime import date, timedelta

import pytest
from django.core import serializers
from django.urls import reverse
from django.utils import timezone

from apps.accounts import initial_pins, pins, roles
from apps.accounts.models import Resident
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff

TODAY = date(2026, 11, 3)
LOGIN = reverse("accounts:login")
CHANGE_PIN = reverse("accounts:change_pin")
IMPORT = reverse("manage:resident_import")
CONFIRM = reverse("manage:resident_import_confirm")
CANCEL = reverse("manage:resident_import_cancel")
# The fake date of birth and every way it could leak.
BORN = "05.03.2004"
DATE_FORMS = ("05.03.2004", "2004-03-05", "05/03/2004", "050304", "2004, 3, 5")
INITIAL = "050304"


@pytest.fixture(autouse=True)
def login_dormitory(settings, dormitory):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug


@pytest.fixture
def boss_client(client, dormitory):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    client.cookies["django_language"] = "en"
    return client


def csv_file(*rows, header="Student code;Full name;Room;Date of birth;Opening balance"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    text = "\n".join([header, *(";".join(row) for row in rows)])
    return SimpleUploadedFile("residents.csv", text.encode("utf-8"), content_type="text/csv")


def upload(client, *rows, **kwargs):
    response = client.post(IMPORT, {"file": csv_file(*rows, **kwargs)})
    assert response.status_code == 200
    return response


def import_rows(client, *rows, renew=False, **kwargs):
    token = upload(client, *rows, **kwargs).context["token"]
    data = {"token": token}
    if renew:
        data["renew_initial_pins"] = "on"
    assert client.post(CONFIRM, data).status_code == 302


def log_in(client, code, pin):
    return client.post(LOGIN, {"username": code, "password": pin})


# --- Parsing ------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["05.03.2004", "2004-03-05", "05/03/2004", " 05.03.2004 "])
def test_accepted_formats_give_ddmmyy(text):
    born = initial_pins.parse_birth_date(text, TODAY)
    assert born == date(2004, 3, 5)
    assert initial_pins.pin_from_date(born) == INITIAL


@pytest.mark.parametrize(
    "text",
    [
        "38051",  # an Excel day number
        "38051.0",
        "05.03.04",  # two-digit year
        "03/25/2004",  # month/day
        "31.02.2004",  # does not exist
        "2004-13-05",
        "05.03.2020",  # 6 years old
        "05.03.1900",  # 126 years old
        "5.3.2004",
        "05-03-2004",
        "March 5, 2004",
        "2004/03/05",
    ],
)
def test_anything_else_is_refused_never_guessed(text):
    with pytest.raises(initial_pins.BadDate) as refused:
        initial_pins.parse_birth_date(text, TODAY)
    assert text.strip() not in str(refused.value)  # the message never repeats it


# --- The import ---------------------------------------------------------------------


def test_preview_masks_dates_and_reports_errors_by_line(boss_client):
    response = upload(
        boss_client,
        ("S1", "Ivan Testov", "101", BORN, ""),
        ("S2", "Anna Testova", "102", "03/25/2004", ""),
        ("S3", "Petr Testov", "103", "", ""),
    )
    html = response.content.decode()
    for form in DATE_FORMS + ("03/25/2004",):
        assert form not in html
    result = response.context["result"]
    assert [r.status for r in result.rows] == ["new", "error", "new"]
    assert "month/day" in result.rows[1].errors[0]
    assert "logs in with the date of birth" in html and "login link" in html


def test_only_hashes_are_kept_never_the_date_or_the_file(boss_client, caplog):
    caplog.set_level(logging.DEBUG)
    response = upload(boss_client, ("S1", "Ivan Testov", "101", BORN, "150"))
    session = boss_client.session
    assert "resident_import_file" not in session
    stored = str(dict(session.items()))
    for form in DATE_FORMS:
        assert form not in stored
    boss_client.post(CONFIRM, {"token": response.context["token"]})
    assert "resident_import_rows" not in boss_client.session

    # Nowhere in the database (every table, sessions and history included) or the logs.
    from django.apps import apps

    dump = "".join(
        serializers.serialize("json", model.objects.all())
        for model in apps.get_models()
        if model._meta.managed
    )
    for form in DATE_FORMS:
        assert form not in dump, form
        assert form not in caplog.text
    user = Resident.objects.get(student_code="S1").user
    assert user.password.startswith("pin_pbkdf2_sha256$")
    assert pins.check_pin(user, INITIAL)


def test_cancel_forgets_the_preview(boss_client):
    upload(boss_client, ("S1", "Ivan Testov", "101", BORN, ""))
    assert "resident_import_rows" in boss_client.session
    boss_client.post(CANCEL)
    assert "resident_import_rows" not in boss_client.session
    assert not Resident.objects.exists()


def test_initial_pin_set_is_audited_without_the_date(boss_client):
    import_rows(boss_client, ("S1", "Ivan Testov", "101", BORN, ""))
    event = AuditEvent.objects.get(action="resident.initial_pin")
    text = str(event.before) + str(event.after) + event.reason + event.target_repr
    for form in DATE_FORMS:
        assert form not in text
    resident = Resident.objects.get(student_code="S1")
    assert resident.must_change_pin
    assert resident.activation() == Resident.Activation.PENDING


def test_no_date_means_no_initial_pin_but_a_link(boss_client):
    import_rows(boss_client, ("S1", "Ivan Testov", "101", "", ""))
    resident = Resident.objects.get(student_code="S1")
    assert not resident.user.has_usable_password()
    assert not resident.must_change_pin
    assert resident.activation() == Resident.Activation.NONE
    done = boss_client.get(reverse("manage:resident_import_done"))
    assert len(done.context["new_residents"]) == 1  # needs a login link


# --- First login and the forced change ------------------------------------------------


@pytest.fixture
def imported(boss_client):
    import_rows(boss_client, ("S1", "Ivan Testov", "101", BORN, ""))
    boss_client.logout()
    return Resident.objects.get(student_code="S1")


def test_first_login_then_must_choose_a_pin_before_anything_else(client, imported):
    assert log_in(client, "S1", INITIAL).status_code == 302
    assert AuditEvent.objects.filter(action="resident.initial_pin_login").count() == 1
    for url in (reverse("core:home"), reverse("ledger:balance"), reverse("bookings:mine")):
        response = client.get(url)
        assert response.status_code == 302 and response.url == CHANGE_PIN
    page = client.get(CHANGE_PIN)
    assert page.status_code == 200 and page.context["forced"]

    response = client.post(CHANGE_PIN, {"current": INITIAL, "pin1": "482913", "pin2": "482913"})
    assert response.status_code == 302
    imported.refresh_from_db()
    assert not imported.must_change_pin and imported.initial_pin_expires_at is None
    assert imported.activation() == Resident.Activation.ACTIVATED
    assert client.get(reverse("bookings:mine")).status_code == 200
    assert AuditEvent.objects.filter(action="resident.initial_pin_changed").count() == 1
    client.logout()
    assert log_in(client, "S1", INITIAL).status_code == 200  # the first PIN is gone
    assert log_in(client, "S1", "482913").status_code == 302


def test_new_pin_equal_to_the_initial_one_is_refused(client, imported):
    log_in(client, "S1", INITIAL)
    response = client.post(CHANGE_PIN, {"current": INITIAL, "pin1": INITIAL, "pin2": INITIAL})
    assert response.status_code == 200
    assert response.context["form"].has_error("pin1")
    imported.refresh_from_db()
    assert imported.must_change_pin


def test_new_pin_follows_the_normal_rules(client, imported):
    log_in(client, "S1", INITIAL)
    response = client.post(CHANGE_PIN, {"current": INITIAL, "pin1": "123456", "pin2": "123456"})
    assert response.context["form"].has_error("pin1", "pin_trivial")


def test_only_the_initial_pin_is_exempt_from_the_easy_pin_rule(boss_client, client):
    import_rows(boss_client, ("S1", "Ivan Testov", "101", "11.11.2000", ""))
    boss_client.logout()
    assert log_in(client, "S1", "111100").status_code == 302


def test_wrong_dates_count_toward_the_lock(client, imported):
    for day in range(10, 15):  # five wrong dates
        log_in(client, "S1", f"{day:02d}0304")
    assert log_in(client, "S1", INITIAL).status_code == 200  # locked


# --- Expiry -------------------------------------------------------------------------


def test_expired_initial_pin_is_refused_even_without_the_cleanup(client, imported, monkeypatch):
    later = timezone.now() + timedelta(days=15)
    monkeypatch.setattr(timezone, "now", lambda: later)
    response = log_in(client, "S1", INITIAL)
    assert response.status_code == 200
    assert (
        "Invalid student code or PIN" in response.content.decode()
        or response.context["form"].errors
    )
    imported.refresh_from_db()
    assert imported.user.has_usable_password()  # the clean-up never ran
    assert imported.activation(later) == Resident.Activation.EXPIRED


def test_cleanup_removes_expired_hashes_only(client, boss_client, monkeypatch):
    import_rows(
        boss_client,
        ("S1", "Ivan Testov", "101", BORN, ""),
        ("S2", "Anna Testova", "102", "06.04.2003", ""),
    )
    fresh = Resident.objects.get(student_code="S2")
    fresh.initial_pin_expires_at = timezone.now() + timedelta(days=30)
    fresh.save()
    later = timezone.now() + timedelta(days=15)
    assert initial_pins.expire_old(later) == 1
    expired = Resident.objects.get(student_code="S1")
    assert not expired.user.has_usable_password()
    assert expired.activation(later) == Resident.Activation.EXPIRED
    fresh.refresh_from_db()
    assert fresh.user.has_usable_password()


def test_expiry_is_configurable_by_superusers(boss_client):
    from apps.dorms.models import GlobalSettings

    GlobalSettings.objects.filter(pk=1).update(initial_pin_days=3)
    import_rows(boss_client, ("S1", "Ivan Testov", "101", BORN, ""))
    resident = Resident.objects.get(student_code="S1")
    left = resident.initial_pin_expires_at - timezone.now()
    assert timedelta(days=2, hours=23) < left <= timedelta(days=3)


# --- Importing again ----------------------------------------------------------------


def test_reimport_never_touches_a_resident_who_chose_their_pin(boss_client, client):
    import_rows(boss_client, ("S1", "Ivan Testov", "101", BORN, ""))
    resident = Resident.objects.get(student_code="S1")
    pins.set_pin(resident.user, "482913")
    resident.user.save()
    initial_pins.clear(resident)
    import_rows(boss_client, ("S1", "Ivan Testov", "101", BORN, ""), renew=True)
    resident.refresh_from_db()
    assert pins.check_pin(resident.user, "482913")
    assert not resident.must_change_pin
    assert AuditEvent.objects.filter(action="resident.initial_pin").count() == 1


def test_reimport_renews_a_pending_pin_only_when_ticked(boss_client):
    import_rows(boss_client, ("S1", "Ivan Testov", "101", BORN, ""))
    first = Resident.objects.get(student_code="S1").user.password
    preview = upload(boss_client, ("S1", "Ivan Testov", "101", BORN, ""))
    assert len(preview.context["result"].renewable_rows) == 1
    assert 'name="renew_initial_pins"' in preview.content.decode()
    assert 'name="renew_initial_pins" checked' not in preview.content.decode()
    boss_client.post(CONFIRM, {"token": preview.context["token"]})  # not ticked
    assert Resident.objects.get(student_code="S1").user.password == first
    import_rows(boss_client, ("S1", "Ivan Testov", "101", BORN, ""), renew=True)
    assert Resident.objects.get(student_code="S1").user.password != first
    assert AuditEvent.objects.filter(action="resident.initial_pin").count() == 2


def test_an_activation_link_replaces_a_pending_initial_pin(client, imported):
    from apps.accounts.forms import SetPinForm

    form = SetPinForm(imported.user, {"pin1": "482913", "pin2": "482913"})
    assert form.is_valid()
    form.save()
    imported.refresh_from_db()
    assert not imported.must_change_pin
    assert imported.activation() == Resident.Activation.ACTIVATED


# --- Activation status in the residents list ---------------------------------------


def test_residents_list_filters_by_login_status(boss_client, monkeypatch):
    from conftest import make_resident

    import_rows(
        boss_client,
        ("S1", "Pending Person", "101", BORN, ""),
        ("S2", "Link Person", "102", "", ""),
        ("S3", "Expired Person", "103", "06.04.2003", ""),
    )
    expired = Resident.objects.get(student_code="S3")
    expired.initial_pin_expires_at = timezone.now() - timedelta(minutes=1)
    expired.save()
    make_resident(Resident.objects.first().dormitory, "S4", name="Active Person")
    url = reverse("manage:residents")
    for status, name in (
        ("pending", "Pending Person"),
        ("none", "Link Person"),
        ("expired", "Expired Person"),
        ("activated", "Active Person"),
    ):
        html = boss_client.get(url, {"login": status}).content.decode()
        others = {"Pending Person", "Link Person", "Expired Person", "Active Person"} - {name}
        assert name in html
        assert not any(other in html for other in others), status
    everyone = boss_client.get(url).content.decode()
    assert "first-time PIN expired" in everyone


def test_login_page_explains_the_first_login(client, db):
    client.cookies["django_language"] = "en"
    html = client.get(LOGIN).content.decode()
    assert "date of birth as DDMMYY" in html


def test_too_many_dates_in_one_file_is_refused(boss_client):
    from apps.accounts import importing

    rows = [
        (f"S{n}", f"Person {n}", "101", BORN, "") for n in range(importing.MAX_INITIAL_PINS + 1)
    ]
    response = boss_client.post(IMPORT, {"file": csv_file(*rows)})
    assert "split it into smaller files" in response.content.decode()
    assert "resident_import_rows" not in boss_client.session
