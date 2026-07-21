"""Tests for the ReAct loop engine (control flow) and step parsing.

Everything the loop touches — capture, decide, act — is injected, so the control
flow (done, step cap, give-up, abort, history) is verified without any live
vision or real clicks.
"""
import asyncio
from src.agent import react
from src.agent.react import ReactDecision


def _run(coro):
    return asyncio.run(coro)


# --- per-step parsing --------------------------------------------------------

def test_parse_step_variants():
    assert react.parse_step('{"action":{"name":"click","x":5,"y":6}}').kind == "act"
    d = react.parse_step('{"done": true, "message": "opened it"}')
    assert d.kind == "done" and d.message == "opened it"
    assert react.parse_step('{"give_up": true, "reason": "stuck"}').kind == "give_up"
    # Unreadable output must NEVER become a blind action.
    assert react.parse_step("uhh not json").kind == "give_up"
    assert react.parse_step('{"nonsense": 1}').kind == "give_up"


# --- loop control ------------------------------------------------------------

def _fixed(decisions):
    """decide() that returns a scripted sequence of decisions."""
    state = {"i": 0}

    async def decide(goal, history, image, geom, step):
        d = decisions[state["i"]]
        state["i"] += 1
        return d
    return decide


async def _capture_ok():
    return ("img", (0, 0, 1920, 1080))


async def _act_ok(action, image, geom):
    return "did it"


def test_stops_on_done():
    decide = _fixed([
        ReactDecision("act", {"name": "click", "x": 1, "y": 1}),
        ReactDecision("done", message="all set"),
    ])
    acts = []

    async def act(a, i, g):
        acts.append(a)
        return "ok"
    res = _run(react.run_react("goal", capture=_capture_ok, decide=decide, act=act, max_steps=6))
    assert res == "all set"
    assert len(acts) == 1                 # only the pre-done step acted


def test_stops_at_step_cap():
    decide = _fixed([ReactDecision("act", {"name": "scroll", "amount": -100})] * 10)
    acts = []

    async def act(a, i, g):
        acts.append(a)
        return "ok"
    res = _run(react.run_react("goal", capture=_capture_ok, decide=decide, act=act, max_steps=3))
    assert "3 steps" in res
    assert len(acts) == 3                  # never exceeds the cap


def test_give_up_stops_without_acting():
    decide = _fixed([ReactDecision("give_up", message="too risky")])
    acts = []

    async def act(a, i, g):
        acts.append(a)
        return "ok"
    res = _run(react.run_react("goal", capture=_capture_ok, decide=decide, act=act, max_steps=6))
    assert res == "too risky" and acts == []


def test_abort_before_first_capture():
    captured = {"n": 0}

    async def capture():
        captured["n"] += 1
        return await _capture_ok()
    res = _run(react.run_react("goal", capture=capture, decide=_fixed([]), act=_act_ok,
                               max_steps=6, should_abort=lambda: True))
    assert res == "Okay, stopping."
    assert captured["n"] == 0              # aborted before doing anything


def test_capture_failure_is_handled():
    async def bad_capture():
        raise RuntimeError("no screen")
    res = _run(react.run_react("goal", capture=bad_capture, decide=_fixed([]), act=_act_ok, max_steps=6))
    assert "couldn't see" in res


def test_history_is_passed_forward():
    seen = []

    async def decide(goal, history, image, geom, step):
        seen.append(len(history))
        if step >= 2:
            return ReactDecision("done", message="ok")
        return ReactDecision("act", {"name": "scroll", "amount": -50})
    _run(react.run_react("goal", capture=_capture_ok, decide=decide, act=_act_ok, max_steps=6))
    assert seen == [0, 1, 2]               # history grows each acted step
