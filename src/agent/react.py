"""ReAct loop: observe → reason → act, until done / capped / aborted.

For goals that need checking the screen between steps ("open youtube and play the
first lofi video"), a single plan isn't enough — the agent must look, act, look
again. This module is the loop CONTROL only; the observe/decide/act steps are
injected, so the flow (step cap, done/give-up, abort) is unit-tested without any
live vision or real clicks.

Safety is structural: a hard step cap, an abort check each iteration, and the
fact that decide() sees a fresh screenshot every step (so it can notice its last
action did nothing and stop).
"""
import re
import json
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Awaitable, Callable

from src.utils.logger import get_logger

logger = get_logger("ReAct")


@dataclass
class ReactDecision:
    kind: str                       # 'act' | 'done' | 'give_up'
    action: Optional[dict] = None   # {"name": ..., ...} when kind == 'act'
    message: str = ""


def parse_step(text: str) -> ReactDecision:
    """Turns the model's per-step JSON into a decision. Anything unreadable is
    treated as give-up (never as a blind action)."""
    data = _extract_json(text)
    if not isinstance(data, dict):
        return ReactDecision("give_up", message="I lost track of what I was doing.")
    if data.get("done") is True:
        return ReactDecision("done", message=str(data.get("message", "")).strip())
    if data.get("give_up") is True or data.get("giveup") is True:
        return ReactDecision("give_up", message=str(data.get("reason", "")).strip())
    action = data.get("action")
    if isinstance(action, dict) and action.get("name"):
        return ReactDecision("act", action=action)
    return ReactDecision("give_up", message="I couldn't decide a next step.")


async def run_react(
    goal: str,
    *,
    capture: Callable[[], Awaitable],
    decide: Callable[[str, List[Dict[str, Any]], Any, Any, int], Awaitable[ReactDecision]],
    act: Callable[[dict, Any, Any], Awaitable[str]],
    max_steps: int,
    should_abort: Optional[Callable[[], bool]] = None,
) -> str:
    """Drives the loop. Returns the final spoken message.

    capture() -> (image, geometry); decide(goal, history, image, geometry, step)
    -> ReactDecision; act(action, image, geometry) -> observation string.
    """
    history: List[Dict[str, Any]] = []
    for step in range(max_steps):
        if should_abort and should_abort():
            return "Okay, stopping."
        try:
            image, geometry = await capture()
        except Exception as e:
            logger.error(f"ReAct capture failed: {e}")
            return "I couldn't see the screen."

        decision = await decide(goal, history, image, geometry, step)
        if decision.kind == "done":
            return decision.message or "Done."
        if decision.kind == "give_up":
            return decision.message or "I couldn't finish that one."

        observation = await act(decision.action or {}, image, geometry)
        history.append({"action": decision.action, "observation": observation})
        logger.info(f"ReAct step {step + 1}: {decision.action} -> {observation}")

    return f"I tried {max_steps} steps but couldn't confirm it's done."


def step_prompt(goal: str, history: List[Dict[str, Any]], image_w: int, image_h: int) -> str:
    """System prompt for one reasoning step. The model sees the current screenshot
    and picks exactly one next action, or declares done / give-up."""
    hist = "\n".join(
        f"{i + 1}. {h['action']} -> {h['observation']}" for i, h in enumerate(history)
    ) or "(nothing yet)"
    return (
        "You are operating a Windows PC to accomplish a goal, one step at a time, "
        f"by looking at a screenshot ({image_w}x{image_h} px).\n"
        f"GOAL: {goal}\n"
        f"STEPS SO FAR:\n{hist}\n\n"
        "Look at the current screenshot and choose the SINGLE next action. Reply "
        "with ONLY JSON, one of:\n"
        '{"action": {"name": "click", "x": <px>, "y": <px>}}   (center of the target)\n'
        '{"action": {"name": "type", "text": "..."}}\n'
        '{"action": {"name": "scroll", "amount": <negative down / positive up>}}\n'
        '{"action": {"name": "press", "keys": ["ctrl","t"]}}\n'
        '{"done": true, "message": "<what you accomplished>"}   when the goal is visibly achieved\n'
        '{"give_up": true, "reason": "<why>"}   if stuck or it looks unsafe.\n'
        "Coordinates are in the screenshot's pixels. Prefer 'done' as soon as the "
        "goal is clearly complete. Never guess wildly."
    )


def _extract_json(text: str):
    if not text:
        return None
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
