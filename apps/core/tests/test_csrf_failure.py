"""A refused form shows a plain page and logs why, without secrets."""

import logging

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse


def test_refused_upload_logs_the_reason_and_shape(resident, caplog):
    client = Client(enforce_csrf_checks=True)
    client.force_login(resident.user)
    client.cookies["django_language"] = "en"
    with caplog.at_level(logging.WARNING, logger="dorm_laundry.csrf"):
        response = client.post(
            reverse("receipts:new"),
            {"amount": 100, "file": SimpleUploadedFile("r.pdf", b"%PDF-1.4 x")},
        )
    assert response.status_code == 403
    assert "The form could not be sent" in response.content.decode()
    record = next(r for r in caplog.records if r.name == "dorm_laundry.csrf")
    message = record.getMessage()
    assert "reason='CSRF cookie not set.'" in message
    assert "file_fields=1" in message and "token_field=False" in message
    assert resident.full_name not in message and resident.student_code not in message


def test_lost_body_is_visible_in_the_log(resident, caplog):
    """What a browser dropping the upload looks like: a large Content-Length
    but no fields at all arrived."""
    client = Client(enforce_csrf_checks=True)
    client.force_login(resident.user)
    client.get(reverse("receipts:new"))  # sets the CSRF cookie
    with caplog.at_level(logging.WARNING, logger="dorm_laundry.csrf"):
        response = client.generic(
            "POST",
            reverse("receipts:new"),
            data=b"",
            content_type="multipart/form-data; boundary=x",
            HTTP_CONTENT_LENGTH="482113",
        )
    assert response.status_code == 403
    message = next(r for r in caplog.records if r.name == "dorm_laundry.csrf").getMessage()
    assert "post_fields=0" in message and "file_fields=0" in message
    assert "CSRF token missing" in message
