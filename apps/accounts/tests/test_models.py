import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.db import IntegrityError

from apps.accounts import roles
from apps.accounts.models import Resident, User
from conftest import make_resident


def test_role_groups_exist(db):
    assert set(Group.objects.values_list("name", flat=True)) >= set(roles.ALL_ROLES)


def test_has_role(resident):
    assert roles.has_role(resident.user, roles.RESIDENT)
    assert not roles.has_role(resident.user, roles.MANAGER)


def test_inactive_user_has_no_role(resident):
    resident.user.is_active = False
    resident.user.save()
    assert not roles.has_role(resident.user, roles.RESIDENT)


def test_anonymous_has_no_role(db):
    assert not roles.has_role(AnonymousUser(), roles.RESIDENT)


def test_student_code_unique_per_dormitory(resident, dormitory):
    user = User.objects.create_user(username="dup")
    with pytest.raises(IntegrityError):
        Resident.objects.create(
            user=user, dormitory=dormitory, student_code=resident.student_code, room="1"
        )


def test_same_student_code_allowed_in_other_dormitory(resident, other_dormitory):
    make_resident(other_dormitory, resident.student_code)
