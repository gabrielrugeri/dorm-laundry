"""Create a demo dormitory with fake residents, staff, credits and bookings.

    python manage.py seed_demo

Safe to run more than once: existing demo objects are reused, not duplicated.
All names, rooms and codes are invented. Never put real personal data here.

On a production server (Railway demo) it refuses to run unless DEMO_MODE is
on, and it requires SEED_DEMO_STAFF_PASSWORD and SEED_DEMO_RESIDENT_PIN to be
set to non-default values, because the defaults are published in the README.

Logins (passwords come from env vars, see .env.example):
    admin    / SEED_DEMO_STAFF_PASSWORD   dormitory admin (/manage/)
    manager  / SEED_DEMO_STAFF_PASSWORD   key manager
    student code D0001 … D0020 / SEED_DEMO_RESIDENT_PIN   residents
"""

import os
import random
from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts import roles
from apps.accounts import services as resident_services
from apps.accounts.models import Resident, StaffProfile, User
from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.dorms.models import Dormitory, Machine, TimeSlot
from apps.ledger import services as ledger_services
from apps.ledger.models import LedgerEntry

FIRST_NAMES = ["Ivan", "Anna", "Pyotr", "Olga", "Sergei", "Maria", "Dmitri", "Elena", "Pavel"]
LAST_NAMES = ["Testov", "Primerova", "Demin", "Fakeova", "Obraztsov", "Vymyslova", "Shablonov"]
# Two-hour slots from 10:00; the last one ends at midnight.
SLOT_HOURS = [10, 12, 14, 16, 18, 20, 22]
MACHINE_COUNT = 6
# Comments an admin types when recording a payment (fake, in Russian like the real ones).
PAYMENT_NOTES = ["Наличными на вахте", "Перевод на карту", "Наличными"]
RESIDENT_COUNT = 20
# Published in the README for local development; never accepted on a server.
DEFAULT_STAFF_PASSWORD = "demo-staff-password"
DEFAULT_RESIDENT_PIN = "123456"


class Command(BaseCommand):
    help = "Create fake demo data (dormitory, machines, slots, residents, staff, bookings)."

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(42)  # Same data every time.
        staff_password = os.environ.get("SEED_DEMO_STAFF_PASSWORD", DEFAULT_STAFF_PASSWORD)
        resident_pin = os.environ.get("SEED_DEMO_RESIDENT_PIN", DEFAULT_RESIDENT_PIN)
        if settings.IS_PRODUCTION:
            if not settings.DEMO_MODE:
                raise CommandError("Refusing to add fake demo data: DEMO_MODE is not true.")
            if staff_password == DEFAULT_STAFF_PASSWORD or resident_pin == DEFAULT_RESIDENT_PIN:
                raise CommandError(
                    "Set SEED_DEMO_STAFF_PASSWORD and SEED_DEMO_RESIDENT_PIN to your own values "
                    "first: the defaults are published in the README."
                )

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

        self._staff_user("admin", roles.ADMIN, dorm, staff_password)
        self._staff_user("manager", roles.MANAGER, dorm, staff_password)

        if not dorm_created:
            # Demo residents exist already. Some were erased or changed on purpose,
            # so looking them up again by code would create duplicates.
            self.stdout.write(self.style.SUCCESS(f"Demo data ready for “{dorm.name}”."))
            return

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
                # Recorded by the admin like a real cash payment at the desk.
                ledger_services.add_manual_entry(
                    actor=User.objects.get(username="admin"),
                    resident=resident,
                    kind=LedgerEntry.Kind.CREDIT,
                    amount=rng.choice([100, 200, 300, 500]),
                    note=rng.choice(PAYMENT_NOTES),
                )
            residents.append(resident)

        self._demo_bookings(dorm, slots, machines, residents, rng)
        self._demo_admin_cancellation(dorm)
        self._demo_resident_states(dorm, residents)

        self.stdout.write(self.style.SUCCESS(f"Demo data ready for “{dorm.name}”."))

    def _staff_user(self, username, role, dorm, password):
        """A dormitory staff account. Not a superuser: Django admin is for
        developers only (create one with `manage.py createsuperuser`)."""
        user, created = User.objects.get_or_create(username=username)
        if created:
            user.set_password(password)
            user.groups.add(Group.objects.get(name=role))
        user.is_staff = user.is_superuser = False
        user.save()
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

    def _demo_admin_cancellation(self, dorm):
        """One of tomorrow's bookings cancelled by the admin through the service,
        so the demo shows the resident's notice, the refund and an audit event."""
        tomorrow = timezone.localdate(timezone=dorm.tzinfo) + timedelta(days=1)
        booking = (
            Booking.objects.filter(machine__dormitory=dorm, date=tomorrow, status="active")
            .order_by("starts_at")
            .first()
        )
        if booking is None:
            return
        booking_services.cancel_booking(
            booking,
            actor=User.objects.get(username="admin"),
            reason="Плановая проверка машины",
            full_refund=True,
        )

    def _demo_resident_states(self, dorm, residents):
        """Residents in every state the admin screens show: two in debt, one
        with access turned off, one whose personal data was erased, and one
        just added (no history, no PIN yet)."""
        admin = User.objects.get(username="admin")
        for resident, debt in ((residents[3], 80), (residents[6], 150)):
            balance = LedgerEntry.objects.balance(resident)
            ledger_services.add_manual_entry(
                actor=admin,
                resident=resident,
                kind=LedgerEntry.Kind.ADJUSTMENT,
                amount=-(balance + debt),
                note="Перевод не дошёл, оплата отменена",
            )
        resident_services.deactivate(actor=admin, resident=residents[18], reason="Выехал на лето")
        resident_services.anonymize(actor=admin, resident=residents[19], confirm_debt=True)
        resident_services.create_resident(
            actor=admin,
            dormitory=dorm,
            full_name="Svetlana Novikova",
            room="118",
            student_code="D0021",
        )
