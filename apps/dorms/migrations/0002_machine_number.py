"""Replace the free-text machine label with a number.

Residents now see "Machine 3" / "Машина 3" in their own language, built from the
number. Existing labels are converted: the digits in the label become the
number ("Machine 3" -> 3); labels without digits get the next free number.
"""

import re

from django.db import migrations, models


def labels_to_numbers(apps, schema_editor):
    Machine = apps.get_model("dorms", "Machine")
    by_dormitory = {}
    for machine in Machine.objects.order_by("dormitory_id", "label", "pk"):
        by_dormitory.setdefault(machine.dormitory_id, []).append(machine)
    for machines in by_dormitory.values():
        used = set()
        without_digits = []
        for machine in machines:
            match = re.search(r"\d+", machine.label)
            number = int(match.group()) if match else None
            if number and number not in used:
                machine.number = number
                used.add(number)
                machine.save(update_fields=["number"])
            else:
                without_digits.append(machine)
        next_number = 1
        for machine in without_digits:
            while next_number in used:
                next_number += 1
            machine.number = next_number
            used.add(next_number)
            machine.save(update_fields=["number"])


def numbers_to_labels(apps, schema_editor):
    Machine = apps.get_model("dorms", "Machine")
    for machine in Machine.objects.all():
        machine.label = f"Machine {machine.number}"
        machine.save(update_fields=["label"])


class Migration(migrations.Migration):
    dependencies = [
        ("dorms", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="machine",
            name="number",
            field=models.PositiveSmallIntegerField(null=True, verbose_name="number"),
        ),
        migrations.RunPython(labels_to_numbers, numbers_to_labels),
        migrations.RemoveConstraint(
            model_name="machine",
            name="unique_machine_label_per_dormitory",
        ),
        migrations.RemoveField(
            model_name="machine",
            name="label",
        ),
        migrations.AlterField(
            model_name="machine",
            name="number",
            field=models.PositiveSmallIntegerField(
                help_text="Shown as “Machine 3” in the selected language.",
                verbose_name="number",
            ),
        ),
        migrations.AlterModelOptions(
            name="machine",
            options={
                "ordering": ["dormitory", "number"],
                "verbose_name": "machine",
                "verbose_name_plural": "machines",
            },
        ),
        migrations.AddConstraint(
            model_name="machine",
            constraint=models.UniqueConstraint(
                fields=("dormitory", "number"), name="unique_machine_number_per_dormitory"
            ),
        ),
    ]
