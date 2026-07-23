from PyQt6.QtGui import QGuiApplication
from PyQt6.QtCore import QRect, QPoint
from src.constants import BOUNCE_COEFFICIENT
from src.utils.logger import get_logger

logger = get_logger("Collision")

class CollisionResolver:
    """
    Retrieves display layouts and detects/resolves collisions against active screen
    boundaries and taskbar work areas.
    """
    
    @staticmethod
    def get_active_screen_geometry(pos: QPoint) -> QRect:
        """Finds which screen contains the coordinate, or returns primary screen."""
        app = QGuiApplication.instance()
        if not app:
            return QRect(0, 0, 1920, 1080)
            
        screens = app.screens()
        for screen in screens:
            if screen.geometry().contains(pos):
                # Returns geometry excluding taskbar
                return screen.availableGeometry()
                
        # Fallback to primary screen
        if screens:
            return screens[0].availableGeometry()
        return QRect(0, 0, 1920, 1080)

    @staticmethod
    def get_virtual_desktop_geometry() -> QRect:
        """Union of every screen's work area — the whole span the pet may roam.

        Walls must come from this, NOT from a single screen: clamping x to the
        active monitor's edges made those edges solid, trapping the pet on one
        display and making it impossible to walk onto an extended monitor.
        """
        if not QGuiApplication.instance():
            return QRect(0, 0, 1920, 1080)

        screens = QGuiApplication.screens()  # static: avoids QCoreApplication typing
        if not screens:
            return QRect(0, 0, 1920, 1080)

        rect = screens[0].availableGeometry()
        for screen in screens[1:]:
            rect = rect.united(screen.availableGeometry())
        return rect

    @staticmethod
    def get_monitor_spans() -> list:
        """Sorted (left, right) x-spans of every physical monitor."""
        spans = [(s.geometry().left(), s.geometry().left() + s.geometry().width())
                 for s in QGuiApplication.screens()]
        return sorted(spans)

    @classmethod
    def skip_dead_gap(cls, x: float, w: int, vx: float) -> float:
        """If the pet's centre has wandered into dead space between non-adjacent
        monitors (a gap no display covers), snap it onto the next monitor in its
        direction of travel so it never disappears into the void. Returns x
        unchanged when the pet is on a real monitor or there's no gap to cross."""
        spans = cls.get_monitor_spans()
        if not spans:
            return x
        cx = x + w / 2
        if any(left <= cx < right for left, right in spans):
            return x  # already on a monitor
        rights_behind = [right for left, right in spans if right <= cx]   # monitors to the left
        lefts_ahead = [left for left, right in spans if left > cx]         # monitors to the right
        if vx >= 0 and lefts_ahead:
            return float(min(lefts_ahead))          # land left edge on the next monitor
        if vx < 0 and rights_behind:
            return float(max(rights_behind) - w)    # land right edge on the previous monitor
        return x

    @classmethod
    def resolve_boundaries(
        cls, x: float, y: float, w: int, h: int, vx: float, vy: float
    ) -> tuple[float, float, float, float, dict]:
        """
        Validates boundaries.
        Returns: (new_x, new_y, new_vx, new_vy, collision_details)
        """
        # Determine active monitor based on pet's center position. The floor and
        # ceiling are per-monitor (each display has its own taskbar / height),
        # but the WALLS come from the full virtual desktop so the pet can walk
        # from one monitor onto another instead of bouncing off a screen seam.
        center_pt = QPoint(int(x + w / 2), int(y + h / 2))
        screen_geom = cls.get_active_screen_geometry(center_pt)
        desktop_geom = cls.get_virtual_desktop_geometry()

        # QRect.right()/bottom() are left+width-1 / top+height-1 (Qt legacy),
        # so compute edges from width/height to avoid a 1px sink into the
        # taskbar / right wall.
        left_wall = desktop_geom.left()
        right_wall = desktop_geom.left() + desktop_geom.width() - w
        top_wall = screen_geom.top()
        floor_y = screen_geom.top() + screen_geom.height() - h  # Top of taskbar
        
        collided_floor = False
        collided_wall = False
        
        # Resolve floor collision
        if y >= floor_y:
            y = floor_y
            vy = 0.0
            collided_floor = True
            
        # Resolve ceiling collision (optional, but keeps pet from flying off top)
        if y <= top_wall:
            y = top_wall
            vy = 0.0
            
        # Resolve wall collision (bounce). Velocities are px/s; kill bounces
        # slower than 20 px/s so the pet doesn't jitter against walls.
        if x <= left_wall:
            x = left_wall
            vx = -vx * BOUNCE_COEFFICIENT
            if abs(vx) < 20.0:
                vx = 0.0
            collided_wall = True
        elif x >= right_wall:
            x = right_wall
            vx = -vx * BOUNCE_COEFFICIENT
            if abs(vx) < 20.0:
                vx = 0.0
            collided_wall = True
            
        details = {
            "collided_floor": collided_floor,
            "collided_wall": collided_wall,
            "floor_y": floor_y,
            "screen_rect": screen_geom
        }
        
        return x, y, vx, vy, details
