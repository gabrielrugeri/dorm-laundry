"""Create one Django group per role (see apps/accounts/roles.py).

Names are written out here on purpose: migrations must not depend on code that
may change later.
"""

from django.db import migrations

ROLES = ["resident", "manager", "admin"]


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLES:
        Group.objects.get_or_create(name=name)


def delete_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_resident_staffprofile"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(create_groups, delete_groups)]
