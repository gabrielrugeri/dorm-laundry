"""Fake receipt files for the demo: small but real PDFs and pictures, so the
receipt viewer shows something. Never used outside DEMO_MODE."""

import io

from PIL import Image, ImageDraw


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def demo_pdf(*lines):
    """A one-page PDF with a few lines of ASCII text."""
    text = (
        "BT /F1 18 Tf 60 760 Td 24 TL "
        + " ".join(f"({_escape(line)}) Tj T*" for line in lines)
        + " ET"
    )
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        "/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(text)} >>\nstream\n{text}\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


def demo_receipt_pdf(tag, amount=None):
    lines = ["DEMO receipt - not a real payment", f"Reference: {tag}"]
    if amount is not None:
        lines.append(f"Amount: {amount} RUB")
    return demo_pdf(*lines)


def demo_png(text="DEMO", size=(360, 220)):
    image = Image.new("RGB", size, (241, 245, 249))
    draw = ImageDraw.Draw(image)
    draw.rectangle([6, 6, size[0] - 7, size[1] - 7], outline=(29, 78, 216), width=4)
    draw.text((24, size[1] // 2 - 10), text, fill=(15, 23, 42))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
