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


# Dispatch table: action name -> handler. Extended in later phases.
HANDLERS = {
    "open_app": lambda p: open_app(p.get("app", "")),
    "open_url": lambda p: open_url(p.get("url", "")),
    "web_search": lambda p: web_search(p.get("query", ""), p.get("engine", "google")),
}


def execute(action: Action) -> ActionResult:
    handler = HANDLERS.get(action.name)
    if handler is None:
        return ActionResult(False, f"I don't know how to '{action.name}' yet.")
    return handler(action.params)
