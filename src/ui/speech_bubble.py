from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont, QPen, QBrush, QPolygon
from src.config import Config
from src.constants import MAX_BUBBLE_WIDTH, READING_TIME_PER_WORD_MS
from src.utils.logger import get_logger

logger = get_logger("SpeechBubble")

class SpeechBubble(QWidget):
    """
    Floating speech bubble painted next to the pet.
    Implements a typewriter typing animation, auto-resizing, and auto-fade mechanisms.
    Emits `dismissed` when the fade-out completes so the window can return the
    pet from TALK back to IDLE.
    """
    dismissed = pyqtSignal()

    def __init__(self):
        super().__init__()
        
        # Configure tool window traits (borderless, stay-on-top, click-through)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        
        self.full_text = ""
        self.current_visible_text = ""
        self.char_index = 0

        # Streaming lifecycle: a placeholder ("Thinking...") is replaced by the
        # first streamed chunk instead of being concatenated with it (audit M-1);
        # while a stream is active the bubble never starts its dismiss fade.
        self.is_placeholder = False
        self.stream_active = False

        # Animation & Fade settings
        self.opacity = 1.0
        self.is_fading = False

        # Sizing boundaries
        self.padding = 12
        self.bubble_rect = QRect()

        # Font metrics are reused across paints/chunks instead of being
        # constructed per call
        self.font = QFont("Segoe UI", 9)
        from PyQt6.QtGui import QFontMetrics
        self.font_metrics = QFontMetrics(self.font)
        
        # Timers
        self.typewriter_timer = QTimer(self)
        self.typewriter_timer.timeout.connect(self._type_next_char)
        
        self.fade_timer = QTimer(self)
        self.fade_timer.timeout.connect(self._perform_fade)
        
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.start_fade)

    def show_text(self, text: str, pet_pos: QPoint, pet_size: int, placeholder: bool = False):
        """Prepares and displays the bubble next to the pet.

        placeholder=True marks transient status text ("Thinking...") that the
        first streamed chunk should replace entirely."""
        if not text:
            self.hide()
            return

        self.full_text = text
        self.current_visible_text = ""
        self.char_index = 0
        self.opacity = 1.0
        self.is_fading = False
        self.is_placeholder = placeholder
        self.stream_active = False

        self.fade_timer.stop()
        self.dismiss_timer.stop()
        
        # Calculate dynamic size based on text length
        self._calculate_dimensions()
        
        # Position bubble centered above the pet
        self.position_bubble(pet_pos, pet_size)
        self.show()
        
        # Start typewriter animation (speed is a persisted user setting)
        self.typewriter_timer.start(Config.SPEECH_TYPING_SPEED_MS)

    def append_chunk(self, chunk: str, pet_pos: QPoint, pet_size: int):
        """Streams a text chunk (real-time stream update)."""
        if self.is_placeholder:
            # First real chunk replaces the "Thinking..." placeholder
            self.full_text = ""
            self.current_visible_text = ""
            self.char_index = 0
            self.is_placeholder = False

        self.stream_active = True
        self.is_fading = False
        self.opacity = 1.0
        self.fade_timer.stop()
        self.dismiss_timer.stop()  # never fade out mid-stream

        self.full_text += chunk
        self._calculate_dimensions()
        self.position_bubble(pet_pos, pet_size)

        if not self.typewriter_timer.isActive():
            self.show()
            self.typewriter_timer.start(Config.SPEECH_TYPING_SPEED_MS)

    def finish_stream(self):
        """Marks the stream complete; the dismiss countdown starts once the
        typewriter catches up (or immediately if it already has)."""
        self.stream_active = False
        if not self.typewriter_timer.isActive() and self.isVisible():
            self._start_dismiss_countdown()

    def position_bubble(self, pet_pos: QPoint, pet_size: int):
        """Aligns the speech bubble relative to the pet coordinates."""
        # Align center horizontally above the pet window
        bubble_x = pet_pos.x() + (pet_size - self.width()) // 2
        bubble_y = pet_pos.y() - self.height() - 5  # 5px offset above pet
        
        # Clamps to avoid placing bubble off screen
        screen = self.screen()
        if screen:
            screen_rect = screen.availableGeometry()
            if bubble_x < screen_rect.left() + 10:
                bubble_x = screen_rect.left() + 10
            elif bubble_x + self.width() > screen_rect.right() - 10:
                bubble_x = screen_rect.right() - self.width() - 10
                
            if bubble_y < screen_rect.top():
                # If too high, show speech bubble underneath pet instead
                bubble_y = pet_pos.y() + pet_size + 5
                
        self.move(bubble_x, bubble_y)

    def _calculate_dimensions(self):
        """Measures font layouts to auto-size the speech bubble boundaries."""
        fm = self.font_metrics

        # Wrap bounds
        max_text_width = MAX_BUBBLE_WIDTH - (self.padding * 2)
        text_rect = fm.boundingRect(
            0, 0, max_text_width, 1000,
            Qt.TextFlag.TextWordWrap,
            self.full_text if self.full_text else "Thinking..."
        )
        
        # Dimensions
        w = text_rect.width() + (self.padding * 2) + 4
        h = text_rect.height() + (self.padding * 2) + 12 # Extra height for bottom tail
        
        self.bubble_rect = QRect(2, 2, w - 4, h - 14)
        self.setFixedSize(w, h)

    def _type_next_char(self):
        """Advances typing text index by index."""
        if self.char_index < len(self.full_text):
            self.char_index += 1
            self.current_visible_text = self.full_text[:self.char_index]
            self.update()
        else:
            self.typewriter_timer.stop()
            # While streaming, more text may still arrive — don't dismiss yet
            if not self.stream_active:
                self._start_dismiss_countdown()

    def _start_dismiss_countdown(self):
        """Reading delay proportional to word count, then fade."""
        word_count = len(self.full_text.split())
        reading_duration = max(3000, word_count * READING_TIME_PER_WORD_MS)
        self.dismiss_timer.start(reading_duration)

    def start_fade(self):
        """Triggers the opacity fade-out sequence."""
        self.is_fading = True
        self.fade_timer.start(30)  # ~30 FPS fade updates

    def _perform_fade(self):
        """Gradually reduces opacity and hides bubble."""
        self.opacity -= 0.05
        if self.opacity <= 0.0:
            self.opacity = 0.0
            self.fade_timer.stop()
            self.hide()
            self.dismissed.emit()
        else:
            self.update()

    def paintEvent(self, event):
        if not self.current_visible_text and not self.full_text:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Apply current opacity
        painter.setOpacity(self.opacity)
        
        # 1. Paint background bubble body
        brush = QBrush(QColor(255, 255, 255, 245))  # High-quality off-white
        pen = QPen(QColor(40, 40, 40, 200), 1.5)
        painter.setBrush(brush)
        painter.setPen(pen)
        
        # Rounded Rect
        painter.drawRoundedRect(self.bubble_rect, 8.0, 8.0)
        
        # 2. Paint speech tail pointing downwards
        tail_polygon = QPolygon([
            QPoint(self.width() // 2 - 8, self.bubble_rect.bottom()),
            QPoint(self.width() // 2 + 8, self.bubble_rect.bottom()),
            QPoint(self.width() // 2, self.height() - 2)
        ])
        # Draw tail
        painter.drawPolygon(tail_polygon)
        
        # Mask out boundary line between tail and bubble body
        painter.setPen(Qt.PenStyle.NoPen)
        mask_rect = QRect(
            self.width() // 2 - 7, self.bubble_rect.bottom() - 2,
            14, 4
        )
        painter.drawRect(mask_rect)
        
        # 3. Paint typewriter text
        painter.setPen(QPen(QColor(25, 25, 25, 255)))
        painter.setFont(self.font)
        
        text_draw_rect = QRect(
            self.bubble_rect.left() + self.padding,
            self.bubble_rect.top() + self.padding,
            self.bubble_rect.width() - (self.padding * 2),
            self.bubble_rect.height() - (self.padding * 2)
        )
        
        # Draw substring
        painter.drawText(
            text_draw_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            self.current_visible_text if self.current_visible_text else "..."
        )
