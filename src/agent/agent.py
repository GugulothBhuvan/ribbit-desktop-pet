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
import json
from typing import Optional, List

from src.config import Config
from src.agent import actions
from src.agent.actions import Action, RISK_SAFE, RISK_RISKY
from src.utils.logger import get_logger

logger = get_logger("DesktopAgent")

# Utterances that MIGHT be a command (checked only when the rules didn't already
# match). Kept to imperative starts so chat like "tell me about opening a shop"
# — which merely contains "open" — is not sent to the LLM parser.
COMMAND_VERBS = (
    "open", "launch", "start", "run", "close", "search", "google", "find",
    "type", "write", "click", "scroll", "press", "switch", "play", "pause",
    "mute", "unmute", "volume", "go to", "goto", "pull up", "fire up", "bring up",
    "copy", "paste", "cut", "select", "save", "undo", "redo", "maximize",
    "minimize", "screenshot", "new tab", "new window", "refresh",
)

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


def _extract_json(text: str):
    """Pulls a JSON object out of an LLM reply that may wrap it in ``` fences or
    stray prose. Returns the parsed object, or None."""
    if not text:
        return None
    # Prefer a fenced block, else the outermost {...}.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start:end + 1] if 0 <= start < end else None
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return None


# Hotkey combos that are safe to run without confirmation (from NAMED_HOTKEYS).
SAFE_HOTKEY_COMBOS = {tuple(keys) for keys, risk in NAMED_HOTKEYS.values() if risk == RISK_SAFE}


class DesktopAgent:
    def __init__(self):
        self._pending: Optional[List[Action]] = None   # a plan awaiting confirmation
        # Injected by the orchestrator: schedules the async screenshot->vision->
        # click flow. Left None means vision-click is unavailable.
        self._vision_click_fn = None

    def set_vision_click_fn(self, fn):
        self._vision_click_fn = fn

    def try_handle(self, text: str) -> Optional[str]:
        """Returns the pet's spoken response if this line was a command (executed
        or awaiting confirmation), or None to let it fall through to chat/LLM."""
        if not Config.AGENT_ENABLED:
            return None
        text = (text or "").strip()
        if not text:
            return None

        # A pending plan: resolve confirmation / kill switch first.
        if self._pending is not None:
            return self._resolve_pending(text)

        action = self.parse(text)
        if action is None:
            return None  # rules didn't match -> caller may try the LLM parser
        return self.execute_or_confirm([action])

    def might_be_command(self, text: str) -> bool:
        """Cheap pre-filter: worth asking the LLM to parse this as a command?
        Only true for imperative starts, so plain chat never triggers an LLM
        round-trip."""
        low = _WAKE_PREFIX.sub("", text.strip()).lower()
        return any(low == v or low.startswith(v + " ") for v in COMMAND_VERBS)

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

        # "click <target>" / "double click <target>" -> find it by vision, click.
        m = re.match(r"^(?:double[- ]?click|double tap)\s+(?:on\s+)?(.+)$", low)
        if m:
            target = m.group(1).strip()
            return Action("vision_click", {"target": target, "double": True},
                          RISK_RISKY, f"double-click {target}")
        m = re.match(r"^(?:click|tap)\s+(?:on\s+)?(.+)$", low)
        if m:
            target = m.group(1).strip()
            return Action("vision_click", {"target": target}, RISK_RISKY, f"click {target}")

        m = re.match(r"^press\s+(.+)$", low)
        if m:
            keys = _words_to_keys(m.group(1))
            if keys:
                return Action("press_hotkey", {"keys": keys}, RISK_RISKY,
                              f"press {'+'.join(keys)}")

        return None

    # --- plan execution + confirmation ------------------------------------

    def execute_or_confirm(self, plan: List[Action]) -> str:
        """Runs a plan now, or asks first if any step is risky."""
        if not plan:
            return "I didn't catch a command."
        risky = Config.AGENT_CONFIRM_RISKY and any(a.risk == RISK_RISKY for a in plan)
        if risky:
            self._pending = plan
            return f"{self._plan_summary(plan)}? Say yes to confirm, or no to cancel."
        return self._run_plan(plan)

    def _run_plan(self, plan: List[Action]) -> str:
        """Executes steps in order, stopping at the first failure.

        vision_click is async (screenshot -> vision -> click): it's kicked off
        via the injected executor and its result is spoken later, so here it just
        schedules and reports 'looking...'."""
        messages = []
        for action in plan:
            if action.name == "vision_click":
                target = action.params.get("target", "")
                if self._vision_click_fn:
                    self._vision_click_fn(target, bool(action.params.get("double")))
                    messages.append(f"Looking for {target}…")
                else:
                    messages.append("Vision clicking isn't set up.")
                continue
            result = actions.execute(action)
            logger.info(f"AGENT executed {action.name} params={action.params} ok={result.ok}")
            messages.append(result.message)
            if not result.ok:
                break
        return " ".join(messages)

    @staticmethod
    def _plan_summary(plan: List[Action]) -> str:
        return " then ".join(a.summary or a.name for a in plan)

    def _resolve_pending(self, text: str) -> str:
        low = text.lower()
        if any(w in low for w in _NO):
            self._pending = None
            return "Okay, cancelled."
        if any(w in low for w in _YES):
            plan = self._pending
            self._pending = None
            return self._run_plan(plan) if plan else "Nothing to confirm."
        return "Say yes to confirm, or no to cancel."

    # --- LLM parsing (flexible / multi-step commands) ---------------------

    def command_prompt(self, text: str):
        """(system, user) prompts asking the LLM to turn a request into a JSON
        plan of known actions — or declare it chat."""
        apps = ", ".join(sorted(set(actions.app_allowlist().values())))
        system = (
            "You convert a user's request into desktop actions, or decide it is "
            "just conversation. Respond with ONLY a JSON object, no prose.\n"
            'If it is a computer command: {"actions": [{"name": "...", "params": {...}}, ...]}\n'
            'If it is not a command (chit-chat, a question): {"chat": true}\n\n'
            "Allowed actions and params:\n"
            "- open_app {app}          app must be one of: " + apps + "\n"
            "- open_url {url}          http/https only\n"
            "- web_search {query, engine}   engine is 'google' or 'youtube'\n"
            "- press_hotkey {keys}     keys is a list like ['ctrl','t'] or ['alt','tab']\n"
            "- type_text {text}\n"
            "- scroll {amount}         positive up, negative down\n"
            "- mouse_click {button, double}\n"
            "- media_key {key}         volumeup|volumedown|volumemute|playpause|nexttrack|prevtrack\n\n"
            "Use multiple actions for multi-step requests, in order. Never invent "
            "action names or apps outside the list."
        )
        return system, text.strip()

    def plan_from_llm(self, llm_text: str) -> Optional[List[Action]]:
        """Parses the LLM's JSON into a validated plan, or None (chat / garbage /
        no valid actions). Every action is re-validated and re-risk-classified
        here — the model's output is never trusted to be safe on its own."""
        data = _extract_json(llm_text)
        if not isinstance(data, dict) or data.get("chat") is True:
            return None
        raw = data.get("actions")
        if not isinstance(raw, list):
            return None

        plan: List[Action] = []
        for item in raw:
            action = self._validate_action(item)
            if action is not None:
                plan.append(action)
        return plan or None

    def _validate_action(self, item) -> Optional[Action]:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        params = item.get("params") or {}
        if name not in actions.HANDLERS or not isinstance(params, dict):
            logger.warning(f"Dropping unknown/invalid agent action: {item}")
            return None

        # Per-action sanity: refuse anything the safe handlers would reject anyway.
        if name == "open_app" and str(params.get("app", "")).lower() not in actions.app_allowlist():
            return None
        if name == "open_url" and not _looks_like_url(str(params.get("url", "")).lower()):
            return None
        if name == "press_hotkey" and not isinstance(params.get("keys"), list):
            return None

        return Action(name, params, self._risk_for(name, params), self._describe(name, params))

    @staticmethod
    def _risk_for(name: str, params: dict) -> str:
        if name in ("type_text", "mouse_click"):
            return RISK_RISKY
        if name == "press_hotkey":
            return RISK_SAFE if tuple(params.get("keys", [])) in SAFE_HOTKEY_COMBOS else RISK_RISKY
        return RISK_SAFE   # open_app / open_url / web_search / scroll / media_key

    @staticmethod
    def _describe(name: str, params: dict) -> str:
        if name == "open_app":
            return f"open {params.get('app')}"
        if name == "open_url":
            return f"open {params.get('url')}"
        if name == "web_search":
            return f"search {params.get('engine', 'google')} for {params.get('query')}"
        if name == "type_text":
            return f"type \"{str(params.get('text',''))[:40]}\""
        if name == "press_hotkey":
            return "press " + "+".join(params.get("keys", []))
        return name.replace("_", " ")
