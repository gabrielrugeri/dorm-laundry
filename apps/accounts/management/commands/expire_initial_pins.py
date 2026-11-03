"""Delete the hashes of first-time PINs that have expired.

    python manage.py expire_initial_pins

Safe to run any time (daily from the systemd timer, and at every deploy).
Login refuses expired first-time PINs whether or not this has run; this only
removes hashes that are no longer needed (apps/accounts/initial_pins.py).
"""

from django.core.management.base import BaseCommand

from apps.accounts import initial_pins


class Command(BaseCommand):
    help = "Delete the hashes of expired first-time PINs."

    def handle(self, *args, **options):
        count = initial_pins.expire_old()
        self.stdout.write(f"Expired first-time PINs removed: {count}.")
