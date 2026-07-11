from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QBuffer, QIODevice
from src.utils.logger import get_logger

logger = get_logger("VisionManager")

class VisionManager:
    """
    Vision Manager Module.
    Captures primary screen frames on-demand and applies image compression.
    """
    @classmethod
    def capture_screen(cls, compression_quality: int = 80) -> bytes:
        """Captures primary screen pixmap and returns compressed PNG byte stream."""
        logger.info("Executing on-demand screen capture...")
        screen = QApplication.primaryScreen()
        if not screen:
            raise Exception("No primary screen detected.")

        # Capture primary screen frame
        pixmap = screen.grabWindow(0)
        
        # Save to buffer using PNG format with compression
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "PNG", compression_quality)
        image_bytes = buffer.data().data()
        
        logger.info(f"Screen capture completed. Compressed PNG size: {len(image_bytes)} bytes")
        return image_bytes
