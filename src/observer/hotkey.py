"""Global push-to-talk hotkey (plan 5.6).

The pet window is designed to never take keyboard focus (PRD 8.6), which made
the old focused-window Space handler unusable — and when it *did* have focus
it swallowed the user's spacebar. A system-wide RegisterHotKey fixes both:
Ctrl+Shift+Space toggles recording from anywhere.
"""
import sys
import ctypes
from PyQt6.QtCore import QThread
from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger("GlobalHotkey")

MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
# Without MOD_NOREPEAT, holding the combo fires WM_HOTKEY at the keyboard's
# auto-repeat rate (~30/s), machine-gunning the PTT toggle (observed live).
MOD_NOREPEAT = 0x4000
VK_SPACE = 0x20
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1

HOTKEY_LABEL = "Ctrl+Shift+Space"


class GlobalHotkeyListener(QThread):
    """Runs a native message loop on its own thread; publishes PTT_TOGGLED."""

    def __init__(self, event_bus: EventBus):
        super().__init__()
        self.event_bus = event_bus
        self._native_thread_id = None

    def run(self):
        if sys.platform != "win32":
            logger.info("Global hotkey not supported on this platform; skipping.")
            return

        import ctypes.wintypes as wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._native_thread_id = kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_SPACE):
            logger.error(f"Could not register global PTT hotkey {HOTKEY_LABEL} "
                         "(already in use by another app?). Voice input disabled.")
            return
        logger.info(f"Global PTT hotkey registered: {HOTKEY_LABEL}")

        try:
            msg = wintypes.MSG()
            # GetMessageW returns 0 on WM_QUIT, -1 on error
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                    logger.info("PTT hotkey pressed.")
                    self.event_bus.publish(EventType.PTT_TOGGLED, {})
        finally:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            logger.info("Global PTT hotkey unregistered.")

    def stop(self):
        if sys.platform == "win32" and self._native_thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._native_thread_id, WM_QUIT, 0, 0)
        self.wait(2000)
