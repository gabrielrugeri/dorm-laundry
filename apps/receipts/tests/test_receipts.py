"""Receipts: file checks, immediate credit, guardrails, duplicates, access.
Every name here is fake; images are drawn in memory."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.dorms.models import GlobalSettings
from apps.keylog.tests.test_services import make_staff
from apps.ledger.models import LedgerEntry
from apps.receipts import files, services
from apps.receipts.models import Receipt

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)  # noon in Moscow


def picture(fmt="PNG", colour=(10, 20, 30), exif=None, size=(40, 30)):
    out = io.BytesIO()
    image = Image.new("RGB", size, colour)
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(out, fmt, **kwargs)
    return out.getvalue()


def upload(data, name="receipt.png"):
    return SimpleUploadedFile(name, data, content_type="application/octet-stream")


def pdf(text=b"1"):
    return b"%PDF-1.4\n% fake receipt " + text + b"\n%%EOF\n"


def submit(resident, amount=100, data=None, now=NOW):
    return services.submit_receipt(
        resident=resident, amount=amount, upload=upload(data or pdf(str(amount).encode())), now=now
    )


# --- File checks ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (pdf(), files.PDF),
        (picture("PNG"), files.PNG),
        (picture("JPEG"), files.JPEG),
        (picture("WEBP"), files.WEBP),
    ],
    ids=["pdf", "png", "jpeg", "webp"],
)
def test_accepted_types_are_recognised_by_their_bytes(data, content_type):
    stored, found, digest = files.check(upload(data, name="anything.txt"), 10 * 1024 * 1024)
    assert found == content_type
    assert len(digest) == 64


def test_photo_metadata_is_removed():
    exif = Image.Exif()
    exif[0x010F] = "FakeCamMaker"  # camera maker; GPS would be stripped the same way
    data = picture("JPEG", exif=exif)
    assert b"FakeCamMaker" in data
    stored, _type, digest = files.check(upload(data), 10 * 1024 * 1024)
    assert b"FakeCamMaker" not in stored
    # The fingerprint is of the original bytes, so a re-send is still a duplicate.
    assert digest == files.hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 30, "heic"),
        (b"<html><script>alert(1)</script></html>", "wrong_type"),
        (b"MZ\x90\x00 an exe", "wrong_type"),
        (b"\x89PNG\r\n\x1a\n" + b"broken", "unreadable"),
        (b"", "empty"),
    ],
    ids=["heic", "html", "exe", "broken-png", "empty"],
)
def test_other_files_are_refused(data, code):
    with pytest.raises(files.FileRefused) as refused:
        files.check(upload(data), 10 * 1024 * 1024)
    assert refused.value.code == code


def test_too_large_is_refused():
    with pytest.raises(files.FileRefused) as refused:
        files.check(upload(pdf(b"x" * 2000)), 1000)
    assert refused.value.code == "too_large"


# --- Immediate credit -----------------------------------------------------------------


def test_receipt_credits_the_balance_at_once(resident):
    receipt = submit(resident, amount=300)
    entry = LedgerEntry.objects.get(receipt=receipt)
    assert (entry.kind, entry.amount, entry.resident) == ("credit", 300, resident)
    assert LedgerEntry.objects.balance(resident) == 300
    assert receipt.status == Receipt.Status.CREDITED
    assert receipt.file.storage.exists(receipt.file.name)
    assert "receipt" not in receipt.file.name.rsplit("/", 1)[-1]  # random name
    event = AuditEvent.objects.get(action="receipt.credit")
    assert event.after["amount"] == 300 and "sha256" not in event.after


def test_same_file_is_refused_for_everyone(resident, other_resident):
    data = pdf(b"same")
    submit(resident, data=data)
    with pytest.raises(services.ReceiptRefused) as refused:
        submit(other_resident, data=data)
    assert refused.value.code == "duplicate"
    assert LedgerEntry.objects.balance(other_resident) == 0
    assert AuditEvent.objects.filter(action="receipt.refused").count() == 1


def test_largest_amount_per_receipt(resident):
    with pytest.raises(services.ReceiptRefused) as refused:
        submit(resident, amount=2001)
    assert refused.value.code == "max_amount"
    assert not Receipt.objects.exists()


def test_daily_limit_counts_accepted_receipts_only(resident):
    with pytest.raises(services.ReceiptRefused):
        submit(resident, amount=99_999)  # refused: does not use up the day
    for n in range(3):
        submit(resident, amount=10 + n)
    with pytest.raises(services.ReceiptRefused) as refused:
        submit(resident, amount=20)
    assert refused.value.code == "daily_limit"
    submit(resident, amount=20, now=NOW + timedelta(days=1))  # next day is fine


def test_thirty_day_cap(resident):
    GlobalSettings.objects.filter(pk=1).update(max_uploads_per_day=20)
    for n in range(2):
        submit(resident, amount=2000, data=pdf(f"a{n}".encode()))
    submit(resident, amount=1000, data=pdf(b"b"))  # 5000 in 30 days: the cap
    with pytest.raises(services.ReceiptRefused) as refused:
        submit(resident, amount=1, data=pdf(b"c"))
    assert refused.value.code == "30_day_cap"
    later = NOW + timedelta(days=31)
    submit(resident, amount=500, data=pdf(b"d"), now=later)


def test_refused_receipt_leaves_no_file(resident, private_media):
    submit(resident, data=pdf(b"first"))
    with pytest.raises(services.ReceiptRefused):
        submit(resident, data=pdf(b"first"))
    stored = [p for p in private_media.rglob("*") if p.is_file()]
    assert len(stored) == 1


def test_resident_with_receipts_has_history(resident):
    from apps.accounts.services import has_history

    submit(resident)
    assert has_history(resident)


# --- Screens and file access ----------------------------------------------------------

NEW = reverse("receipts:new")


def test_upload_screen_tops_up_and_shows_the_receipt(client, resident):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    page = client.get(NEW)
    assert page.status_code == 200 and "How to pay" in page.content.decode()
    response = client.post(NEW, {"amount": 250, "file": upload(picture())}, follow=True)
    assert "Your balance was topped up by 250 RUB." in response.content.decode()
    receipt = Receipt.objects.get()
    assert reverse("receipts:view", kwargs={"pk": receipt.pk}) in response.content.decode()


def test_upload_screen_shows_refusal(client, resident):
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    page = client.post(NEW, {"amount": 100, "file": upload(b"<html>", name="x.png")})
    assert "Send a PDF file or a picture" in page.content.decode()
    assert not Receipt.objects.exists()


def test_receipt_file_for_owner_and_admins_only(client, resident, other_resident, dormitory):
    receipt = submit(resident)
    url = reverse("receipts:file", kwargs={"pk": receipt.pk})
    assert client.get(url).status_code == 404  # anonymous
    client.force_login(other_resident.user)
    assert client.get(url).status_code == 404
    client.force_login(make_staff(dormitory, "keys", role=roles.MANAGER))
    assert client.get(url).status_code == 404  # managers never see receipts
    client.force_login(resident.user)
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert b"".join(response.streaming_content).startswith(b"%PDF-")
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    assert client.get(url).status_code == 200


def test_admin_of_another_dormitory_cannot_see_the_receipt(client, resident, other_dormitory):
    receipt = submit(resident)
    client.force_login(make_staff(other_dormitory, "stranger", role=roles.ADMIN))
    assert client.get(reverse("receipts:file", kwargs={"pk": receipt.pk})).status_code == 404


def test_private_files_have_no_public_url(resident):
    receipt = submit(resident)
    with pytest.raises(ValueError):
        receipt.file.url  # noqa: B018


def test_missing_file_is_not_found_not_an_error(client, resident):
    receipt = submit(resident)
    receipt.file.storage.delete(receipt.file.name)
    client.force_login(resident.user)
    assert client.get(reverse("receipts:file", kwargs={"pk": receipt.pk})).status_code == 404


# --- Viewer (sandboxed inline display) ------------------------------------------------


def test_viewer_shows_own_receipt_inline_and_sandboxed(client, resident, other_resident, dormitory):
    receipt = submit(resident)
    view = reverse("receipts:view", kwargs={"pk": receipt.pk})
    inline = reverse("receipts:inline", kwargs={"pk": receipt.pk})
    client.force_login(resident.user)
    page = client.get(view).content.decode()
    assert inline in page and reverse("receipts:file", kwargs={"pk": receipt.pk}) in page
    response = client.get(inline)
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("inline;")
    csp = response["Content-Security-Policy"]
    assert csp.startswith("sandbox;") and "default-src 'none'" in csp
    assert "script-src" not in csp  # nothing may run
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert response["X-Content-Type-Options"] == "nosniff"
    for target in (view, inline):
        client.force_login(other_resident.user)
        assert client.get(target).status_code == 404
        client.force_login(make_staff(dormitory, f"keys-{target[-3:]}", role=roles.MANAGER))
        assert client.get(target).status_code == 404


def test_admin_receipt_page_embeds_the_sandboxed_file(client, resident, dormitory):
    receipt = submit(resident)
    client.force_login(make_staff(dormitory, "boss", role=roles.ADMIN))
    html = client.get(reverse("manage:receipt", kwargs={"pk": receipt.pk})).content.decode()
    assert f'<iframe src="{reverse("receipts:inline", kwargs={"pk": receipt.pk})}"' in html


def test_balance_links_to_the_viewer_not_a_silent_download(client, resident):
    receipt = submit(resident)
    client.force_login(resident.user)
    html = client.get(reverse("ledger:balance")).content.decode()
    assert reverse("receipts:view", kwargs={"pk": receipt.pk}) in html
