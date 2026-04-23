"""Generate QR codes as in-memory PNG bytes for Telegram replies."""

from io import BytesIO

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def qr_png(data: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
