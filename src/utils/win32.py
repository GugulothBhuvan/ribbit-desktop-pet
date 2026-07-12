"""Shared Win32 helpers (single home for ctypes structs — previously duplicated
in context_engine.py and win32_hook.py, both with a signed-byte bug)."""
import sys
from typing import Optional, Tuple

if sys.platform == "win32":
    import ctypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        # All byte fields are UNSIGNED (c_ubyte). With the previous c_byte,
        # the "unknown" sentinel 255 read back as -1, defeating every
        # `!= 255` guard and reporting battery at -1% (audit M-3).
        _fields_ = [
            ('ACLineStatus', ctypes.c_ubyte),
            ('BatteryFlag', ctypes.c_ubyte),
            ('BatteryLifePercent', ctypes.c_ubyte),
            ('Reserved1', ctypes.c_ubyte),
            ('BatteryLifeTime', ctypes.c_ulong),
            ('BatteryFullLifeTime', ctypes.c_ulong),
        ]

    _NO_SYSTEM_BATTERY = 128  # BatteryFlag value on desktop PCs
    _UNKNOWN = 255


def get_battery_status() -> Tuple[Optional[int], Optional[bool]]:
    """Returns (percent, on_ac_power).

    percent is None when unknown or when the machine has no battery
    (desktop PCs); on_ac_power is None when the AC line status is unknown.
    Callers must treat None as "don't know" — never as a number."""
    if sys.platform != "win32":
        return None, None
    try:
        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None, None

        percent: Optional[int] = int(status.BatteryLifePercent)
        if percent == _UNKNOWN or status.BatteryFlag == _NO_SYSTEM_BATTERY:
            percent = None

        on_ac: Optional[bool]
        if status.ACLineStatus == _UNKNOWN:
            on_ac = None
        else:
            on_ac = status.ACLineStatus == 1

        return percent, on_ac
    except Exception:
        return None, None


def acquire_single_instance_lock(name: str = "DesktopPetAI_SingleInstance") -> bool:
    """Creates a named mutex; returns False if another instance already holds it.
    The mutex handle is intentionally kept for the process lifetime."""
    if sys.platform != "win32":
        return True
    ERROR_ALREADY_EXISTS = 183
    ctypes.windll.kernel32.CreateMutexW(None, False, name)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS
