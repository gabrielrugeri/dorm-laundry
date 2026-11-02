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
from contextlib import contextmanager
from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts import roles
from apps.accounts import services as resident_services
from apps.accounts.models import Resident, StaffProfile, User
from apps.audit.models import AuditEvent
from apps.bookings import services as booking_services
from apps.bookings.models import Booking
from apps.dorms import maintenance
from apps.dorms.models import Dormitory, Machine, MachineUnavailability, TimeSlot
from apps.ledger import services as ledger_services
from apps.ledger.models import LedgerEntry
from apps.payments.models import PaymentDetails
from apps.receipts import services as receipt_services

# Made-up names, stored the way a real list would have them: Russian names in
# Cyrillic, two foreign residents in Latin script. Shown exactly like this in
# every interface language.
NAMES = [
    "Иван Тестов",
    "Анна Примерова",
    "Пётр Демин",
    "Ольга Фейкова",
    "Сергей Образцов",
    "Мария Вымыслова",
    "Дмитрий Шаблонов",
    "Елена Тестова",
    "Павел Примеров",
    "Carlos Ejemplo",
    "Наталья Образцова",
    "Алексей Макетов",
    "Ирина Шаблонова",
    "Mei Shiyan",
    "Андрей Пробный",
    "Татьяна Демина",
    "Николай Вымыслов",
    "Юлия Макетова",
    "Михаил Фейков",
    "Ксения Пробная",
]
# Two-hour slots from 10:00; the last one ends at midnight.
SLOT_HOURS = [10, 12, 14, 16, 18, 20, 22]
# How likely a machine is booked in each slot of the fake history.
SLOT_POPULARITY = {10: 0.15, 12: 0.2, 14: 0.3, 16: 0.45, 18: 0.6, 20: 0.55, 22: 0.3}
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
            slug="demo", defaults={"name": "Общежитие № 1", "code": "DEM"}
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
                    "full_name": NAMES[n - 1],
                    # Rooms like "214", and shared blocks like "301-2".
                    "room": f"{rng.randint(1, 5)}{rng.randint(1, 30):02d}"
                    + (f"-{rng.randint(1, 2)}" if n % 4 == 0 else ""),
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

        self._demo_history(dorm, slots, machines, residents, rng)
        self._demo_bookings(dorm, slots, machines, residents, rng)
        self._demo_admin_cancellation(dorm)
        self._demo_maintenance(machines)
        self._demo_resident_states(dorm, residents)
        self._demo_payments(dorm, residents)

        self.stdout.write(self.style.SUCCESS(f"Demo data ready for “{dorm.name}”."))

    def _demo_maintenance(self, machines):
        """Machine 6 under maintenance for two days (its bookings in that time
        are cancelled and refunded), and maintenance planned on machine 5."""
        admin = User.objects.get(username="admin")
        now = timezone.now()
        maintenance.take_out_of_service(
            actor=admin,
            machine=machines[5],
            kind=MachineUnavailability.Kind.MAINTENANCE,
            starts_at=now,
            ends_at=now + timedelta(days=2),
            reason="Течёт насос, ждём мастера",
        )
        planned = (now + timedelta(days=5)).replace(minute=0, second=0, microsecond=0)
        maintenance.take_out_of_service(
            actor=admin,
            machine=machines[4],
            kind=MachineUnavailability.Kind.MAINTENANCE,
            starts_at=planned,
            ends_at=planned + timedelta(hours=4),
            reason="Плановая чистка фильтра",
        )

    def _demo_history(self, dorm, slots, machines, residents, rng):
        """Eight weeks of fake past use, so the dashboard's charts make sense:
        evenings and weekends busier than mornings, residents topping up with
        receipts or cash when they run low, a few cancellations and two
        voided receipts. Everything goes through the real services; only
        the timestamps are moved back (see `_dated`). Residents book only
        what they can pay, so nobody ends this in debt."""
        admin = User.objects.get(username="admin")
        today = timezone.localdate(timezone=dorm.tzinfo)
        weeks = settings.SEED_DEMO_HISTORY_WEEKS
        if weeks < 1:
            return
        first = today - timedelta(days=today.weekday(), weeks=weeks - 1)
        regulars = residents[:18]
        receipts, tag = [], 0
        day = first
        while day < today:
            weekend = day.weekday() >= 5
            for slot in slots:
                busy = SLOT_POPULARITY[slot.start_time.hour] * (1.25 if weekend else 1)
                for machine in machines:
                    if rng.random() >= busy:
                        continue
                    resident = rng.choice(regulars)
                    starts_at, _ends_at = slot.bounds(day)
                    if LedgerEntry.objects.balance(resident) < dorm.price_per_slot:
                        tag += 1
                        paid_at = starts_at - timedelta(hours=rng.randint(2, 6))
                        receipt = self._history_top_up(admin, resident, rng, tag, paid_at)
                        if receipt is not None:
                            receipts.append((receipt, paid_at))
                    if LedgerEntry.objects.balance(resident) < dorm.price_per_slot:
                        continue
                    booked_at = starts_at - timedelta(hours=1)
                    with self._dated(booked_at):
                        try:
                            [booking] = booking_services.book_slots(
                                resident, machine, day, [slot], now=booked_at
                            )
                        except booking_services.BookingError:
                            continue
                    if rng.random() < 0.03:
                        cancelled_at = booked_at + timedelta(minutes=20)
                        with self._dated(cancelled_at):
                            booking_services.cancel_booking(
                                booking, actor=resident.user, now=cancelled_at
                            )
            day += timedelta(days=1)
        # Two receipts the admin found to be wrong, a few days after they came.
        for receipt, paid_at in receipts[3:5]:
            voided_at = paid_at + timedelta(days=2)
            with self._dated(voided_at):
                receipt_services.void_receipt(
                    receipt=receipt,
                    actor=admin,
                    reason="Такого платежа нет в выписке банка",
                    now=voided_at,
                )
            # Put the money back as cash, so the resident is not left in debt.
            with self._dated(voided_at + timedelta(hours=1)):
                ledger_services.add_manual_entry(
                    actor=admin,
                    resident=receipt.resident,
                    kind=LedgerEntry.Kind.CREDIT,
                    amount=receipt.amount,
                    note="Оплатил наличными на вахте",
                )

    def _history_top_up(self, admin, resident, rng, tag, when):
        """A past payment: two times out of three a receipt, else cash."""
        amount = rng.choice([200, 300, 500])
        with self._dated(when):
            if rng.random() < 2 / 3:
                fake_pdf = f"%PDF-1.4\n% DEMO receipt {tag}, not a real payment\n%%EOF\n".encode()
                try:
                    return receipt_services.submit_receipt(
                        resident=resident,
                        amount=amount,
                        upload=SimpleUploadedFile("demo.pdf", fake_pdf),
                        now=when,
                    )
                except receipt_services.ReceiptRefused:
                    pass  # a limit was reached: pay cash instead
            ledger_services.add_manual_entry(
                actor=admin,
                resident=resident,
                kind=LedgerEntry.Kind.CREDIT,
                amount=amount,
                note=rng.choice(PAYMENT_NOTES),
            )
        return None

    @contextmanager
    def _dated(self, when):
        """Move the automatic timestamps of rows made inside the block to
        `when`. Seed data only: the database stamps rows with the real time,
        and history needs past times. Ledger entries stay append-only here;
        the update only corrects when they were made."""
        marks = {
            model: model.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
            for model in (LedgerEntry, Booking, AuditEvent)
        }
        yield
        for model, last in marks.items():
            model.objects.filter(pk__gt=last).update(created_at=when)

    def _demo_payments(self, dorm, residents):
        """Obviously fake payment details and three receipts, one of them
        voided by the admin. No real bank, account or phone: the BIK,
        account and INN stay empty."""
        PaymentDetails.objects.create(
            dormitory=dorm,
            recipient="Общежитие № 1 (пример, не платите сюда)",
            bank="Банк Пример",
            sbp_phone="+70000000000",
            purpose_prefix="Стирка",
        )
        receipts = []
        for resident, amount in ((residents[0], 200), (residents[1], 150), (residents[2], 1900)):
            fake_pdf = (
                b"%PDF-1.4\n% DEMO receipt, not a real payment: "
                + resident.student_code.encode()
                + b"\n%%EOF\n"
            )
            receipts.append(
                receipt_services.submit_receipt(
                    resident=resident,
                    amount=amount,
                    upload=SimpleUploadedFile("demo.pdf", fake_pdf),
                )
            )
        receipt_services.void_receipt(
            receipt=receipts[2],
            actor=User.objects.get(username="admin"),
            reason="Такого платежа нет в выписке банка",
        )

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
            full_name="Светлана Новикова",
            room="118",
            student_code="D0021",
        )
