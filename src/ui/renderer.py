from PyQt6.QtGui import QPainter, QPixmap, QTransform
from PyQt6.QtCore import QObject, pyqtSignal
from src.animation.sprite_loader import SpriteLoader
from src.utils.logger import get_logger

logger = get_logger("SpriteRenderer")

class SpriteRenderer(QObject):
    """
    Manages active frame calculations, state-dependent frame rates,
    horizontal mirroring for left/right movements, and QPainter execution.
    """
    animation_finished = pyqtSignal(str)

    def __init__(self, sprite_loader: SpriteLoader):
        super().__init__()
        self.sprite_loader = sprite_loader
        
        self.current_state = "idle"
        self.frames: list[QPixmap] = []
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
        self.frame_index = 0
        self.loop = loop
        
        if not self.frames:
            logger.warning(f"No frames found for animation: {animation_name}")

    def set_direction(self, direction: int):
        """Sets the horizontal alignment direction (1 for right, -1 for left)."""
        self.direction = direction

    def advance_frame(self):
        """Increments active animation frame pointer."""
        if not self.frames:
            return

        self.frame_index += 1
        if self.frame_index >= len(self.frames):
            if self.loop:
                self.frame_index = 0
            else:
                self.frame_index = len(self.frames) - 1
                self.animation_finished.emit(self.current_state)

    def get_current_frame(self) -> QPixmap:
        """Retrieves the active pixmap frame, programmatically mirrored if heading left."""
        if not self.frames or self.frame_index >= len(self.frames):
            return QPixmap()

        frame = self.frames[self.frame_index]
        
        # If moving left, mirror the frame horizontally (TRD/PRD requirement)
        if self.direction == -1:
            transform = QTransform().scale(-1, 1)
            # Return mirrored frame
            return frame.transformed(transform)
            
        return frame

    def render(self, painter: QPainter):
        """Draws current frame onto the window surface."""
        pixmap = self.get_current_frame()
        if not pixmap.isNull():
            painter.drawPixmap(0, 0, pixmap)
