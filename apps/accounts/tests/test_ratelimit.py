"""Login limits per account and per address (apps/accounts/ratelimit.py).
Every name and code here is fake."""

import pytest
from django.forms.forms import NON_FIELD_ERRORS
from django.test import Client
from django.urls import reverse

from apps.accounts import ratelimit
from apps.dorms.models import GlobalSettings

PIN = "123456"
WRONG = "999999"
LOGIN = reverse("accounts:login")
DORM_ADDRESS = "203.0.113.10"


@pytest.fixture(autouse=True)
def setup(settings, dormitory, monkeypatch):
    settings.DEFAULT_DORMITORY_SLUG = dormitory.slug
    settings.CLIENT_IP_HEADER = "X-Real-IP"


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(ratelimit, "_now", clock)
    return clock


def post_login(client, code, pin, address=DORM_ADDRESS):
    return client.post(LOGIN, {"username": code, "password": pin}, HTTP_X_REAL_IP=address)


def error_code(response):
    form = response.context and response.context.get("form")
    if form is None:
        return None
    for code in ("locked", "wait", "invalid_login"):
        if form.has_error(NON_FIELD_ERRORS, code):
            return code
    return None


def logged_in(response):
    return response.status_code == 302


# --- Per account ----------------------------------------------------------------------


def test_account_locked_after_five_wrong_pins_even_from_another_address(client, resident, clock):
    for n in range(5):
        post_login(client, resident.student_code, WRONG, address=f"198.51.100.{n}")
    response = post_login(client, resident.student_code, PIN, address="192.0.2.1")
    assert not logged_in(response)
    assert error_code(response) == "locked"
    clock.advance(61)
    assert logged_in(post_login(client, resident.student_code, PIN))


def test_each_lock_lasts_twice_as_long_up_to_thirty_minutes(client, resident, clock):
    expected = [60, 120, 240, 480, 960, 1800, 1800]
    for seconds in expected:
        for _ in range(5):
            post_login(client, resident.student_code, WRONG, address="198.51.100.1")
        state = ratelimit.check(resident.student_code, None)
        assert state.reason == ratelimit.Refusal.ACCOUNT_LOCKED
        assert state.seconds == seconds
        clock.advance(seconds)
        assert ratelimit.check(resident.student_code, None) is None


def test_unknown_codes_are_locked_exactly_like_real_ones(client, resident, clock):
    for code in ("NOSUCHCODE", resident.student_code):
        for _ in range(5):
            post_login(client, code, WRONG, address="198.51.100.1")
    real = post_login(client, resident.student_code, PIN, address="198.51.100.2")
    unknown = post_login(client, "NOSUCHCODE", PIN, address="198.51.100.2")
    assert error_code(real) == error_code(unknown) == "locked"


def test_success_starts_the_account_over(client, resident, clock):
    for _ in range(4):
        post_login(client, resident.student_code, WRONG)
    assert logged_in(post_login(client, resident.student_code, PIN))
    client.logout()
    for _ in range(4):
        post_login(client, resident.student_code, WRONG)
    assert logged_in(post_login(client, resident.student_code, PIN))


def test_a_locked_account_is_never_checked(client, resident, clock, monkeypatch):
    from apps.accounts import pins

    for _ in range(5):
        post_login(client, resident.student_code, WRONG)
    checked = []
    monkeypatch.setattr(pins, "check_pin", lambda *a: checked.append(a) or True)
    post_login(client, resident.student_code, PIN)
    assert checked == []


def test_error_messages_are_generic(client, resident, clock):
    wrong = post_login(client, resident.student_code, WRONG).content.decode()
    unknown = post_login(client, "NOSUCHCODE", WRONG).content.decode()
    assert "Неверный" in wrong or "Invalid" in wrong
    for page in (wrong, unknown):
        assert "не существует" not in page and "does not exist" not in page


# --- Per address ----------------------------------------------------------------------


def test_an_address_gets_short_waits_then_is_blocked_after_the_hourly_limit(client, db, clock):
    GlobalSettings.objects.filter(pk=1).update(
        login_address_free_failures=10, login_address_hourly_limit=100
    )
    for n in range(10):
        post_login(client, f"X{n}", WRONG)
        clock.advance(1)
    # Over the free amount: an attempt right after a failure has to wait.
    post_login(client, "X10", WRONG)
    response = post_login(client, "X11", WRONG)
    assert error_code(response) == "wait"
    clock.advance(5)
    assert error_code(post_login(client, "X12", WRONG)) == "invalid_login"
    # The hourly limit blocks the address, whatever the waits.
    for n in range(200):
        clock.advance(11)
        post_login(client, f"Y{n}", WRONG)
    assert error_code(post_login(client, "Z", WRONG)) == "locked"
    other = post_login(client, "Z", WRONG, address="192.0.2.99")
    assert error_code(other) == "invalid_login"  # another address is not affected
    clock.advance(60 * 60)
    assert error_code(post_login(client, "Z", WRONG)) == "invalid_login"


def test_waits_never_exceed_the_longest_wait(client, db, clock):
    for n in range(500):
        clock.advance(11)
        post_login(client, f"X{n}", WRONG)
    refusal = ratelimit.check("ANY", _request(DORM_ADDRESS))
    assert refusal is None or refusal.seconds <= 10


def _request(address):
    from django.test import RequestFactory

    return RequestFactory().post(LOGIN, HTTP_X_REAL_IP=address)


def test_300_residents_behind_one_address_with_typos_all_get_in(db, dormitory, clock):
    """The whole dormitory shares one internet address. In one busy hour,
    300 residents each mistype their PIN once, then type it right. Everyone
    gets in; at worst someone is asked to wait a few seconds once."""
    from conftest import make_resident

    residents = [make_resident(dormitory, f"S{n:04d}") for n in range(300)]
    waits = []
    for resident in residents:
        client = Client()
        assert error_code(post_login(client, resident.student_code, "000111")) == "invalid_login"
        clock.advance(4)  # notices the typo, types again
        response = post_login(client, resident.student_code, PIN)
        if not logged_in(response):
            assert error_code(response) == "wait"
            refusal = ratelimit.check(resident.student_code, _request(DORM_ADDRESS))
            waits.append(refusal.seconds)
            clock.advance(refusal.seconds)
            response = post_login(client, resident.student_code, PIN)
        assert logged_in(response), resident.student_code
        clock.advance(8)  # the next resident, about 12 seconds later
    assert all(seconds <= 10 for seconds in waits)
