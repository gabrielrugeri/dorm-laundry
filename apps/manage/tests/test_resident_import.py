"""Importing residents from a file in the admin area. Fake names only."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.accounts import roles
from apps.accounts.models import Resident
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff

UPLOAD = reverse("manage:resident_import")
CONFIRM = reverse("manage:resident_import_confirm")
DONE = reverse("manage:resident_import_done")
LINKS = reverse("manage:resident_import_links")
SAMPLE = reverse("manage:resident_import_sample")


@pytest.fixture
def boss_client(client, dormitory):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    client.cookies["django_language"] = "en"
    return client


def csv_file(*lines):
    content = "\n".join(";".join(cells) for cells in lines).encode("utf-8")
    return SimpleUploadedFile("residents.csv", content, content_type="text/csv")


def upload(client, *lines):
    return client.post(UPLOAD, {"file": csv_file(("Student code", "Full name", "Room"), *lines)})


def test_preview_writes_nothing(boss_client, resident):
    page = upload(boss_client, ("S0001", "Ivan Testov", "999"), ("S5", "New Person", "5"))
    result = page.context["result"]
    assert (len(result.new_rows), len(result.changed_rows)) == (1, 1)
    assert Resident.objects.count() == 1
    resident.refresh_from_db()
    assert resident.room == "101"
    assert "Import 2 rows" in page.content.decode()


def test_confirm_imports_the_previewed_file(boss_client, resident):
    page = upload(boss_client, ("S0001", "Ivan Testov", "999"), ("S5", "New Person", "5"))
    response = boss_client.post(CONFIRM, {"token": page.context["token"]})
    assert response.url == DONE
    resident.refresh_from_db()
    assert resident.room == "999"
    assert Resident.objects.filter(student_code="S5").exists()
    done = boss_client.get(DONE)
    assert done.context["summary"] == {"created": 1, "changed": 1, "skipped": 0}

    # Pressing confirm again does not import twice.
    again = boss_client.post(CONFIRM, {"token": page.context["token"]})
    assert again.url == UPLOAD
    assert Resident.objects.filter(student_code="S5").count() == 1


def test_wrong_token_imports_nothing(boss_client):
    upload(boss_client, ("S5", "New Person", "5"))
    boss_client.post(CONFIRM, {"token": "forged"})
    assert not Resident.objects.filter(student_code="S5").exists()


def test_unreadable_file_shows_a_message(boss_client):
    page = boss_client.post(UPLOAD, {"file": csv_file(("Name", "Room"), ("A", "1"))})
    assert "first row must name the columns" in page.context["error"]
    assert boss_client.post(UPLOAD, {}).context["error"]


def test_login_links_for_new_residents(boss_client):
    page = upload(boss_client, ("S5", "New Person", "5"), ("S6", "Other Person", "6"))
    boss_client.post(CONFIRM, {"token": page.context["token"]})
    response = boss_client.get(LINKS)
    body = response.content.decode("utf-8-sig")
    assert body.count("/account/activate/") == 2
    assert "New Person" in body
    # Each download is recorded; the links themselves are never stored.
    assert AuditEvent.objects.filter(action="resident.activation_link").count() == 2
    assert "/account/activate/" not in str(list(AuditEvent.objects.values()))


def test_no_links_for_residents_who_already_chose_a_pin(boss_client):
    page = upload(boss_client, ("S5", "New Person", "5"))
    boss_client.post(CONFIRM, {"token": page.context["token"]})
    new = Resident.objects.get(student_code="S5")
    new.user.set_password("482913")
    new.user.save()
    assert boss_client.get(LINKS).status_code == 404


def test_sample_file_can_be_imported(boss_client):
    sample = boss_client.get(SAMPLE).content
    page = boss_client.post(UPLOAD, {"file": SimpleUploadedFile("s.csv", sample)})
    assert len(page.context["result"].new_rows) == 2


def test_preview_in_russian_highlights_name_changes(client, dormitory, resident):
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    page = client.post(
        UPLOAD,
        {"file": csv_file(("Студенческий код", "ФИО", "Комната"), ("S0001", "Ivan Novy", "101"))},
    )
    html = page.content.decode()
    assert "Проверьте перед импортом" in html
    assert "Ivan Testov" in html and "Ivan Novy" in html
    assert "bg-amber-50" in html  # the name change is highlighted


@pytest.mark.parametrize("url", [UPLOAD, DONE, LINKS, SAMPLE])
def test_managers_and_residents_cannot(client, dormitory, resident, url):
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(url).status_code == 403
    client.force_login(resident.user)
    assert client.get(url).status_code == 403


def test_file_previewed_in_one_dormitory_cannot_be_confirmed_in_another(
    client, dormitory, other_dormitory
):
    admin = make_staff(dormitory, "boss", role=roles.ADMIN)
    client.force_login(admin)
    page = upload(client, ("S5", "New Person", "5"))
    admin.staff_profile.dormitory = other_dormitory
    admin.staff_profile.save()
    client.post(CONFIRM, {"token": page.context["token"]})
    assert not Resident.objects.filter(student_code="S5").exists()
