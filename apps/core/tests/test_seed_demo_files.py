"""seed_demo_files: puts back missing demo files, only in the demo."""

from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from apps.receipts import services
from apps.receipts.demo_files import demo_receipt_pdf


def send(resident):
    return services.submit_receipt(
        resident=resident,
        amount=100,
        upload=SimpleUploadedFile("r.pdf", demo_receipt_pdf("t1", 100)),
    )


def run():
    out = StringIO()
    call_command("seed_demo_files", stdout=out)
    return out.getvalue()


def test_missing_files_are_written_back_in_the_demo(resident, settings):
    settings.DEMO_MODE = True
    receipt = send(resident)
    storage = receipt.file.storage
    storage.delete(receipt.file.name)  # like the pre-deploy container's lost disk
    assert "1 written" in run()
    assert storage.exists(receipt.file.name)
    assert storage.open(receipt.file.name).read().startswith(b"%PDF-1.4")
    assert "0 written" in run()  # running it again changes nothing


def test_never_touches_a_real_instance(resident, settings):
    settings.DEMO_MODE = False
    receipt = send(resident)
    receipt.file.storage.delete(receipt.file.name)
    assert "nothing to do" in run()
    assert not receipt.file.storage.exists(receipt.file.name)


def test_demo_pdf_is_a_real_pdf():
    pdf = demo_receipt_pdf("x", 50)
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in pdf and b"xref" in pdf
