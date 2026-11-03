"""Lower receipt limits: 600 ₽ per receipt, 1500 ₽ per resident in 30 days.

The existing rules row changes only if it still has the old defaults (2000 and
5000): a value an admin chose is never overwritten. On a database already in
use the change is recorded in the history like any other change of the rules,
with no person as its author. A new database (no accounts yet) never used the
old values, so there is nothing to record.
"""

from django.conf import settings
from django.db import migrations, models

OLD = {"max_receipt_amount": 2000, "max_credit_per_30_days": 5000}
NEW = {"max_receipt_amount": 600, "max_credit_per_30_days": 1500}
REASON = "Новые значения по умолчанию после обновления программы."
FIELDS = (
    "credit_limit",
    "max_receipt_amount",
    "max_credit_per_30_days",
    "max_uploads_per_day",
    "max_upload_mb",
)


def _values(row):
    return {"id": row.pk, **{name: getattr(row, name) for name in FIELDS}}


def lower_the_defaults(apps, schema_editor):
    GlobalSettings = apps.get_model("dorms", "GlobalSettings")
    AuditEvent = apps.get_model("audit", "AuditEvent")
    User = apps.get_model(settings.AUTH_USER_MODEL)
    row = GlobalSettings.objects.filter(pk=1).first()
    if row is None or any(getattr(row, name) != value for name, value in OLD.items()):
        return
    before = _values(row)
    for name, value in NEW.items():
        setattr(row, name, value)
    row.save()
    if not User.objects.exists():
        return
    AuditEvent.objects.create(
        action="settings.change",
        target_type="dorms.GlobalSettings",
        target_id=str(row.pk),
        target_repr="Money and upload rules",
        before=before,
        after=_values(row),
        reason=REASON,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("dorms", "0005_machine_unavailability"),
        ("audit", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="globalsettings",
            name="max_credit_per_30_days",
            field=models.PositiveIntegerField(
                default=1500, verbose_name="most money credited to one resident in 30 days (RUB)"
            ),
        ),
        migrations.AlterField(
            model_name="globalsettings",
            name="max_receipt_amount",
            field=models.PositiveIntegerField(
                default=600, verbose_name="largest amount on one receipt (RUB)"
            ),
        ),
        migrations.RunPython(lower_the_defaults, migrations.RunPython.noop),
    ]
