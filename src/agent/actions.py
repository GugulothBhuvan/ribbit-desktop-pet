"""Desktop actions the agent can perform, and their safety classification.

Phase 1 ships only SAFE, deterministic actions: launch an allowlisted app, open
an http(s) URL, run a web search. Keyboard/mouse/vision actions arrive in later
phases behind the confirm-risky gate.

Handlers return an ActionResult(ok, message); the message is what the pet says.
subprocess / webbrowser are called at module scope so tests can monkeypatch them
without launching anything real.
"""
import subprocess
import webbrowser
from dataclasses import dataclass, field
from typing import Dict, Any
from urllib.parse import quote_plus, urlparse

from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("AgentActions")

# Risk levels. SAFE runs immediately; RISKY needs confirmation (Config.AGENT_CONFIRM_RISKY).
RISK_SAFE = "safe"
RISK_RISKY = "risky"


@dataclass
class Action:
    name: str
    params: Dict[str, Any] = field(default_factory=dict)
    risk: str = RISK_SAFE
    summary: str = ""          # human phrasing used for confirmation prompts


@dataclass
class ActionResult:
    ok: bool
    message: str


# Friendly names -> the token `start` resolves (via App Paths) or a system command.
# Only apps in this map (plus AGENT_EXTRA_APPS) can ever be launched.
_DEFAULT_APPS: Dict[str, str] = {
    "notepad": "notepad",
    "calculator": "calc", "calc": "calc",
    "paint": "mspaint", "mspaint": "mspaint",
    "explorer": "explorer", "file explorer": "explorer", "files": "explorer",
    "chrome": "chrome", "google chrome": "chrome",
    "edge": "msedge", "microsoft edge": "msedge",
    "firefox": "firefox",
    "spotify": "spotify",
    "vscode": "code", "vs code": "code", "code": "code",
    "word": "winword", "excel": "excel",
    "settings": "ms-settings:",
    "terminal": "wt", "cmd": "cmd", "command prompt": "cmd", "powershell": "powershell",
    "task manager": "taskmgr", "taskmgr": "taskmgr",
}


def app_allowlist() -> Dict[str, str]:
    """Built-in apps merged with AGENT_EXTRA_APPS ('name=command,...')."""
    apps = dict(_DEFAULT_APPS)
    for pair in Config.AGENT_EXTRA_APPS.split(","):
        pair = pair.strip()
        if "=" in pair:
            name, cmd = pair.split("=", 1)
            name, cmd = name.strip().lower(), cmd.strip()
            if name and cmd:
                apps[name] = cmd
    return apps


def open_app(app: str) -> ActionResult:
    """Launches an allowlisted app. Names outside the allowlist are refused —
    an LLM/mishear can never spawn an arbitrary executable."""
    key = (app or "").strip().lower()
    token = app_allowlist().get(key)
    if not token:
        return ActionResult(False, f"I can't open '{app}' — it's not on my safe app list.")
    try:
        # `start "" <token>` resolves browsers/known apps via the shell without
        # running a free-form command string.
        subprocess.Popen(["cmd", "/c", "start", "", token], shell=False)
        logger.info(f"AGENT open_app: {key} -> {token}")
        return ActionResult(True, f"Opening {app}.")
    except Exception as e:
        logger.error(f"open_app failed for {key}: {e}")
        return ActionResult(False, f"I couldn't open {app}.")


def open_url(url: str) -> ActionResult:
    """Opens an http/https URL in the default browser. Other schemes (file:,
    javascript:, etc.) are refused."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme:
        # An explicit scheme must be http/https — reject file:, javascript:, ftp:
        # etc. (Do NOT prepend https to these; that would smuggle them through.)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ActionResult(False, "I can only open normal web links.")
    else:
        # Bare domain like "github.com" -> assume https.
        url = "https://" + url
        parsed = urlparse(url)
        if not parsed.netloc:
            return ActionResult(False, "I can only open normal web links.")
    try:
        webbrowser.open(url)
        logger.info(f"AGENT open_url: {url}")
        return ActionResult(True, f"Opening {parsed.netloc}.")
    except Exception as e:
        logger.error(f"open_url failed for {url}: {e}")
        return ActionResult(False, "I couldn't open that link.")


def web_search(query: str, engine: str = "google") -> ActionResult:
    """Runs a web search. 'youtube' routes to YouTube, otherwise Google."""
    query = (query or "").strip()
    if not query:
        return ActionResult(False, "Search for what?")
    if engine == "youtube":
        url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
        where = "YouTube"
    else:
        url = "https://www.google.com/search?q=" + quote_plus(query)
        where = "Google"
    try:
        webbrowser.open(url)
        logger.info(f"AGENT web_search[{engine}]: {query}")
        return ActionResult(True, f"Searching {where} for {query}.")
    except Exception as e:
        logger.error(f"web_search failed for {query}: {e}")
        return ActionResult(False, "I couldn't run that search.")


# --- Phase 2: keyboard / mouse (needs the optional pyautogui backend) --------

_pg = None
_pg_tried = False


def _backend():
    """Lazily imports pyautogui once; returns None (and logs) if unavailable so
    keyboard/mouse actions degrade gracefully instead of crashing."""
    global _pg, _pg_tried
    if not _pg_tried:
        _pg_tried = True
        try:
            import pyautogui
            pyautogui.FAILSAFE = True    # slam mouse to a corner to abort
            pyautogui.PAUSE = 0.03
            _pg = pyautogui
        except Exception as e:
            logger.warning(f"pyautogui unavailable ({e}); keyboard/mouse actions "
                           "disabled. Install with: pip install -e .[agent]")
    return _pg


def press_hotkey(keys) -> ActionResult:
    pg = _backend()
    if pg is None:
        return ActionResult(False, "Keyboard control isn't installed.")
    if not keys:
        return ActionResult(False, "No keys to press.")
    try:
        pg.hotkey(*keys)
        logger.info(f"AGENT press_hotkey: {'+'.join(keys)}")
        return ActionResult(True, f"Done ({'+'.join(keys)}).")
    except Exception as e:
        logger.error(f"press_hotkey failed {keys}: {e}")
        return ActionResult(False, "That key combo didn't work.")


def type_text(text: str) -> ActionResult:
    pg = _backend()
    if pg is None:
        return ActionResult(False, "Keyboard control isn't installed.")
    text = text or ""
    try:
        pg.write(text, interval=0.01)
        logger.info(f"AGENT type_text: {len(text)} chars")
        return ActionResult(True, "Typed it.")
    except Exception as e:
        logger.error(f"type_text failed: {e}")
        return ActionResult(False, "I couldn't type that.")


def scroll(amount: int) -> ActionResult:
    pg = _backend()
    if pg is None:
        return ActionResult(False, "Mouse control isn't installed.")
    try:
        pg.scroll(int(amount))
        logger.info(f"AGENT scroll: {amount}")
        return ActionResult(True, f"Scrolled {'up' if amount > 0 else 'down'}.")
    except Exception as e:
        logger.error(f"scroll failed: {e}")
        return ActionResult(False, "I couldn't scroll.")


def mouse_click(button: str = "left", double: bool = False) -> ActionResult:
    pg = _backend()
    if pg is None:
        return ActionResult(False, "Mouse control isn't installed.")
    try:
        if double:
            pg.doubleClick()
            what = "Double-clicked."
        elif button == "right":
            pg.rightClick()
            what = "Right-clicked."
        else:
            pg.click()
            what = "Clicked."
        logger.info(f"AGENT mouse_click: button={button} double={double}")
        return ActionResult(True, what)
    except Exception as e:
        logger.error(f"mouse_click failed: {e}")
        return ActionResult(False, "I couldn't click.")


def click_at(x: int, y: int, double: bool = False) -> ActionResult:
    """Clicks an absolute screen coordinate (used by vision-click)."""
    pg = _backend()
    if pg is None:
        return ActionResult(False, "Mouse control isn't installed.")
    try:
        if double:
            pg.doubleClick(x, y)
        else:
            pg.click(x, y)
        logger.info(f"AGENT click_at: ({x},{y}) double={double}")
        return ActionResult(True, "Clicked.")
    except Exception as e:
        logger.error(f"click_at failed ({x},{y}): {e}")
        return ActionResult(False, "I couldn't click there.")


def media_key(key: str) -> ActionResult:
    pg = _backend()
    if pg is None:
        return ActionResult(False, "Media control isn't installed.")
    try:
        pg.press(key)
        logger.info(f"AGENT media_key: {key}")
        return ActionResult(True, "Done.")
    except Exception as e:
        logger.error(f"media_key failed {key}: {e}")
        return ActionResult(False, "That didn't work.")


# Dispatch table: action name -> handler. Extended in later phases.
HANDLERS = {
    "open_app": lambda p: open_app(p.get("app", "")),
    "open_url": lambda p: open_url(p.get("url", "")),
    "web_search": lambda p: web_search(p.get("query", ""), p.get("engine", "google")),
    "press_hotkey": lambda p: press_hotkey(p.get("keys", [])),
    "type_text": lambda p: type_text(p.get("text", "")),
    "scroll": lambda p: scroll(p.get("amount", -500)),
    "mouse_click": lambda p: mouse_click(p.get("button", "left"), p.get("double", False)),
    "media_key": lambda p: media_key(p.get("key", "")),
}


def execute(action: Action) -> ActionResult:
    handler = HANDLERS.get(action.name)
    if handler is None:
        return ActionResult(False, f"I don't know how to '{action.name}' yet.")
    return handler(action.params)
