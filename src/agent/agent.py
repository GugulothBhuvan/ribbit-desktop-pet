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

# Named hotkeys: phrase -> (keys, risk). SAFE run immediately; RISKY confirm.
NAMED_HOTKEYS = {
    "copy": (["ctrl", "c"], RISK_SAFE),
    "cut": (["ctrl", "x"], RISK_RISKY),
    "paste": (["ctrl", "v"], RISK_RISKY),
    "undo": (["ctrl", "z"], RISK_SAFE),
    "redo": (["ctrl", "y"], RISK_SAFE),
    "select all": (["ctrl", "a"], RISK_SAFE),
    "save": (["ctrl", "s"], RISK_SAFE),
    "find": (["ctrl", "f"], RISK_SAFE),
    "address bar": (["ctrl", "l"], RISK_SAFE),
    "new tab": (["ctrl", "t"], RISK_SAFE),
    "close tab": (["ctrl", "w"], RISK_RISKY),
    "reopen tab": (["ctrl", "shift", "t"], RISK_SAFE),
    "switch tab": (["ctrl", "tab"], RISK_SAFE),
    "new window": (["ctrl", "n"], RISK_SAFE),
    "switch window": (["alt", "tab"], RISK_SAFE),
    "close window": (["alt", "f4"], RISK_RISKY),
    "refresh": (["f5"], RISK_SAFE),
    "screenshot": (["win", "shift", "s"], RISK_SAFE),
    "show desktop": (["win", "d"], RISK_SAFE),
    "minimize": (["win", "down"], RISK_SAFE),
    "lock screen": (["win", "l"], RISK_RISKY),
    "enter": (["enter"], RISK_SAFE),
    "escape": (["esc"], RISK_SAFE),
}

MEDIA_KEYS = {
    "volume up": "volumeup", "volume down": "volumedown", "mute": "volumemute",
    "unmute": "volumemute", "play": "playpause", "pause": "playpause",
    "next track": "nexttrack", "previous track": "prevtrack",
    "next song": "nexttrack", "previous song": "prevtrack",
}

# Spoken key names -> pyautogui key names.
_KEY_WORDS = {
    "control": "ctrl", "ctrl": "ctrl", "command": "ctrl", "cmd": "ctrl",
    "shift": "shift", "alt": "alt", "option": "alt",
    "windows": "win", "win": "win", "super": "win",
    "enter": "enter", "return": "enter", "escape": "esc", "esc": "esc",
    "tab": "tab", "space": "space", "delete": "delete", "backspace": "backspace",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "pageup": "pageup", "pagedown": "pagedown",
}


def _words_to_keys(spec: str):
    """Turns 'control shift p' / 'ctrl+c' into ['ctrl','shift','p']. Single
    letters/digits pass through; unknown words are dropped."""
    keys = []
    for w in re.split(r"[\s+]+", spec.strip().lower()):
        if not w:
            continue
        if w in _KEY_WORDS:
            keys.append(_KEY_WORDS[w])
        elif len(w) == 1 and w.isalnum():
            keys.append(w)
    return keys


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

        # type <text> — keep the ORIGINAL case; risky (goes to the focused app).
        m = re.match(r"^type\s+(.+)$", t, re.I)
        if m:
            text = m.group(1).strip()
            return Action("type_text", {"text": text}, RISK_RISKY, f"type \"{text[:40]}\"")

        # Exact-match commands only, so chat like "copy that" isn't hijacked.
        if low in NAMED_HOTKEYS:
            keys, risk = NAMED_HOTKEYS[low]
            return Action("press_hotkey", {"keys": keys}, risk, low)

        if low in MEDIA_KEYS:
            return Action("media_key", {"key": MEDIA_KEYS[low]}, RISK_SAFE, low)

        m = re.match(r"^scroll(?:\s+(up|down))?(?:\s+(\d+))?$", low)
        if m:
            direction = m.group(1) or "down"
            amount = int(m.group(2) or 500)
            amount = amount if direction == "up" else -amount
            return Action("scroll", {"amount": amount}, RISK_SAFE, f"scroll {direction}")

        if low in ("click", "left click"):
            return Action("mouse_click", {"button": "left"}, RISK_RISKY, "click")
        if low in ("double click", "double-click"):
            return Action("mouse_click", {"double": True}, RISK_RISKY, "double-click")
        if low in ("right click", "right-click"):
            return Action("mouse_click", {"button": "right"}, RISK_RISKY, "right-click")

        m = re.match(r"^press\s+(.+)$", low)
        if m:
            keys = _words_to_keys(m.group(1))
            if keys:
                return Action("press_hotkey", {"keys": keys}, RISK_RISKY,
                              f"press {'+'.join(keys)}")

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
            action = self._pending
            self._pending = None
            return self._run(action) if action else "Nothing to confirm."
        return "Say yes to confirm, or no to cancel."
