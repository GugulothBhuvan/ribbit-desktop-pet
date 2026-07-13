"""Global push-to-talk hotkey (plan 5.6).

The pet window is designed to never take keyboard focus (PRD 8.6), which made
the old focused-window Space handler unusable — and when it *did* have focus
it swallowed the user's spacebar. A system-wide RegisterHotKey fixes both.

The combo is configurable via Config.PTT_HOTKEY (default "ctrl+space").
"""
import sys
import ctypes
from PyQt6.QtCore import QThread
from src.config import Config
from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger("GlobalHotkey")

# Win32 modifier flags. MOD_NOREPEAT is critical: without it, holding the combo
# fires WM_HOTKEY at the keyboard auto-repeat rate (~30/s), machine-gunning the
# toggle (observed live).
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
HOTKEY_ID = 1

_MODIFIER_NAMES = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "super": MOD_WIN,
}
_NAMED_KEYS = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    **{f"f{i}": 0x70 + (i - 1) for i in range(1, 13)},
}


def parse_hotkey(spec: str):
    """Parses a spec like 'ctrl+space' or 'ctrl+alt+j' into (modifiers, vk, label).
    Returns None if the spec has no valid key."""
    mods = 0
    vk = None
    labels = []
    for part in (p.strip().lower() for p in spec.split("+") if p.strip()):
        if part in _MODIFIER_NAMES:
            mods |= _MODIFIER_NAMES[part]
            labels.append(part.capitalize())
        elif part in _NAMED_KEYS:
            vk = _NAMED_KEYS[part]
            labels.append(part.capitalize())
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
            labels.append(part.upper())
    if vk is None:
        return None
    return mods, vk, "+".join(labels)


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

        parsed = parse_hotkey(Config.PTT_HOTKEY) or parse_hotkey("ctrl+space")
        mods, vk, label = parsed

        import ctypes.wintypes as wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._native_thread_id = kernel32.GetCurrentThreadId()

        if not user32.RegisterHotKey(None, HOTKEY_ID, mods | MOD_NOREPEAT, vk):
            logger.error(f"Could not register global PTT hotkey {label} "
                         "(already claimed by another app?). Set PTT_HOTKEY in .env "
                         "to a free combo. Voice input disabled for now.")
            return
        logger.info(f"Global PTT hotkey registered: {label}")

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
