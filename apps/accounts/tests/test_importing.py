"""CSV import of residents. Every name and code here is fake."""

import pytest

from apps.accounts import importing, roles
from apps.accounts.models import Resident
from apps.audit.models import AuditEvent
from apps.keylog.tests.test_services import make_staff


@pytest.fixture(autouse=True)
def english():
    """Messages are checked in English; the default language is Russian."""
    from django.utils import translation

    with translation.override("en"):
        yield


@pytest.fixture
def boss(dormitory):
    return make_staff(dormitory, "boss", role=roles.ADMIN)


def csv_bytes(*lines, encoding="utf-8", sep=";"):
    return "\n".join(sep.join(cells) for cells in lines).encode(encoding)


HEADER = ("Студенческий код", "ФИО", "Комната")


def statuses(result):
    return [(row.line, row.status) for row in result.rows]


def test_preview_new_changed_unchanged_error(dormitory, resident, other_resident):
    data = csv_bytes(
        HEADER,
        ("S0001", "Ivan Testov", "101"),  # unchanged
        ("S0002", "Anna Fakeova-Petrova", "202"),  # name changed
        ("S9001", "Olga Novikova", "305"),  # new
        ("S9002", "", "306"),  # error: no name
        ("s9001", "Copy Person", "307"),  # error: duplicate code in the file
    )
    result = importing.preview(dormitory, data)
    assert statuses(result) == [
        (2, "unchanged"),
        (3, "changed"),
        (4, "new"),
        (5, "error"),
        (6, "error"),
    ]
    changed = result.rows[1]
    assert changed.changes == {"full_name": ("Anna Fakeova", "Anna Fakeova-Petrova")}
    assert changed.name_changed
    assert "line 4" in result.rows[4].errors[0]
    assert Resident.objects.count() == 2  # nothing written
    assert not AuditEvent.objects.exists()


def test_apply_creates_and_updates_with_audit(boss, dormitory, other_resident):
    data = csv_bytes(
        HEADER,
        ("S0002", "Anna Fakeova", "203"),
        ("S9001", "Olga Novikova", "305"),
        ("S9002", "", "306"),
    )
    result, created = importing.apply(boss, dormitory, data)
    assert [r.student_code for r in created] == ["S9001"]
    assert not created[0].user.has_usable_password()
    other_resident.refresh_from_db()
    assert other_resident.room == "203"
    assert sorted(AuditEvent.objects.values_list("action", flat=True)) == [
        "resident.create",
        "resident.update",
    ]
    assert not Resident.objects.filter(student_code="S9002").exists()


def test_importing_the_same_file_twice_changes_nothing(boss, dormitory):
    data = csv_bytes(HEADER, ("S9001", "Olga Novikova", "305"))
    importing.apply(boss, dormitory, data)
    result, created = importing.apply(boss, dormitory, data)
    assert created == []
    assert statuses(result) == [(2, "unchanged")]
    assert Resident.objects.filter(student_code="S9001").count() == 1
    assert AuditEvent.objects.count() == 1


def test_excel_files_windows_1251_and_commas(dormitory):
    data = csv_bytes(
        ("код", "имя", "комната", "язык"),
        ("S9001", "Ольга Новикова", "305", "EN"),
        encoding="cp1251",
        sep=",",
    )
    row = importing.preview(dormitory, data).rows[0]
    assert row.values == {
        "student_code": "S9001",
        "full_name": "Ольга Новикова",
        "room": "305",
    }  # the "language" column is ignored


def test_utf8_with_bom_and_english_headers(dormitory):
    data = b"\xef\xbb\xbf" + csv_bytes(("student_code", "full_name", "room"), ("S1", "A B", "1"))
    assert statuses(importing.preview(dormitory, data)) == [(2, "new")]


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (csv_bytes(("name", "room"), ("A", "1")), "first row"),
        (csv_bytes(HEADER), "no residents"),
        (b"x" * (importing.MAX_FILE_BYTES + 1), "too large"),
    ],
    ids=["empty", "no-header", "no-rows", "too-large"],
)
def test_unreadable_files_are_refused_with_a_message(dormitory, data, message):
    with pytest.raises(importing.ImportFileError) as error:
        importing.preview(dormitory, data)
    assert message in str(error.value)


def test_other_dormitory_and_erased_residents_are_not_matched(boss, other_dormitory, resident):
    from apps.accounts import services
    from conftest import make_resident

    make_resident(other_dormitory, "S7777", name="Elsewhere", room="9")
    services.anonymize(actor=boss, resident=resident)
    data = csv_bytes(HEADER, ("S7777", "Someone Here", "10"))
    assert statuses(importing.preview(resident.dormitory, data)) == [(2, "new")]


def test_too_long_values_and_ignored_language_column(dormitory):
    data = csv_bytes(
        ("код", "фио", "комната", "язык"),
        ("S1", "A" * 201, "1", "ru"),
        ("S2", "B", "2", "de"),
    )
    rows = importing.preview(dormitory, data).rows
    assert rows[0].status == "error"
    assert "too long" in rows[0].errors[0]
    assert rows[1].status == "new"


def test_apply_is_one_transaction(boss, dormitory, monkeypatch):
    from apps.accounts import services

    calls = {"n": 0}
    real = services.create_resident

    def fail_on_second(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(**kwargs)

    monkeypatch.setattr(services, "create_resident", fail_on_second)
    data = csv_bytes(HEADER, ("S1", "A B", "1"), ("S2", "C D", "2"))
    with pytest.raises(RuntimeError):
        importing.apply(boss, dormitory, data)
    assert not Resident.objects.exists()
    assert not AuditEvent.objects.exists()
