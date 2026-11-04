"""`manage.py dormitory_admin` and the staff password link. Every name is fake."""

import re
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import Client
from django.urls import reverse

from apps.accounts import roles
from apps.accounts.models import Resident, User
from apps.audit.models import AuditEvent

BASE = "https://laundry.example.org"
NEW_PASSWORD = "a-long-new-staff-password-7"


def run(*args):
    out = StringIO()
    call_command("dormitory_admin", *args, stdout=out)
    return out.getvalue()


def link_in(output):
    return re.search(r"https://laundry\.example\.org(/\S+)", output).group(1)


def create(dormitory, username="olga", role="admin", name="Ольга Комендантова"):
    return run(
        "create",
        "--dormitory",
        dormitory.slug,
        "--username",
        username,
        "--role",
        role,
        "--name",
        name,
        "--base-url",
        BASE,
    )


def choose_password(path, password=NEW_PASSWORD):
    client = Client()
    page = client.get(path, follow=True)  # Django moves the token into the session
    form_url = page.redirect_chain[-1][0] if page.redirect_chain else path
    return client, client.post(form_url, {"new_password1": password, "new_password2": password})


def test_create_then_choose_the_password_then_log_in(dormitory):
    output = create(dormitory)
    user = User.objects.get(username="olga")
    assert not user.has_usable_password()  # nobody knows a password yet
    assert roles.has_role(user, roles.ADMIN)
    assert user.staff_profile.dormitory == dormitory
    assert user.get_full_name() == "Ольга Комендантова"
    assert not user.is_superuser and not user.is_staff  # never Django admin

    client, response = choose_password(link_in(output))
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    login = client.post(reverse("accounts:login"), {"username": "olga", "password": NEW_PASSWORD})
    assert login.status_code == 302
    actions = list(AuditEvent.objects.values_list("action", flat=True))
    assert "staff.create" in actions and "user.password_set_by_link" in actions


def test_the_link_works_once(dormitory):
    path = link_in(create(dormitory))
    choose_password(path)
    _client, response = choose_password(path, "another-long-password-8")
    assert response.status_code == 200 and not response.context["validlink"]
    assert User.objects.get(username="olga").check_password(NEW_PASSWORD)


def test_a_new_link_for_an_existing_account(dormitory):
    create(dormitory)
    output = run("link", "--username", "olga", "--base-url", BASE)
    _client, response = choose_password(link_in(output))
    assert response.status_code == 302
    assert AuditEvent.objects.filter(action="staff.password_link").count() == 1


def test_managers_too(dormitory):
    create(dormitory, username="keys", role="manager")
    assert roles.has_role(User.objects.get(username="keys"), roles.MANAGER)


def test_deactivate_switches_off_and_logs_out(dormitory):
    path = link_in(create(dormitory))
    client, _ = choose_password(path)
    client.post(reverse("accounts:login"), {"username": "olga", "password": NEW_PASSWORD})
    assert client.get(reverse("manage:residents")).status_code == 200
    output = run("deactivate", "--username", "olga", "--reason", "Left the job")
    assert "1 login(s) ended" in output
    assert not User.objects.get(username="olga").is_active
    assert client.get(reverse("manage:residents")).status_code == 302
    event = AuditEvent.objects.get(action="staff.deactivate")
    assert event.reason == "Left the job"
    with pytest.raises(CommandError):
        run("link", "--username", "olga", "--base-url", BASE)


def test_links_never_work_for_residents_or_switched_off_staff(dormitory, resident):
    from apps.accounts.activation import staff_password_url

    _client, response = choose_password(staff_password_url(BASE, resident.user)[len(BASE) :])
    assert not response.context["validlink"]
    with pytest.raises(CommandError):
        run("link", "--username", resident.user.username, "--base-url", BASE)


@pytest.mark.parametrize(
    "args, message",
    [
        (["create", "--dormitory", "nope", "--username", "x", "--base-url", BASE], "No dormitory"),
        (["link", "--username", "nobody", "--base-url", BASE], "No dormitory admin"),
        (["create", "--dormitory", "test", "--username", "x"], "PUBLIC_BASE_URL"),
    ],
)
def test_clear_errors(dormitory, settings, args, message):
    settings.PUBLIC_BASE_URL = ""
    with pytest.raises(CommandError, match=message):
        run(*args)


def test_usernames_are_unique_ignoring_case(dormitory):
    create(dormitory)
    with pytest.raises(CommandError, match="already taken"):
        create(dormitory, username="OLGA")


def test_superusers_are_not_managed_here(dormitory, admin_user):
    from django.contrib.auth.models import Group

    from apps.accounts.models import StaffProfile

    admin_user.groups.add(Group.objects.get(name=roles.ADMIN))
    StaffProfile.objects.create(user=admin_user, dormitory=dormitory)
    with pytest.raises(CommandError, match="superuser"):
        run("deactivate", "--username", admin_user.username, "--reason", "x")


def test_no_resident_is_created_or_touched(dormitory, resident):
    create(dormitory)
    assert Resident.objects.count() == 1
