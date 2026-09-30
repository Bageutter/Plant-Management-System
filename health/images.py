"""Image preparation for vision inference.

Vision models tile an image into fixed-size patches, so a full-resolution phone
photo costs far more tokens (and time) than it adds in useful detail. Downscaling
to the encoder's working resolution is the single largest latency saving.
"""

from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageOps

    PILLOW_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without Pillow installed
    PILLOW_AVAILABLE = False


def downscale_image(payload: bytes, max_edge: int = 896) -> tuple[bytes, str]:
    """Shrink an image so its longest edge is at most ``max_edge`` pixels.

    Returns ``(bytes, mime)``. If Pillow is unavailable or the image cannot be
    decoded, the original bytes are returned unchanged so assessment still works.
    """

    if not PILLOW_AVAILABLE:
        return payload, ""

    try:
        with Image.open(io.BytesIO(payload)) as img:
            # Honour EXIF orientation so the model sees the photo upright.
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            if max(img.size) > max_edge:
                img.thumbnail((max_edge, max_edge), Image.LANCZOS)

            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85, optimize=True)
    except (OSError, ValueError) as exc:
        logger.warning("Could not downscale image, sending as-is: %s", exc)
        return payload, ""

    resized = buffer.getvalue()
    # Only take the re-encoded version when it is actually smaller.
    if len(resized) >= len(payload):
        return payload, ""

    logger.info("downscaled image %s -> %s bytes", len(payload), len(resized))
    return resized, "image/jpeg"


def to_base64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def format_bytes(size: int) -> str:
    """Human-readable size for user-facing messages (``12 MB``, ``850 KB``)."""

    if size >= 1024 * 1024:
        value = size / (1024 * 1024)
        unit = "MB"
    elif size >= 1024:
        value = size / 1024
        unit = "KB"
    else:
        return f"{size} bytes"
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{text} {unit}"


def upload_limit_message(limit: int) -> str:
    """The one sentence shown whenever an upload is over the size limit."""

    return (
        f"The upload is larger than the {format_bytes(limit)} limit. "
        "Choose a smaller photo, or let the page shrink it before sending."
    )
