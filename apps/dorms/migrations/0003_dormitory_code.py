"""Add a short dormitory code (e.g. "DEM"), used in file names.

Existing dormitories get a code from their slug ("demo" -> "DEM").
"""

import re

import django.core.validators
from django.db import migrations, models


def fill_codes(apps, schema_editor):
    Dormitory = apps.get_model("dorms", "Dormitory")
    taken = set()
    for dorm in Dormitory.objects.order_by("pk"):
        base = (re.sub(r"[^A-Z0-9]", "", dorm.slug.upper()) or "DORM")[:3].ljust(2, "X")
        code, n = base, 1
        while code in taken:
            n += 1
            code = f"{base}{n}"
        taken.add(code)
        dorm.code = code
        dorm.save(update_fields=["code"])


class Migration(migrations.Migration):
    dependencies = [("dorms", "0002_machine_number")]

    operations = [
        migrations.AddField(
            model_name="dormitory",
            name="code",
            field=models.CharField(blank=True, max_length=8, null=True),
        ),
        migrations.RunPython(fill_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="dormitory",
            name="code",
            field=models.CharField(
                blank=True,
                help_text="Used in file names, e.g. calendar files. Filled in from the slug when left empty.",
                max_length=8,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        "^[A-Z0-9]{2,8}$", "2 to 8 capital Latin letters or digits, e.g. DEM."
                    )
                ],
                verbose_name="short code",
            ),
        ),
    ]
