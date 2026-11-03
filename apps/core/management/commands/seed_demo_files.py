"""Demo only: put back the files of demo receipts (and the QR code) that are
missing on disk.

On Railway the pre-deploy step (migrate, seed_demo) runs in a separate
container whose disk is thrown away, and volumes are not mounted there, so
files written by seed_demo never reach the app. This command runs when the
app container starts (deploy/scripts/railway-start.sh), where the volume is
mounted, and writes a small placeholder for every file that is missing.
Running it again changes nothing. It refuses to touch anything unless
DEMO_MODE is true: a real instance never gets made-up files.
"""

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.payments.models import PaymentDetails
from apps.receipts.demo_files import demo_png, demo_receipt_pdf
from apps.receipts.models import Receipt


class Command(BaseCommand):
    help = "Demo only: write placeholder files for demo receipts whose files are missing."

    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            self.stdout.write("Not a demo (DEMO_MODE is not true): nothing to do.")
            return
        written = 0
        for receipt in Receipt.objects.exclude(file="").iterator():
            storage = receipt.file.storage
            if storage.exists(receipt.file.name):
                continue
            if receipt.content_type == "application/pdf":
                data = demo_receipt_pdf(f"receipt-{receipt.pk}", receipt.amount)
            else:
                data = demo_png(f"DEMO receipt {receipt.pk}")
            saved = storage.save(receipt.file.name, ContentFile(data))
            if saved != receipt.file.name:  # never expected: keep the record in step
                Receipt.objects.filter(pk=receipt.pk).update(file=saved)
            written += 1
        for details in PaymentDetails.objects.exclude(qr_image=""):
            storage = details.qr_image.storage
            if not storage.exists(details.qr_image.name):
                storage.save(details.qr_image.name, ContentFile(demo_png("DEMO QR")))
                written += 1
        self.stdout.write(f"Demo files: {written} written.")
