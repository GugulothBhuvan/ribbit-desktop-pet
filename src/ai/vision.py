"""On-demand screenshot post-processing (TRD 9.3).

The GUI thread only grabs the raw QImage; this module's downscale + JPEG
encode runs on the background worker loop — the previous implementation
PNG-encoded the full-resolution screen on the GUI thread, stalling rendering
for 100ms+ per capture (audit M-10). QImage is a thread-safe value class, so
processing it off the GUI thread is supported.
"""
from PyQt6.QtGui import QImage
from PyQt6.QtCore import QBuffer, QIODevice, Qt
from src.utils.logger import get_logger

logger = get_logger("Vision")

MAX_DIMENSION = 1024
JPEG_QUALITY = 70


def process_capture(image: QImage) -> bytes:
    """Downscales a captured frame to <=1024px and encodes it as JPEG bytes."""
    if image.isNull():
        raise ValueError("Captured image is null.")

    if image.width() > MAX_DIMENSION or image.height() > MAX_DIMENSION:
        image = image.scaled(
            MAX_DIMENSION, MAX_DIMENSION,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "JPEG", JPEG_QUALITY):
        raise RuntimeError("JPEG encoding of screen capture failed.")

    data = bytes(buffer.data())
    logger.info(f"Screen capture processed: {image.width()}x{image.height()}, {len(data)} bytes JPEG")
    return data
