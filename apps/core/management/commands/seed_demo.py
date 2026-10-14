"""Create a demo dormitory with fake residents, staff, credits and bookings.

    python manage.py seed_demo

Safe to run more than once: existing demo objects are reused, not duplicated.
All names, rooms and codes are invented. Never put real personal data here.

Logins (passwords come from env vars, see .env.example):
    admin    / SEED_DEMO_STAFF_PASSWORD   superuser, Django admin
    manager  / SEED_DEMO_STAFF_PASSWORD   key manager
    student code D0001 … D0020 / SEED_DEMO_RESIDENT_PIN   residents
"""

import os
import random
from datetime import time, timedelta

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts import roles
from apps.accounts.models import Resident, StaffProfile, User
from apps.bookings.models import Booking
from apps.dorms.models import Dormitory, Machine, TimeSlot
from apps.ledger.models import LedgerEntry

FIRST_NAMES = ["Ivan", "Anna", "Pyotr", "Olga", "Sergei", "Maria", "Dmitri", "Elena", "Pavel"]
LAST_NAMES = ["Testov", "Primerova", "Demin", "Fakeova", "Obraztsov", "Vymyslova", "Shablonov"]
# Two-hour slots from 10:00; the last one ends at midnight.
SLOT_HOURS = [10, 12, 14, 16, 18, 20, 22]
MACHINE_COUNT = 6
RESIDENT_COUNT = 20


class Command(BaseCommand):
    help = "Create fake demo data (dormitory, machines, slots, residents, staff, bookings)."

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(42)  # Same data every time.
        staff_password = os.environ.get("SEED_DEMO_STAFF_PASSWORD", "demo-staff-password")
        resident_pin = os.environ.get("SEED_DEMO_RESIDENT_PIN", "123456")

        dorm, dorm_created = Dormitory.objects.get_or_create(
            slug="demo", defaults={"name": "Общежитие № 1"}
        )
        slots = [
            TimeSlot.objects.update_or_create(
                dormitory=dorm, start_time=time(hour, 0), defaults={"active": True}
            )[0]
            for hour in SLOT_HOURS
        ]
        # Slots from older demo data stay (bookings point to them) but are switched off.
        dorm.time_slots.exclude(pk__in=[slot.pk for slot in slots]).update(active=False)
        machines = [
            Machine.objects.get_or_create(dormitory=dorm, number=n)[0]
            for n in range(1, MACHINE_COUNT + 1)
        ]

        self._staff_user("admin", roles.ADMIN, dorm, staff_password, superuser=True)
        self._staff_user("manager", roles.MANAGER, dorm, staff_password)

        resident_group = Group.objects.get(name=roles.RESIDENT)
        residents = []
        for n in range(1, RESIDENT_COUNT + 1):
            code = f"D{n:04d}"
            user, created = User.objects.get_or_create(username=f"{dorm.slug}-{code}")
            if created:
                user.set_password(resident_pin)
                user.save()
                user.groups.add(resident_group)
            resident, created = Resident.objects.get_or_create(
                dormitory=dorm,
                student_code=code,
                defaults={
                    "user": user,
                    "full_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
                    "room": f"{rng.randint(1, 5)}{rng.randint(1, 30):02d}",
                },
            )
            if created:
                LedgerEntry.objects.create(
                    resident=resident,
                    kind=LedgerEntry.Kind.CREDIT,
                    amount=rng.choice([100, 200, 300, 500]),
                )
            residents.append(resident)

        if dorm_created:
            self._demo_bookings(dorm, slots, machines, residents, rng)

        self.stdout.write(self.style.SUCCESS(f"Demo data ready for “{dorm.name}”."))

    def _staff_user(self, username, role, dorm, password, superuser=False):
        user, created = User.objects.get_or_create(
            username=username, defaults={"is_staff": superuser, "is_superuser": superuser}
        )
        if created:
            user.set_password(password)
            user.save()
            user.groups.add(Group.objects.get(name=role))
        StaffProfile.objects.get_or_create(user=user, defaults={"dormitory": dorm})

    def _demo_bookings(self, dorm, slots, machines, residents, rng):
        """A few bookings today and tomorrow, charged through the ledger."""
        today = timezone.localdate(timezone=dorm.tzinfo)
        for day in (today, today + timedelta(days=1)):
            for slot in slots:
                for machine in rng.sample(machines, k=rng.randint(0, 3)):
                    resident = rng.choice(residents)
                    if LedgerEntry.objects.balance(resident) < dorm.price_per_slot:
                        continue
                    booking = Booking.objects.create(
                        machine=machine,
                        date=day,
                        slot=slot,
                        resident=resident,
                        price_rub=dorm.price_per_slot,
                    )
                    LedgerEntry.objects.create(
                        resident=resident,
                        kind=LedgerEntry.Kind.BOOKING,
                        amount=-booking.price_rub,
                        booking=booking,
                    )
