from typing import List, Optional
from PyQt6.QtGui import QPainter, QPixmap, QTransform
from PyQt6.QtCore import QObject, pyqtSignal
from src.animation.sprite_loader import SpriteLoader
from src.utils.logger import get_logger

logger = get_logger("SpriteRenderer")

class SpriteRenderer(QObject):
    """
    Manages active frame calculations, state-dependent frame rates,
    horizontal mirroring for left/right movements, and QPainter execution.

    Mirrored frames are built once per animation and cached — the previous
    implementation allocated a transformed QPixmap on every paint while the
    pet faced left (audit perf #2).
    """
    animation_finished = pyqtSignal(str)

    def __init__(self, sprite_loader: SpriteLoader):
        super().__init__()
        self.sprite_loader = sprite_loader

        self.current_state = "idle"
        self.frames: List[QPixmap] = []
        self._mirrored_frames: Optional[List[QPixmap]] = None
        self.frame_index = 0
        self.loop = True

        # Mirroring orientation (1 = Right, -1 = Left)
        self.direction = 1

        # Load initial idle frames
        self.set_animation("idle", loop=True)

    def set_animation(self, animation_name: str, loop: bool = True):
        """Loads a new animation sequence and resets frame tracking indices."""
        self.current_state = animation_name
        self.frames = self.sprite_loader.get_animation_frames(animation_name)
        self._mirrored_frames = None  # rebuilt lazily for the new frames
        self.frame_index = 0
        self.loop = loop

        if not self.frames:
            logger.warning(f"No frames found for animation: {animation_name}")

    def set_direction(self, direction: int) -> bool:
        """Sets the facing direction (1 right, -1 left). Returns True if changed."""
        if direction == self.direction:
            return False
        self.direction = direction
        return True

    def advance_frame(self) -> bool:
        """Increments the animation frame pointer. Returns True if the visible
        frame changed (so callers can skip redundant repaints)."""
        if not self.frames:
            return False

        # Keep the active animation marked as in-use so the cache purge
        # never evicts what is on screen (audit M-7)
        self.sprite_loader.touch(self.current_state)

        previous_index = self.frame_index
        self.frame_index += 1
        if self.frame_index >= len(self.frames):
            if self.loop:
                self.frame_index = 0
            else:
                self.frame_index = len(self.frames) - 1
                self.animation_finished.emit(self.current_state)

        return self.frame_index != previous_index

    def _get_mirrored_frames(self) -> List[QPixmap]:
        if self._mirrored_frames is None:
            transform = QTransform().scale(-1, 1)
            self._mirrored_frames = [f.transformed(transform) for f in self.frames]
        return self._mirrored_frames

    def get_current_frame(self) -> QPixmap:
        """Retrieves the active pixmap frame, mirrored (from cache) if heading left."""
        if not self.frames or self.frame_index >= len(self.frames):
            return QPixmap()

        if self.direction == -1:
            return self._get_mirrored_frames()[self.frame_index]
        return self.frames[self.frame_index]

    def render(self, painter: QPainter):
        """Draws current frame onto the window surface."""
        pixmap = self.get_current_frame()
        if not pixmap.isNull():
            painter.drawPixmap(0, 0, pixmap)
