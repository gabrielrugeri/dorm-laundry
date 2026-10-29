"""How to pay: validation of payment details, the admin editor (a sensitive
setting) and the resident page. Every detail here is generated and fake."""

import io

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff
from apps.payments import validators
from apps.payments.models import PaymentDetails

EDIT = reverse("manage:payment_details")
PAGE = reverse("payments:how_to_pay")
PASSWORD = "a-staff-password"
FAKE_BIK = "049999999"  # format only; no such bank


def inn10(first9):
    """A 10-digit INN with a correct check digit, built from 9 made-up digits."""
    weights = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    return first9 + str(sum(int(d) * w for d, w in zip(first9, weights, strict=True)) % 11 % 10)


def account_for(bik, start="40702810", rest="00000000001"):
    """A 20-digit account whose control key matches the BIK."""
    for key in range(10):
        account = f"{start}{key}{rest}"
        try:
            validators.validate_account(account, bik)
            return account
        except ValidationError:
            continue
    raise AssertionError("no key found")


# --- Validators ---------------------------------------------------------------------


def test_inn_check_digits():
    good = inn10("770000000")
    validators.validate_inn(good)
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    with pytest.raises(ValidationError):
        validators.validate_inn(bad)
    with pytest.raises(ValidationError):
        validators.validate_inn("123")


def test_account_is_checked_against_the_bik():
    account = account_for(FAKE_BIK)
    validators.validate_account(account, FAKE_BIK)
    with pytest.raises(ValidationError):
        validators.validate_account(account, "049999998")
    with pytest.raises(ValidationError):
        validators.validate_account("123", FAKE_BIK)


@pytest.mark.parametrize("raw", ["8 (900) 123-45-67", "+7 900 123 45 67", "9001234567"])
def test_phone_is_normalised(raw):
    assert validators.normalize_phone(raw) == "+79001234567"
    assert validators.format_phone("+79001234567") == "+7 900 123-45-67"


def test_wrong_phone_is_refused():
    with pytest.raises(ValidationError):
        validators.normalize_phone("12345")


# --- Admin editor ---------------------------------------------------------------------


@pytest.fixture
def boss(dormitory):
    user = make_staff(dormitory, "boss", role=roles.ADMIN)
    user.set_password(PASSWORD)
    user.save()
    return user


@pytest.fixture
def boss_client(client, boss):
    client.force_login(boss)
    client.cookies["django_language"] = "en"
    return client


def form_data(**changes):
    data = {
        "recipient": "Example Dormitory Fund",
        "bank": "Example Bank",
        "sbp_phone": "+7 900 000-00-01",
        "payment_link": "",
        "bik": "",
        "account": "",
        "inn": "",
        "purpose_prefix": "Стирка",
        "reason": "Details from the administration",
        "password": PASSWORD,
    }
    return {**data, **changes}


def qr_png():
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 0, 0)).save(out, "PNG")
    return SimpleUploadedFile("qr.png", out.getvalue(), content_type="image/png")


def test_editor_is_for_admins_only(client, dormitory, resident):
    client.force_login(resident.user)
    assert client.get(EDIT).status_code == 403
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(EDIT).status_code == 403


def test_details_are_saved_and_recorded(boss_client, dormitory):
    response = boss_client.post(EDIT, form_data())
    assert response.status_code == 302
    details = PaymentDetails.objects.get(dormitory=dormitory)
    assert details.sbp_phone == "+79000000001"
    event = AuditEvent.objects.get(action="payments.details_change")
    assert event.reason == "Details from the administration"
    assert event.after["bank"] == "Example Bank"


def test_editor_needs_password_and_reason(boss_client):
    page = boss_client.post(EDIT, form_data(password="wrong", reason=""))
    errors = page.context["form"].errors
    assert "password" in errors and "reason" in errors
    assert not PaymentDetails.objects.exists()


def test_typos_in_bank_details_are_caught(boss_client):
    good = account_for(FAKE_BIK)
    typo = good[:-1] + str((int(good[-1]) + 1) % 10)
    page = boss_client.post(EDIT, form_data(bik=FAKE_BIK, account=typo, inn="1234567890"))
    errors = page.context["form"].errors
    assert "account" in errors and "inn" in errors
    page = boss_client.post(EDIT, form_data(account=good))
    assert "bik" in page.context["form"].errors  # an account needs the BIK to be checked


def test_valid_bank_details_are_accepted(boss_client, dormitory):
    account = account_for(FAKE_BIK)
    inn = inn10("770000000")
    boss_client.post(EDIT, form_data(bik=FAKE_BIK, account=account, inn=inn))
    details = PaymentDetails.objects.get(dormitory=dormitory)
    assert (details.bik, details.account, details.inn) == (FAKE_BIK, account, inn)


def test_link_must_be_https(boss_client):
    page = boss_client.post(EDIT, form_data(payment_link="http://pay.example/"))
    assert "payment_link" in page.context["form"].errors


def test_at_least_one_way_to_pay(boss_client):
    page = boss_client.post(EDIT, form_data(sbp_phone=""))
    assert page.context["form"].non_field_errors()


def test_qr_code_is_saved_and_shown_to_residents_only(
    boss_client, dormitory, resident, other_dormitory
):
    boss_client.post(EDIT, {**form_data(), "qr_image": qr_png()})
    details = PaymentDetails.objects.get(dormitory=dormitory)
    assert details.qr_image
    qr = reverse("payments:qr")
    client = boss_client
    client.logout()
    assert client.get(qr).status_code == 404  # anonymous
    client.force_login(resident.user)
    response = client.get(qr)
    assert response.status_code == 200 and response["Content-Type"] == "image/png"
    stranger = make_staff(other_dormitory, "stranger", role=roles.ADMIN)
    client.force_login(stranger)
    assert client.get(qr).status_code == 404


# --- Resident page ----------------------------------------------------------------------


def test_page_without_details(client, resident):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    assert "has not given payment details yet" in client.get(PAGE).content.decode()


def test_page_shows_details_and_own_purpose(boss_client, client, resident, other_resident):
    resident.student_code, resident.room = "00111598", "301-2"
    resident.save()
    boss_client.post(EDIT, form_data())
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    html = client.get(PAGE).content.decode()
    assert "Стирка, комн. 301-2, код 00111598" in html
    assert "Example Bank" in html and "+7 900 000-00-01" in html
    assert 'data-copy-target="pay-purpose"' in html
    assert other_resident.student_code not in html and other_resident.room not in html
    assert reverse("receipts:new") in html


def test_balance_page_links_how_to_pay_and_receipts(client, resident):
    client.force_login(resident.user)
    html = client.get(reverse("ledger:balance")).content.decode()
    assert PAGE in html and reverse("receipts:new") in html
