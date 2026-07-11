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

    @classmethod
    def resolve_boundaries(
        cls, x: float, y: float, w: int, h: int, vx: float, vy: float
    ) -> tuple[float, float, float, float, dict]:
        """
        Validates boundaries.
        Returns: (new_x, new_y, new_vx, new_vy, collision_details)
        """
        # Determine active monitor based on pet's center position
        center_pt = QPoint(int(x + w / 2), int(y + h / 2))
        screen_geom = cls.get_active_screen_geometry(center_pt)
        
        left_wall = screen_geom.left()
        right_wall = screen_geom.right() - w
        top_wall = screen_geom.top()
        floor_y = screen_geom.bottom() - h  # Top of taskbar
        
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
            
        # Resolve wall collision (bounce)
        if x <= left_wall:
            x = left_wall
            vx = -vx * BOUNCE_COEFFICIENT
            if abs(vx) < 0.5:
                vx = 0.0
            collided_wall = True
        elif x >= right_wall:
            x = right_wall
            vx = -vx * BOUNCE_COEFFICIENT
            if abs(vx) < 0.5:
                vx = 0.0
            collided_wall = True
            
        details = {
            "collided_floor": collided_floor,
            "collided_wall": collided_wall,
            "floor_y": floor_y,
            "screen_rect": screen_geom
        }
        
        return x, y, vx, vy, details
