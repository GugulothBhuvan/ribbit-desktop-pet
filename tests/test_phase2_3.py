"""Regression tests for the Phase 2 + Phase 3 fixes (see MVP_PLAN.md)."""
from src.ai.orchestrator import sanitize_chunk, clamp_stream_text, extract_memory_facts
from src.constants import MAX_CHARACTERS, PetState
from src.utils.win32 import get_battery_status


# --- 3.4: stream-layer response validation -------------------------------

def test_sanitize_chunk_strips_markdown_and_newlines():
    assert sanitize_chunk("**bold**\nand `code`") == "bold and code"
    assert sanitize_chunk("# heading\r\ntext") == " heading  text"

def test_clamp_stream_text_under_limit_passes_through():
    text, final = clamp_stream_text(10, "hello")
    assert text == "hello"
    assert final is False

def test_clamp_stream_text_cuts_at_limit_with_ellipsis():
    text, final = clamp_stream_text(MAX_CHARACTERS - 3, "hello world")
    assert final is True
    assert text.endswith("…")
    assert len(text) <= 4  # 3 chars + ellipsis

def test_clamp_stream_text_stops_when_budget_spent():
    text, final = clamp_stream_text(MAX_CHARACTERS, "more")
    assert text == ""
    assert final is True


# --- 2.8: word-boundary memory extraction ---------------------------------

def test_extract_name():
    facts = extract_memory_facts("Hey, my name is Bhuvan by the way!")
    assert facts["user_name"] == "Bhuvan"  # lowercase "by" is not part of a name

def test_extract_full_name():
    facts = extract_memory_facts("My name is Bhuvan Raj and I like Python")
    assert facts["user_name"] == "Bhuvan Raj"

def test_extract_coding_pref():
    facts = extract_memory_facts("I prefer tabs over spaces.")
    assert facts["coding_pref"] == "tabs over spaces"

def test_extract_does_not_misfire_on_substrings():
    # The old substring split captured garbage from these (audit m-14)
    assert extract_memory_facts("What do you prefer honestly?") == {}
    assert extract_memory_facts("They prefer the dark theme") == {}
    assert extract_memory_facts("nothing to remember here") == {}


# --- 2.2: battery signedness -----------------------------------------------

def test_battery_status_types():
    percent, on_ac = get_battery_status()
    # None means unknown/no battery; a number must be a sane unsigned percent
    if percent is not None:
        assert 0 <= percent <= 100, "signed-byte regression: percent out of range"
    assert on_ac in (True, False, None)


# --- 2.6: collision floor off-by-one ----------------------------------------

def test_collision_floor_uses_full_height(qapp):
    from src.physics.collision import CollisionResolver
    from PyQt6.QtGui import QGuiApplication

    geom = QGuiApplication.primaryScreen().availableGeometry()
    w = h = 100
    # Start well below the floor: must clamp exactly to top+height-h
    x, y, vx, vy, details = CollisionResolver.resolve_boundaries(
        float(geom.left() + 10), float(geom.top() + geom.height() + 500), w, h, 0.0, 5.0)
    assert y == geom.top() + geom.height() - h
    assert details["collided_floor"] is True
    assert vy == 0.0


# --- state priority: physics states not preempted by AI states --------------

def test_physical_states_reject_ai_preemption(qapp, event_bus):
    from src.animation.sprite_loader import SpriteLoader
    from src.animation.state_machine import StateMachine

    sm = StateMachine(event_bus, SpriteLoader())
    assert sm.set_state(PetState.FALL) is True
    # An LLM request mid-fall must NOT flip the pet to think (fall/think flap)
    assert sm.set_state(PetState.THINK) is False
    assert sm.current_state == PetState.FALL
    # Physics-driven exit works
    assert sm.set_state(PetState.LANDING) is True
    assert sm.set_state(PetState.IDLE) is True
    # And from idle, AI states are fine
    assert sm.set_state(PetState.THINK) is True
