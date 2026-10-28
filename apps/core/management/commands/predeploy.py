"""Database steps to run before each deploy (Railway: "Pre-deploy Command").

    python manage.py predeploy

1. migrate: bring the database schema up to date;
2. createcachetable: the shared cache table (login lockout across workers);
3. in demo mode only, seed_demo: fake demo data. It is idempotent: once the
   demo dormitory exists it changes nothing, so running this on every deploy
   never duplicates data and never undoes what testers did.

Safe to run again and again. Fails (non-zero exit) if any step fails, so the
platform does not start a release with an out-of-date database.
"""

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Migrate, create the cache table and, in demo mode, seed demo data (idempotent)."

    def handle(self, *args, **options):
        call_command("migrate", interactive=False, verbosity=1)
        call_command("createcachetable", verbosity=1)
        if settings.DEMO_MODE:
            call_command("seed_demo")
        else:
            self.stdout.write("Not in demo mode: no demo data.")
        self.stdout.write(self.style.SUCCESS("Pre-deploy steps done."))
