import os
import json
import time
from typing import Dict, List, Tuple
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QTimer
from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("SpriteLoader")

class SpriteLoader:
    """
    Loads, slices, scales, and caches animation frames from the sprite sheet.
    Implements a resource cleanup mechanism to purge unused frames after 60 seconds
    to maintain a low memory footprint (<180 MB).

    Must be constructed on the GUI thread AFTER QApplication exists
    (it creates QPixmaps and a QTimer). The CompositionRoot guarantees this.
    """

    def __init__(self):
        # Configure mascot path dynamically from config overrides
        self.set_mascot_directory(Config.SELECTED_MASCOT)
        
        self.metadata: dict = {}
        self.sheet_pixmap: QPixmap = None
        self.scale_factor = Config.ANIMATION_SCALE
        
        # Cache for animations: { anim_name: [QPixmap, ...] }
        self._animation_cache: Dict[str, List[QPixmap]] = {}
        # Tracks last time each animation cache was accessed
        self._last_accessed: Dict[str, float] = {}
        
        # Load metadata and sheet
        self.load_metadata()
        self.load_sprite_sheet()
        
        # Setup cleanup timer (every 10 seconds check for stale assets)
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.cleanup_stale_caches)
        self.cleanup_timer.start(10000)  # 10s interval

    def set_mascot_directory(self, mascot_name: str):
        """Sets the directory paths for the selected mascot name."""
        self.sprite_dir = os.path.join("assets", "sprites", mascot_name)
        self.metadata_path = os.path.join(self.sprite_dir, "metadata.json")

    def set_mascot(self, mascot_name: str):
        """Swaps active mascot sheet on the fly, clearing caches."""
        logger.info(f"Swapping active mascot to: {mascot_name}")
        self.set_mascot_directory(mascot_name)
        self._animation_cache.clear()
        self._last_accessed.clear()
        self.load_metadata()
        self.load_sprite_sheet()

    def load_metadata(self):
        try:
            if os.path.exists(self.metadata_path):
                with open(self.metadata_path, 'r', encoding='utf-8') as f:
                    self.metadata = json.load(f)
                logger.info("Sprite sheet metadata loaded successfully.")
            else:
                logger.error(f"Metadata file not found: {self.metadata_path}")
        except Exception as e:
            logger.error(f"Error loading sprite metadata: {e}")

    def load_sprite_sheet(self):
        try:
            sheet_name = self.metadata.get("sprite_sheet", "sprite_sheet.png")
            sheet_path = os.path.join(self.sprite_dir, sheet_name)
            
            if os.path.exists(sheet_path):
                self.sheet_pixmap = QPixmap(sheet_path)
                logger.info(f"Sprite sheet loaded: {sheet_path} ({self.sheet_pixmap.width()}x{self.sheet_pixmap.height()})")
            else:
                logger.error(f"Sprite sheet image not found: {sheet_path}")
        except Exception as e:
            logger.error(f"Error loading sprite sheet image: {e}")

    def set_scale(self, scale: float):
        """Update animation scale factor and clear cache to redraw at new resolution."""
        if self.scale_factor != scale:
            logger.info(f"Updating animation scale factor to {scale}")
            self.scale_factor = scale
            self._animation_cache.clear()

    def get_animation_frames(self, animation_name: str) -> List[QPixmap]:
        """Gets sliced and scaled frames for the specified animation name."""
        current_time = time.time()
        self._last_accessed[animation_name] = current_time
        
        # Return from cache if hit
        if animation_name in self._animation_cache:
            return self._animation_cache[animation_name]

        # Slicing and scaling frames from sheet
        logger.info(f"Cache miss: Slicing and scaling animation '{animation_name}'")
        
        if not self.sheet_pixmap or not self.metadata:
            logger.warning("Sprite sheet or metadata not initialized, returning empty frame list.")
            return []

        anim_data = self.metadata.get("animations", {}).get(animation_name)
        if not anim_data:
            logger.error(f"Animation '{animation_name}' not defined in metadata.json")
            return []

        frames = []
        for f_info in anim_data.get("frames", []):
            x = f_info.get("x", 0)
            y = f_info.get("y", 0)
            w = f_info.get("w", 128)
            h = f_info.get("h", 128)
            
            # Slices sub-rectangle from main sheet
            sub_pixmap = self.sheet_pixmap.copy(x, y, w, h)
            
            # Scale frame using smooth transformations
            scaled_w = int(w * self.scale_factor)
            scaled_h = int(h * self.scale_factor)
            
            scaled_pixmap = sub_pixmap.scaled(
                scaled_w, scaled_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            frames.append(scaled_pixmap)

        self._animation_cache[animation_name] = frames
        return frames

    def get_animation_fps(self, animation_name: str) -> int:
        """Gets frames per second for specified animation."""
        if not self.metadata:
            return 8
        anim_data = self.metadata.get("animations", {}).get(animation_name, {})
        return anim_data.get("fps", 8)

    def is_looping(self, animation_name: str) -> bool:
        """Determines if the animation loops."""
        if not self.metadata:
            return True
        anim_data = self.metadata.get("animations", {}).get(animation_name, {})
        return anim_data.get("loop", True)

    def cleanup_stale_caches(self):
        """Flushes cached frames for animations that haven't been requested in over 60 seconds."""
        current_time = time.time()
        stale_animations = []
        
        for anim_name, last_time in list(self._last_accessed.items()):
            # Idle walk and talk are common, but let's flush any animation older than 60s
            if current_time - last_time > 60.0:
                stale_animations.append(anim_name)
                
        for anim in stale_animations:
            if anim in self._animation_cache:
                logger.info(f"Purging stale animation '{anim}' from LRU memory cache.")
                del self._animation_cache[anim]
                del self._last_accessed[anim]

    @property
    def frame_width(self) -> int:
        """Exposes the configured base frame width."""
        if not self.metadata:
            return 128
        return self.metadata.get("frame_width", 128)

    @property
    def frame_height(self) -> int:
        """Exposes the configured base frame height."""
        if not self.metadata:
            return 128
        return self.metadata.get("frame_height", 128)
