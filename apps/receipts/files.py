"""Checking an uploaded receipt file before anything is stored.

- The type comes from the file's first bytes, never from its name or the
  browser: PDF, JPEG, PNG and WebP are accepted. HEIC (iPhone photos) is
  refused with a hint, because many computers cannot open it.
- Images are opened and saved again with Pillow: this drops EXIF and other
  metadata (location, camera) and anything hidden after the picture. The
  photo is turned upright first, as the phone meant it.
- PDFs are kept as they are (they are only ever downloaded, never shown in
  the page).
- The SHA-256 fingerprint is taken from the original bytes, so sending the
  same file twice is recognised whatever happens to the stored copy.
"""

import hashlib
import io

from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps, UnidentifiedImageError

PDF, JPEG, PNG, WEBP = "application/pdf", "image/jpeg", "image/png", "image/webp"
PILLOW_FORMAT = {JPEG: "JPEG", PNG: "PNG", WEBP: "WEBP"}


class FileRefused(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.message, self.code = message, code


def sniff(head):
    """The content type from the first bytes, "heic", or None."""
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP
    if head[4:8] == b"ftyp" and head[8:12] in (
        b"heic",
        b"heix",
        b"hevc",
        b"heif",
        b"mif1",
        b"msf1",
    ):
        return "heic"
    return None


def _reencode(data, content_type):
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            if content_type == JPEG and image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            out = io.BytesIO()
            image.save(
                out, PILLOW_FORMAT[content_type], **({"quality": 90} if content_type != PNG else {})
            )
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise FileRefused(
            _("This picture cannot be read. Take a screenshot of the receipt and send that."),
            "unreadable",
        ) from error
    return out.getvalue()


def check(uploaded, max_bytes):
    """(bytes to store, content type, sha256 of the original) or FileRefused."""
    if uploaded.size > max_bytes:
        raise FileRefused(
            _("The file is too large. The largest allowed is %(mb)s MB.")
            % {"mb": max_bytes // (1024 * 1024)},
            "too_large",
        )
    data = uploaded.read()
    if len(data) > max_bytes:  # the size the browser declared was wrong
        raise FileRefused(_("The file is too large."), "too_large")
    if not data:
        raise FileRefused(_("The file is empty."), "empty")
    content_type = sniff(data[:16])
    if content_type == "heic":
        raise FileRefused(
            _(
                "iPhone photos in HEIC format cannot be accepted. Take a screenshot of the "
                "receipt, or send it as PDF or JPEG."
            ),
            "heic",
        )
    if content_type is None:
        raise FileRefused(_("Send a PDF file or a picture (JPEG, PNG or WebP)."), "wrong_type")
    digest = hashlib.sha256(data).hexdigest()
    stored = data if content_type == PDF else _reencode(data, content_type)
    return stored, content_type, digest
