"""The desktop agent: turns a spoken/typed line into a desktop action.

Phase 1 uses a deliberately CONSERVATIVE rule parser — it only claims an
utterance when it's clearly a command (starts with open/launch/search/… and
resolves to a known app, site, or search). Anything else returns None so the
line falls through to normal chat. Getting this wrong would hijack conversation,
so when in doubt it declines.

Risky actions (later phases) stash a pending action and ask for confirmation;
'yes' runs it, 'no'/'stop'/'cancel' clears it (the kill switch).
"""
import re
from typing import Optional

from src.config import Config
from src.agent import actions
from src.agent.actions import Action, RISK_SAFE, RISK_RISKY
from src.utils.logger import get_logger

logger = get_logger("DesktopAgent")

# "open <site>" shortcuts (bare words that aren't apps but are obviously sites).
KNOWN_SITES = {
    "youtube": "youtube.com", "google": "google.com", "gmail": "mail.google.com",
    "github": "github.com", "maps": "maps.google.com", "reddit": "reddit.com",
    "twitter": "twitter.com", "x": "x.com", "whatsapp": "web.whatsapp.com",
    "chatgpt": "chat.openai.com", "claude": "claude.ai",
}

_WAKE_PREFIX = re.compile(r"^\s*(?:hey\s+[\w']+[,.]?\s+|ok\s+[\w']+[,.]?\s+)", re.I)
_SEARCH = re.compile(r"^(?:search for|search|google|look up)\s+(.+)$", re.I)
_YT_PREFIX = re.compile(r"^(?:search youtube for|play on youtube|youtube)\s+(.+)$", re.I)
_YT_SUFFIX = re.compile(r"^(?:play|search)\s+(.+?)\s+on youtube$", re.I)
_OPEN = re.compile(r"^(?:open|go to|goto|navigate to|visit)\s+(.+)$", re.I)
_LAUNCH = re.compile(r"^(?:launch|start|run)\s+(.+)$", re.I)

_YES = ("yes", "yeah", "yep", "haan", "confirm", "do it", "go ahead", "sure", "okay", "ok")
_NO = ("no", "nope", "cancel", "stop", "don't", "dont", "nahi", "abort", "never mind")


def _looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://")) or bool(re.match(r"^[\w-]+(\.[\w-]+)+$", s))


class DesktopAgent:
    def __init__(self):
        self._pending: Optional[Action] = None

    def try_handle(self, text: str) -> Optional[str]:
        """Returns the pet's spoken response if this line was a command (executed
        or awaiting confirmation), or None to let it fall through to chat."""
        if not Config.AGENT_ENABLED:
            return None
        text = (text or "").strip()
        if not text:
            return None

        # A pending risky action: resolve confirmation / kill switch first.
        if self._pending is not None:
            return self._resolve_pending(text)

        action = self.parse(text)
        if action is None:
            return None  # not a command -> chat

        if action.risk == RISK_RISKY and Config.AGENT_CONFIRM_RISKY:
            self._pending = action
            return f"{action.summary}? Say yes to confirm, or no to cancel."
        return self._run(action)

    def parse(self, text: str) -> Optional[Action]:
        """Maps a clear command to an Action, or None. Conservative by design."""
        t = _WAKE_PREFIX.sub("", text.strip())
        low = t.rstrip(" .!?").strip()

        m = _YT_PREFIX.match(low) or _YT_SUFFIX.match(low)
        if m:
            q = m.group(1).strip()
            return Action("web_search", {"query": q, "engine": "youtube"},
                          RISK_SAFE, f"search YouTube for {q}")

        m = _SEARCH.match(low)
        if m:
            q = m.group(1).strip()
            return Action("web_search", {"query": q, "engine": "google"},
                          RISK_SAFE, f"search for {q}")

        m = _OPEN.match(low)
        if m:
            target = m.group(1).strip()
            key = target.lower()
            if key in actions.app_allowlist():
                return Action("open_app", {"app": key}, RISK_SAFE, f"open {target}")
            if key in KNOWN_SITES:
                return Action("open_url", {"url": KNOWN_SITES[key]}, RISK_SAFE, f"open {target}")
            if _looks_like_url(key):
                return Action("open_url", {"url": target}, RISK_SAFE, f"open {target}")
            return None  # "open up to me" etc. -> not a command, let chat have it

        m = _LAUNCH.match(low)
        if m:
            key = m.group(1).strip().lower()
            if key in actions.app_allowlist():
                return Action("open_app", {"app": key}, RISK_SAFE, f"launch {key}")
            return None  # "start over" etc. -> chat

        return None

    def _run(self, action: Action) -> str:
        result = actions.execute(action)
        logger.info(f"AGENT executed {action.name} params={action.params} ok={result.ok}")
        return result.message

    def _resolve_pending(self, text: str) -> str:
        low = text.lower()
        if any(w in low for w in _NO):
            self._pending = None
            return "Okay, cancelled."
        if any(w in low for w in _YES):
            action, self._pending = self._pending, None
            return self._run(action)
        return "Say yes to confirm, or no to cancel."
