"""Real concurrent requests against the booking service. Every name here is fake.

These tests use threads with their own database connections and real commits,
so they need PostgreSQL (CI runs them; locally set DATABASE_URL). They are
skipped on SQLite, where the test database cannot be shared between threads.
"""

import threading
from datetime import UTC, date, datetime, time

import pytest
from django.db import connection

from apps.bookings import services
from apps.bookings.models import Booking
from apps.dorms.models import TimeSlot
from apps.ledger.models import LedgerEntry

DAY = date(2026, 10, 20)
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=UTC)

# Real commits instead of a rolled-back test transaction. serialized_rollback
# restores the role groups (created by a migration) after the database is flushed.
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]


def run_at_once(*calls):
    """Run each call in its own thread, all released at the same moment.

    Returns, in order, each call's result or the exception it raised.
    """
    barrier = threading.Barrier(len(calls))
    results = [None] * len(calls)

    def worker(index, call):
        try:
            barrier.wait()
            results[index] = call()
        except Exception as exc:  # the test inspects it
            results[index] = exc
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=item) for item in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return results


def credit(resident, amount):
    LedgerEntry.objects.create(resident=resident, amount=amount, kind=LedgerEntry.Kind.CREDIT)


@pytest.mark.parametrize("attempt", range(5))
def test_two_residents_race_for_the_same_slot(resident, other_resident, machine, slot, attempt):
    credit(resident, 50)
    credit(other_resident, 50)

    results = run_at_once(
        lambda: services.book_slots(resident, machine, DAY, [slot], now=NOW),
        lambda: services.book_slots(other_resident, machine, DAY, [slot], now=NOW),
    )

    winners = [r for r in results if isinstance(r, list)]
    losers = [r for r in results if isinstance(r, services.SlotUnavailable)]
    assert (len(winners), len(losers)) == (1, 1), results
    [booking] = Booking.objects.all()
    assert LedgerEntry.objects.filter(kind=LedgerEntry.Kind.BOOKING).count() == 1
    loser = other_resident if booking.resident == resident else resident
    assert LedgerEntry.objects.balance(loser) == 50
    assert LedgerEntry.objects.balance(booking.resident) == 0


@pytest.mark.parametrize("attempt", range(5))
def test_one_resident_cannot_spend_balance_twice(resident, machine, slot, dormitory, attempt):
    slot_10 = TimeSlot.objects.create(dormitory=dormitory, start_time=time(10, 0))
    credit(resident, 50)

    results = run_at_once(
        lambda: services.book_slots(resident, machine, DAY, [slot], now=NOW),
        lambda: services.book_slots(resident, machine, DAY, [slot_10], now=NOW),
    )

    winners = [r for r in results if isinstance(r, list)]
    losers = [r for r in results if isinstance(r, services.InsufficientBalance)]
    assert (len(winners), len(losers)) == (1, 1), results
    assert Booking.objects.count() == 1
    assert LedgerEntry.objects.balance(resident) == 0


@pytest.mark.parametrize("attempt", range(5))
def test_concurrent_cancellations_refund_once(resident, machine, slot, attempt):
    credit(resident, 50)
    [booking] = services.book_slots(resident, machine, DAY, [slot], now=NOW)

    results = run_at_once(
        lambda: services.cancel_booking(booking, actor=resident.user, now=NOW),
        lambda: services.cancel_booking(booking, actor=resident.user, now=NOW),
    )

    refunds = [r for r in results if isinstance(r, LedgerEntry)]
    losers = [r for r in results if isinstance(r, services.AlreadyCancelled)]
    assert (len(refunds), len(losers)) == (1, 1), results
    assert LedgerEntry.objects.filter(kind=LedgerEntry.Kind.REFUND).count() == 1
    assert LedgerEntry.objects.balance(resident) == 50
