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


# --- multi-monitor: pet must not be trapped on one screen -------------------

def test_walls_span_the_whole_virtual_desktop(qapp):
    """Walls come from the union of all screens, never a single monitor —
    otherwise a screen seam is a solid wall and the pet can never walk onto an
    extended monitor (reported live on a laptop + external display)."""
    from src.physics.collision import CollisionResolver
    from PyQt6.QtGui import QGuiApplication

    desktop = CollisionResolver.get_virtual_desktop_geometry()

    # The virtual desktop must contain every screen's work area.
    for screen in QGuiApplication.screens():
        assert desktop.contains(screen.availableGeometry())

    # A pet moving right must be clamped to the DESKTOP edge, not a screen edge.
    w = h = 100
    far_right = float(desktop.left() + desktop.width() + 500)
    x, _, _, _, _ = CollisionResolver.resolve_boundaries(
        far_right, float(desktop.top() + 10), w, h, 5.0, 0.0)
    assert x == desktop.left() + desktop.width() - w


def test_floor_stays_per_monitor(qapp):
    """Floor must still come from the pet's own monitor (each has its own
    taskbar), even though walls span all monitors."""
    from src.physics.collision import CollisionResolver
    from PyQt6.QtGui import QGuiApplication

    screen_geom = QGuiApplication.primaryScreen().availableGeometry()
    w = h = 100
    _, y, _, _, details = CollisionResolver.resolve_boundaries(
        float(screen_geom.left() + 10), float(screen_geom.top() + screen_geom.height() + 500),
        w, h, 0.0, 5.0)
    assert y == screen_geom.top() + screen_geom.height() - h
    assert details["screen_rect"] == screen_geom


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


# --- Phase 4: sprite fallback, cache, per-frame durations --------------------

def test_missing_animation_falls_back_to_idle(qapp):
    from src.animation.sprite_loader import SpriteLoader
    loader = SpriteLoader()
    frames = loader.get_animation_frames("definitely-not-an-animation")
    assert len(frames) > 0, "missing animation must render idle, never nothing"
    assert loader.get_animation_fps("definitely-not-an-animation") == loader.get_animation_fps("idle")

def test_previously_missing_states_now_defined(qapp):
    from src.animation.sprite_loader import SpriteLoader
    loader = SpriteLoader()
    for state in ("dragged", "sleep", "listen"):
        assert state in loader.metadata["animations"], f"'{state}' missing from metadata"
        assert len(loader.get_animation_frames(state)) > 0

def test_per_frame_duration_from_metadata(qapp):
    from src.animation.sprite_loader import SpriteLoader
    loader = SpriteLoader()
    assert loader.get_frame_duration("idle", 0) == 100      # metadata duration_ms
    assert loader.get_frame_duration("sleep", 1) == 700
    assert loader.get_frame_duration("idle", 999) == 100    # fallback: 1000/fps

def test_single_frame_animation_reports_no_change(qapp):
    from src.animation.sprite_loader import SpriteLoader
    from src.ui.renderer import SpriteRenderer
    r = SpriteRenderer(SpriteLoader())
    r.set_animation("sit", loop=True)  # 1-frame loop
    assert r.advance_frame() is False, "static frame must not request repaints"


# --- Phase 4: delta-time physics ---------------------------------------------

def test_fall_accelerates_with_dt(qapp, event_bus):
    from PyQt6.QtGui import QGuiApplication
    from src.physics.movement import MovementController

    geom = QGuiApplication.primaryScreen().availableGeometry()
    mc = MovementController(event_bus, float(geom.center().x()), float(geom.top() + 50), 100, 100)

    dt = 1.0 / 60.0
    _, y1, _ = mc.update(PetState.FALL, False, dt)
    v1 = mc.vy
    _, y2, _ = mc.update(PetState.FALL, False, dt)
    v2 = mc.vy

    assert v2 > v1 > 0, "velocity must build up over ticks (visible acceleration)"
    assert y2 > y1, "pet must be moving down"

def test_walk_speed_is_frame_rate_independent(qapp, event_bus):
    from PyQt6.QtGui import QGuiApplication
    from src.constants import WALK_SPEED
    from src.physics.movement import MovementController

    geom = QGuiApplication.primaryScreen().availableGeometry()
    floor_y = geom.top() + geom.height() - 100

    def travel(dt, steps):
        mc = MovementController(event_bus, float(geom.center().x()), float(floor_y), 100, 100)
        mc.walk_direction = 1
        mc.wander_timer = 999.0
        x0 = mc.x
        for _ in range(steps):
            mc.update(PetState.WALK, False, dt)
        return mc.x - x0

    # Same wall-clock second at 60Hz vs 30Hz must cover the same distance
    d60 = travel(1 / 60, 60)
    d30 = travel(1 / 30, 30)
    assert abs(d60 - WALK_SPEED) < 1.0
    assert abs(d60 - d30) < 1.0


# --- Voice/PTT fixes (post-live-run) -----------------------------------------

def test_sleeping_pet_wakes_into_listen(qapp, event_bus):
    """A sleeping pet must be able to enter LISTEN when PTT starts recording;
    rejecting it left the pet asleep while the mic was live (observed live)."""
    from src.animation.sprite_loader import SpriteLoader
    from src.animation.state_machine import StateMachine

    sm = StateMachine(event_bus, SpriteLoader())
    sm.set_state(PetState.SLEEP)
    assert sm.set_state(PetState.LISTEN) is True
    # But it still can't leap straight into wandering from sleep
    sm.set_state(PetState.SLEEP)
    assert sm.set_state(PetState.WALK) is False

def test_audio_recorder_paths_are_unique():
    from src.core.audio_recorder import AudioRecorder
    rec = AudioRecorder()
    try:
        paths = {rec._new_output_path() for _ in range(100)}
        assert len(paths) == 100  # no collisions even back-to-back
    finally:
        rec.cleanup()


# --- Hotkey parsing + ambient interruption (post-live-run) -------------------

def test_parse_hotkey_variants():
    from src.observer.hotkey import parse_hotkey, MOD_CONTROL, MOD_ALT
    mods, vk, label = parse_hotkey("ctrl+space")
    assert mods == MOD_CONTROL and vk == 0x20
    mods, vk, label = parse_hotkey("ctrl+alt+j")
    assert mods == (MOD_CONTROL | MOD_ALT) and vk == ord("J")
    assert parse_hotkey("shift") is None  # no non-modifier key

def test_user_query_resets_ambient_cooldown(qapp, event_bus, tmp_db):
    import time as _t
    import asyncio
    from src.ai.context_engine import ContextEngine
    from src.core.scheduler import AmbientScheduler
    from src.event_bus import EventType

    asyncio.run(tmp_db.initialize())
    sched = AmbientScheduler(event_bus, tmp_db, ContextEngine())
    sched.last_ai_invocation = 0.0  # cooldown long elapsed

    # A user query fires -> scheduler must mark AI as just-invoked
    sched.on_event(EventType.LLM_REQUEST_SENT, {})
    assert _t.time() - sched.last_ai_invocation < 1.0

    # An immediately-following stable screen must NOT trigger a vision query
    triggered = []
    event_bus.subscribe(EventType.VISION_CAPTURE_REQUESTED,
                        lambda t, d: triggered.append(d), executor="gui")
    sched.pending_low_priority_events.append({"type": "x", "data": {"app_name": "a"}, "timestamp": 0})
    sched.on_event(EventType.SCREEN_STABLE, {})
    assert triggered == []  # throttled by the reset cooldown
