"""Tests for the desktop agent (Phase 1: safe launcher actions).

Launchers (subprocess / webbrowser) are monkeypatched so nothing real opens.
Focus: conservative command parsing (must not hijack chat), the app allowlist,
URL-scheme safety, the opt-in gate, and the confirm/kill-switch flow.
"""
import pytest
from src.config import Config
from src.agent import actions
from src.agent.actions import Action, RISK_RISKY, RISK_SAFE
from src.agent.agent import DesktopAgent


@pytest.fixture
def agent(monkeypatch):
    monkeypatch.setattr(Config, "AGENT_ENABLED", True)
    monkeypatch.setattr(Config, "AGENT_CONFIRM_RISKY", True)
    monkeypatch.setattr(Config, "AGENT_EXTRA_APPS", "")
    return DesktopAgent()


# --- parsing: only clear commands become actions -----------------------------

@pytest.mark.parametrize("text,name,params", [
    ("open chrome", "open_app", {"app": "chrome"}),
    ("launch notepad", "open_app", {"app": "notepad"}),
    ("open github.com", "open_url", {"url": "github.com"}),
    ("open youtube", "open_url", {"url": "youtube.com"}),          # site shortcut
    ("search for lofi beats", "web_search", {"query": "lofi beats", "engine": "google"}),
    ("google python asyncio", "web_search", {"query": "python asyncio", "engine": "google"}),
    ("search youtube for modi speech", "web_search", {"query": "modi speech", "engine": "youtube"}),
    ("play lofi on youtube", "web_search", {"query": "lofi", "engine": "youtube"}),
])
def test_parse_recognises_commands(agent, text, name, params):
    action = agent.parse(text)
    assert action is not None, f"expected a command for {text!r}"
    assert action.name == name
    for k, v in params.items():
        assert action.params[k] == v


@pytest.mark.parametrize("text", [
    "how are you today",
    "tell me a joke about python",
    "open up to me about your feelings",   # 'open' but not an app/url -> chat
    "start over, i changed my mind",        # 'start' but not an app -> chat
    "i was searching my soul",              # 'searching' mid-sentence, not a command
    "",
])
def test_parse_ignores_chat(agent, text):
    assert agent.parse(text) is None, f"{text!r} should fall through to chat"


def test_wake_prefix_stripped(agent):
    assert agent.parse("Hey Ribbit, open chrome").name == "open_app"


# --- safety: allowlist + URL scheme ------------------------------------------

def test_open_app_rejects_non_allowlisted(monkeypatch):
    called = []
    monkeypatch.setattr(actions.subprocess, "Popen", lambda *a, **k: called.append(a))
    res = actions.open_app("some_random_exe")
    assert res.ok is False
    assert called == []  # never spawned


def test_open_app_launches_allowlisted(monkeypatch):
    called = []
    monkeypatch.setattr(actions.subprocess, "Popen", lambda *a, **k: called.append(a[0]))
    res = actions.open_app("chrome")
    assert res.ok is True
    assert called and "chrome" in called[0]


def test_extra_apps_merged(monkeypatch):
    monkeypatch.setattr(Config, "AGENT_EXTRA_APPS", "slack=slack, steam=steam")
    assert actions.app_allowlist().get("slack") == "slack"
    assert actions.app_allowlist().get("steam") == "steam"


@pytest.mark.parametrize("url", ["file:///c:/secret.txt", "javascript:alert(1)", "ftp://x/y"])
def test_open_url_rejects_dangerous_schemes(monkeypatch, url):
    opened = []
    monkeypatch.setattr(actions.webbrowser, "open", lambda u: opened.append(u))
    res = actions.open_url(url)
    assert res.ok is False
    assert opened == []


def test_open_url_bare_domain_gets_https(monkeypatch):
    opened = []
    monkeypatch.setattr(actions.webbrowser, "open", lambda u: opened.append(u))
    res = actions.open_url("github.com")
    assert res.ok is True
    assert opened == ["https://github.com"]


# --- opt-in gate + confirmation / kill switch --------------------------------

def test_disabled_by_default_returns_none(monkeypatch):
    monkeypatch.setattr(Config, "AGENT_ENABLED", False)
    assert DesktopAgent().try_handle("open chrome") is None


def test_end_to_end_safe_command_runs(agent, monkeypatch):
    called = []
    monkeypatch.setattr(actions.subprocess, "Popen", lambda *a, **k: called.append(a[0]))
    reply = agent.try_handle("open chrome")
    assert reply == "Opening chrome."
    assert called  # actually launched


def test_risky_action_asks_then_confirms(agent, monkeypatch):
    """A risky action must not run until confirmed; 'yes' runs it, and a fresh
    'no' on another would cancel. Exercises the confirmation/kill-switch path."""
    ran = []
    monkeypatch.setattr(agent, "parse",
                        lambda t: Action("open_app", {"app": "chrome"}, RISK_RISKY, "open chrome"))
    monkeypatch.setattr(agent, "_run", lambda a: ran.append(a.name) or "done")

    ask = agent.try_handle("open chrome")
    assert "confirm" in ask.lower() and ran == []      # deferred
    assert agent.try_handle("yes") == "done" and ran == ["open_app"]


def test_kill_switch_cancels_pending(agent, monkeypatch):
    ran = []
    monkeypatch.setattr(agent, "parse",
                        lambda t: Action("open_app", {"app": "chrome"}, RISK_RISKY, "open chrome"))
    monkeypatch.setattr(agent, "_run", lambda a: ran.append(a.name))
    agent.try_handle("open chrome")            # pending
    assert agent.try_handle("stop") == "Okay, cancelled."
    assert ran == []                            # never executed


# --- Phase 2: keyboard / mouse parsing + risk classification -----------------

@pytest.mark.parametrize("text,name,risk,check", [
    ("copy", "press_hotkey", RISK_SAFE, lambda a: a.params["keys"] == ["ctrl", "c"]),
    ("paste", "press_hotkey", RISK_RISKY, lambda a: a.params["keys"] == ["ctrl", "v"]),
    ("switch window", "press_hotkey", RISK_SAFE, lambda a: a.params["keys"] == ["alt", "tab"]),
    ("close window", "press_hotkey", RISK_RISKY, lambda a: a.params["keys"] == ["alt", "f4"]),
    ("volume up", "media_key", RISK_SAFE, lambda a: a.params["key"] == "volumeup"),
    ("mute", "media_key", RISK_SAFE, lambda a: a.params["key"] == "volumemute"),
    ("scroll down", "scroll", RISK_SAFE, lambda a: a.params["amount"] < 0),
    ("scroll up 300", "scroll", RISK_SAFE, lambda a: a.params["amount"] == 300),
    ("click", "mouse_click", RISK_RISKY, lambda a: a.params.get("button") == "left"),
    ("double click", "mouse_click", RISK_RISKY, lambda a: a.params.get("double") is True),
    ("press control shift p", "press_hotkey", RISK_RISKY, lambda a: a.params["keys"] == ["ctrl", "shift", "p"]),
])
def test_phase2_parse_and_risk(agent, text, name, risk, check):
    action = agent.parse(text)
    assert action is not None and action.name == name
    assert action.risk == risk
    assert check(action)


def test_type_preserves_case_and_is_risky(agent):
    action = agent.parse("Type Hello World")
    assert action.name == "type_text"
    assert action.params["text"] == "Hello World"   # not lowercased
    assert action.risk == RISK_RISKY


@pytest.mark.parametrize("text", ["copy that down", "i need to paste my thoughts", "click of a button"])
def test_phase2_exact_match_does_not_hijack_chat(agent, text):
    assert agent.parse(text) is None


def test_risky_keyboard_command_confirms_before_acting(agent, monkeypatch):
    """A risky keyboard action (paste) must ask first, then run on 'yes' — with a
    fake backend so nothing real is typed."""
    calls = []

    class FakePG:
        FAILSAFE = True
        PAUSE = 0.0
        def hotkey(self, *keys): calls.append(("hotkey", keys))
    monkeypatch.setattr(actions, "_pg", FakePG())
    monkeypatch.setattr(actions, "_pg_tried", True)

    ask = agent.try_handle("paste")
    assert "confirm" in ask.lower() and calls == []     # deferred, nothing pressed
    agent.try_handle("yes")
    assert calls == [("hotkey", ("ctrl", "v"))]


def test_safe_media_command_runs_immediately(agent, monkeypatch):
    pressed = []

    class FakePG:
        FAILSAFE = True
        PAUSE = 0.0
        def press(self, k): pressed.append(k)
    monkeypatch.setattr(actions, "_pg", FakePG())
    monkeypatch.setattr(actions, "_pg_tried", True)

    reply = agent.try_handle("volume up")
    assert pressed == ["volumeup"]     # ran, no confirmation
    assert reply == "Done."


def test_keyboard_action_without_backend_degrades(agent, monkeypatch):
    """No pyautogui installed -> a clear message, never a crash."""
    monkeypatch.setattr(actions, "_pg", None)
    monkeypatch.setattr(actions, "_pg_tried", True)
    monkeypatch.setattr(Config, "AGENT_CONFIRM_RISKY", False)  # let it try to run
    reply = agent.try_handle("copy")
    assert "isn't installed" in reply
