import os
import sys
import time
import subprocess
from datetime import datetime
from typing import Dict, Any

# Platform-specific imports for context gathering using standard libraries
if sys.platform == "win32":
    import ctypes
    
    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ('ACLineStatus', ctypes.c_byte),
            ('BatteryFlag', ctypes.c_byte),
            ('BatteryLifePercent', ctypes.c_byte),
            ('Reserved1', ctypes.c_byte),
            ('BatteryLifeTime', ctypes.c_ulong),
            ('BatteryFullLifeTime', ctypes.c_ulong),
        ]
else:
    ctypes = None

from src.utils.logger import get_logger

logger = get_logger("ContextEngine")

class ContextEngine:
    """
    Assembles real-time system and application telemetry (time, active window,
    battery metrics, pet physical state) to feed into the prompt engine.
    """
    def __init__(self):
        self.start_time = time.time()

    def get_active_window_title(self) -> str:
        """Retrieves the foreground window title (Windows specific, safe fallback)."""
        if sys.platform == "win32" and ctypes:
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
                    return buff.value
            except Exception as e:
                logger.debug(f"Failed to get active window title on Windows: {e}")
        return "Unknown Application"

    def get_battery_level(self) -> int:
        """Retrieves the system battery charge percentage (Windows specific, safe fallback)."""
        if sys.platform == "win32" and ctypes:
            try:
                status = SYSTEM_POWER_STATUS()
                if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                    percent = status.BatteryLifePercent
                    # 255 indicates status unknown
                    if percent != 255:
                        return int(percent)
            except Exception as e:
                logger.debug(f"Failed to get system battery level on Windows: {e}")
        return 100  # Default fallback if on desktop or other OS without support

    def get_git_context(self) -> Dict[str, Any]:
        """Gathers local Git status details using subprocess checks."""
        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=0.5
            )
            if res.returncode != 0:
                return {"git_available": False, "uncommitted_files_count": 0, "last_commit_message": "unknown"}
            
            lines = res.stdout.strip().split("\n")
            uncommitted_count = len([l for l in lines if l])
            
            res_log = subprocess.run(
                ["git", "log", "-1", "--pretty=%s"],
                capture_output=True, text=True, timeout=0.5
            )
            last_commit = res_log.stdout.strip() if res_log.returncode == 0 else "unknown"
            
            return {
                "git_available": True,
                "uncommitted_files_count": uncommitted_count,
                "last_commit_message": last_commit
            }
        except Exception:
            return {"git_available": False, "uncommitted_files_count": 0, "last_commit_message": "unknown"}

    def get_test_context(self) -> Dict[str, Any]:
        """Inspects .pytest_cache folder to extract recent testing statistics."""
        try:
            import json
            last_failed_path = os.path.join(".pytest_cache", "v", "cache", "lastfailed")
            if os.path.exists(last_failed_path):
                mtime = os.path.getmtime(last_failed_path)
                is_fresh = (time.time() - mtime) < 60.0
                
                with open(last_failed_path, "r") as f:
                    failed_tests = json.load(f)
                    
                if failed_tests:
                    return {
                        "recent_test_run_outcome": "failed",
                        "failed_tests_count": len(failed_tests),
                        "is_fresh": is_fresh
                    }
                    
            nodeids_path = os.path.join(".pytest_cache", "v", "cache", "nodeids")
            if os.path.exists(nodeids_path):
                mtime = os.path.getmtime(nodeids_path)
                is_fresh = (time.time() - mtime) < 60.0
                return {
                    "recent_test_run_outcome": "passed",
                    "failed_tests_count": 0,
                    "is_fresh": is_fresh
                }
        except Exception:
            pass
        return {"recent_test_run_outcome": "unknown", "failed_tests_count": 0, "is_fresh": False}

    def assemble_context(self, pet_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Gathers system environment telemetry and active pet physical variables.
        Returns a dictionary structure to inject into prompts.
        """
        now = datetime.now()
        session_duration = time.time() - self.start_time
        
        git_ctx = self.get_git_context()
        test_ctx = self.get_test_context()
        
        context = {
            "current_time": now.strftime("%I:%M %p"),
            "current_date": now.strftime("%A, %B %d, %Y"),
            "session_duration_min": int(session_duration / 60),
            "active_window": self.get_active_window_title(),
            "battery_percent": self.get_battery_level(),
            "pet_x": int(pet_state.get("x", 0)),
            "pet_y": int(pet_state.get("y", 0)),
            "pet_active_state": pet_state.get("state", "idle"),
            # Git Context
            "git_available": git_ctx.get("git_available", False),
            "git_uncommitted_count": git_ctx.get("uncommitted_files_count", 0),
            "git_last_commit": git_ctx.get("last_commit_message", "unknown"),
            # Test Context
            "test_outcome": test_ctx.get("recent_test_run_outcome", "unknown"),
            "test_failed_count": test_ctx.get("failed_tests_count", 0),
            "test_is_fresh": test_ctx.get("is_fresh", False)
        }
        
        logger.debug(f"Context compiled successfully: {context}")
        return context
