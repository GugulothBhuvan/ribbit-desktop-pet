import os
import sys
import time
import ctypes
from PyQt6.QtCore import QThread
from src.event_bus import EventBus, EventType
from src.utils.win32 import get_battery_status
from src.utils.logger import get_logger

logger = get_logger("Win32Observer")

# Win32 structure for GetLastInputInfo
if sys.platform == "win32":
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_uint),
            ("dwTime", ctypes.c_uint),
        ]
else:
    LASTINPUTINFO = None

# Warn about low battery at most once per half hour
BATTERY_WARN_INTERVAL_SEC = 1800.0


class Win32Observer(QThread):
    """
    Background OS Hook Daemon Thread.
    Observes active window shifts, user idle times, and battery status.
    Publishes events to the EventBus without directly invoking the LLM.
    """
    def __init__(self, event_bus: EventBus):
        super().__init__()
        self.event_bus = event_bus
        self.is_running = True

        # State tracking variables
        self.prev_app = ""
        self.prev_title = ""
        self.is_user_idle = False
        self.last_battery_warn = 0.0

        # Idle threshold (5 minutes)
        self.idle_threshold_sec = 300.0

    def run(self):
        logger.info("Win32 Observer thread monitoring started.")
        while self.is_running:
            try:
                if sys.platform == "win32" and LASTINPUTINFO:
                    self._observe_window()
                    self._observe_idle()
                    self._observe_battery()
            except Exception as e:
                logger.error(f"Error in Win32Observer execution loop: {e}")

            # Poll every 1.0 seconds to consume ~0% CPU
            time.sleep(1.0)

    def stop(self):
        self.is_running = False
        self.wait()
        logger.info("Win32 Observer thread stopped.")

    def _observe_window(self):
        """Monitors the active foreground window process and title."""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return

        # Get window title
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        title = "Unknown"
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value

        # Get Process ID and Process Name
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        app_name = "Unknown"
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid.value)
        if handle:
            try:
                buffer = ctypes.create_unicode_buffer(260)
                size = ctypes.c_ulong(260)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    app_name = os.path.basename(buffer.value)
            except Exception:
                pass
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)

        if app_name != self.prev_app or title != self.prev_title:
            self.prev_app = app_name
            self.prev_title = title
            # DEBUG level: window titles can contain sensitive content and
            # must not accumulate in the persistent INFO log.
            logger.debug(f"Active window change: {app_name} - '{title}'")
            self.event_bus.publish(EventType.APPLICATION_CHANGED, {
                "app_name": app_name,
                "title": title
            })

    def _observe_idle(self):
        """Tracks keyboard/mouse idle time via GetLastInputInfo."""
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            idle_sec = millis / 1000.0

            # Transition to idle
            if idle_sec >= self.idle_threshold_sec and not self.is_user_idle:
                self.is_user_idle = True
                logger.info(f"User is idle ({int(idle_sec)}s). Emitting USER_IDLE event.")
                self.event_bus.publish(EventType.USER_IDLE, {"idle_duration_sec": int(idle_sec)})

            # Transition back to active
            elif idle_sec < 5.0 and self.is_user_idle:
                self.is_user_idle = False
                logger.info("User became active. Emitting USER_ACTIVE event.")
                self.event_bus.publish(EventType.USER_ACTIVE, {"active_time": time.time()})

            # Check screen stability for vision (stable for 3-5 seconds after typing/moving mouse)
            if 3.0 <= idle_sec < 5.0:
                self.event_bus.publish(EventType.SCREEN_STABLE, {"idle_duration_sec": int(idle_sec)})

    def _observe_battery(self):
        """Publishes a low-battery warning while discharging, at most every 30 min.

        This is the single owner of BATTERY_WARNING (the scheduler no longer
        duplicates the check)."""
        percent, on_ac = get_battery_status()
        if percent is None or on_ac is not False:
            return

        if percent <= 20:
            now = time.time()
            if now - self.last_battery_warn >= BATTERY_WARN_INTERVAL_SEC:
                self.last_battery_warn = now
                self.event_bus.publish(EventType.BATTERY_WARNING, {
                    "percent": percent,
                    "charging": False
                })
