"""Machine maintenance and archive periods (Stage 2).

A machine's state now comes from MachineUnavailability records instead of
the old `active` flag. Machines that were switched off become archive
records starting now, so they stay unbookable, then the flag is removed.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def archive_inactive_machines(apps, schema_editor):
    Machine = apps.get_model("dorms", "Machine")
    MachineUnavailability = apps.get_model("dorms", "MachineUnavailability")
    for machine in Machine.objects.filter(active=False):
        MachineUnavailability.objects.create(
            machine=machine,
            kind="archive",
            starts_at=timezone.now(),
            reason="Switched off before maintenance periods existed.",
            refund=False,
        )


def restore_active_flag(apps, schema_editor):
    Machine = apps.get_model("dorms", "Machine")
    MachineUnavailability = apps.get_model("dorms", "MachineUnavailability")
    archived = MachineUnavailability.objects.filter(kind="archive").values("machine_id")
    Machine.objects.filter(pk__in=archived).update(active=False)


class Migration(migrations.Migration):

    dependencies = [
        ('dorms', '0004_globalsettings'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MachineUnavailability',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('maintenance', 'maintenance'), ('archive', 'archived')], max_length=16, verbose_name='kind')),
                ('starts_at', models.DateTimeField(verbose_name='from')),
                ('ends_at', models.DateTimeField(blank=True, null=True, verbose_name='until')),
                ('reason', models.TextField(verbose_name='reason')),
                ('refund', models.BooleanField(default=True, help_text='If not, the usual cancellation rule decided refunds.', verbose_name='affected residents refunded in full')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='created at')),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL, verbose_name='created by')),
                ('machine', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='unavailabilities', to='dorms.machine', verbose_name='machine')),
            ],
            options={
                'verbose_name': 'machine out of service',
                'verbose_name_plural': 'machines out of service',
                'ordering': ['machine', 'starts_at'],
                'constraints': [models.CheckConstraint(condition=models.Q(('ends_at__isnull', True), ('ends_at__gt', models.F('starts_at')), _connector='OR'), name='unavailability_ends_after_start'), models.CheckConstraint(condition=models.Q(models.Q(('kind', 'archive'), _negated=True), ('ends_at__isnull', True), _connector='OR'), name='archive_has_no_end'), models.CheckConstraint(condition=models.Q(('reason', ''), _negated=True), name='unavailability_has_reason')],
            },
        ),
        migrations.RunPython(archive_inactive_machines, restore_active_flag),
        migrations.RemoveField(
            model_name='machine',
            name='active',
        ),
    ]
