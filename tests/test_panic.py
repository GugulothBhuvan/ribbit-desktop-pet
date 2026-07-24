"""Tests for Modi's cockroach panic run: trigger -> lift jhola -> sprint
(bouncing off walls) -> calm. Movement/state logic only; the live composite
render needs eyes."""
import src.physics.movement as mv
from src.config import Config
from src.constants import PetState
from src.physics.movement import MovementController


def test_roach_trigger_for_modi(qapp, event_bus, monkeypatch):
    """The rare Modi roll spawns a roach and keeps idling — the panic itself
    fires later, when the roach reaches him (ROACH_SIGHTED)."""
    from src.event_bus import EventType
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)
    monkeypatch.setattr(mv.random, "random", lambda: 0.0)   # < PANIC_CHANCE
    mc = MovementController(event_bus, 100.0, 100.0, 100, 100)
    pub = []
    monkeypatch.setattr(mc.event_bus, "publish", lambda et, d=None: pub.append((et, d)))
    assert mc._roll_idle_behavior() == PetState.IDLE
    assert any(et == EventType.ROACH_SPAWN_REQUESTED for et, _ in pub)


def test_only_modi_spawns_a_roach(qapp, event_bus, monkeypatch):
    """A non-Modi mascot never triggers the roach; the same roll just walks."""
    from src.event_bus import EventType
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "default")
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)
    monkeypatch.setattr(mv.random, "random", lambda: 0.0)   # panic skipped -> roll -> walk
    mc = MovementController(event_bus, 100.0, 100.0, 100, 100)
    pub = []
    monkeypatch.setattr(mc.event_bus, "publish", lambda et, d=None: pub.append((et, d)))
    assert mc._roll_idle_behavior() == PetState.WALK
    assert not any(et == EventType.ROACH_SPAWN_REQUESTED for et, _ in pub)


def test_panic_run_bounces_then_calms(qapp, event_bus, monkeypatch):
    """PANIC_RUN sprints at run speed, bounces off the walls a fixed number of
    times, then recommends IDLE — never runs forever."""
    from PyQt6.QtGui import QGuiApplication
    from src.constants import PANIC_RUN_SPEED
    monkeypatch.setattr(mv.random, "randint", lambda a, b: 2)   # exactly 2 bounces
    monkeypatch.setattr(mv.random, "choice", lambda seq: 1)     # start rightward

    geom = QGuiApplication.primaryScreen().availableGeometry()
    w = h = 100
    mc = MovementController(event_bus, float(geom.center().x()),
                            float(geom.top() + geom.height() - h), w, h)
    # first tick initialises the run
    x0 = mc.x
    mc.update(PetState.PANIC_RUN, False, 1 / 60)
    assert abs(mc.vx) == PANIC_RUN_SPEED and mc._panic_active

    calmed = False
    state = PetState.PANIC_RUN
    for _ in range(60 * 30):        # up to 30s
        _, _, rec = mc.update(state, False, 1 / 60)
        if rec == PetState.IDLE:
            calmed = True
            break
    assert calmed and mc._panic_active is False


def test_flee_panic_runs_away_and_calms_at_wall(qapp, event_bus, monkeypatch):
    """A roach-triggered flee sprints one way, hits the far wall, and calms —
    it never reverses (that would send Modi back into the roach)."""
    from PyQt6.QtGui import QGuiApplication
    geom = QGuiApplication.primaryScreen().availableGeometry()
    w = h = 100
    # Near the right wall, fleeing right: he should reach the wall and stop dead.
    mc = MovementController(event_bus, float(geom.right() - w - 40),
                            float(geom.top() + geom.height() - h), w, h)
    mc.set_flee(1)
    calmed = False
    for _ in range(60 * 20):
        _, _, rec = mc.update(PetState.PANIC_RUN, False, 1 / 60)
        if rec == PetState.IDLE:
            calmed = True
            break
    assert calmed
    assert mc.walk_direction == 1                 # never turned back toward the roach
    assert mc._flee_direction == 0 and not mc._panic_active


def test_flee_direction_is_away_from_roach(qapp, event_bus, tmp_db, monkeypatch):
    """Modi always flees to the side opposite the roach (his back to it)."""
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)
    win, recorder = _modi_window(event_bus, tmp_db, monkeypatch)
    try:
        center = win.physics.x + win.pet_width / 2
        win._react_to_roach({"roach_x": center + 400})   # roach on the right
        win._panic_from_roach()
        assert win.physics._flee_direction == -1         # -> flee left
        win._reacting_to_roach = False
        win._react_to_roach({"roach_x": center - 400})   # roach on the left
        win._panic_from_roach()
        assert win.physics._flee_direction == 1          # -> flee right
        win.close()
    finally:
        recorder.cleanup()


def _modi_window(event_bus, tmp_db, monkeypatch):
    from src.ui.window import PetWindow
    from src.animation.sprite_loader import SpriteLoader
    from src.core.audio_recorder import AudioRecorder
    from src.core.application import Application
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    recorder = AudioRecorder()
    win = PetWindow(event_bus, SpriteLoader(), recorder, tmp_db, Application(), scheduler=None)
    return win, recorder


def test_menu_trigger_spawns_roach(qapp, event_bus, tmp_db, monkeypatch):
    """The on-demand menu item sends in a roach; the pet panics once it arrives."""
    from src.event_bus import EventType
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)
    win, recorder = _modi_window(event_bus, tmp_db, monkeypatch)
    try:
        pub = []
        monkeypatch.setattr(win.event_bus, "publish", lambda et, d=None: pub.append((et, d)))
        win.trigger_panic_run()
        assert any(et == EventType.ROACH_SPAWN_REQUESTED for et, d in pub)
        win.close()
    finally:
        recorder.cleanup()


def test_menu_trigger_blocked_by_calm_mode(qapp, event_bus, tmp_db, monkeypatch):
    """Calm Mode suppresses the roach entirely; the pet says so instead."""
    from src.event_bus import EventType
    monkeypatch.setattr(Config, "REDUCED_MOTION", True)
    win, recorder = _modi_window(event_bus, tmp_db, monkeypatch)
    try:
        pub = []
        monkeypatch.setattr(win.event_bus, "publish", lambda et, d=None: pub.append((et, d)))
        win.trigger_panic_run()
        assert not any(et == EventType.ROACH_SPAWN_REQUESTED for et, d in pub)
        win.close()
    finally:
        recorder.cleanup()


def test_roach_sighted_freezes_then_slings(qapp, event_bus, tmp_db, monkeypatch):
    """ROACH_SIGHTED: Modi first freezes (IDLE), then the deferred reaction lifts
    the jhola (SLING) — which the state machine chains into PANIC_RUN."""
    from src.event_bus import EventType
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)
    win, recorder = _modi_window(event_bus, tmp_db, monkeypatch)
    try:
        pub = []
        monkeypatch.setattr(win.event_bus, "publish", lambda et, d=None: pub.append((et, d)))
        win._react_to_roach()
        assert win._reacting_to_roach
        assert any(et == EventType.STATE_TRANSITION_TRIGGERED
                   and (d or {}).get("state") == PetState.IDLE for et, d in pub)
        win._panic_from_roach()                       # the deferred second half
        assert not win._reacting_to_roach
        assert any(et == EventType.STATE_TRANSITION_TRIGGERED
                   and (d or {}).get("state") == PetState.SLING for et, d in pub)
        win.close()
    finally:
        recorder.cleanup()


def test_sling_chains_to_panic_run(qapp, event_bus, monkeypatch):
    """When the jhola-lift (SLING) animation finishes, the state machine sends
    him into PANIC_RUN."""
    from src.animation.state_machine import StateMachine
    from src.animation.sprite_loader import SpriteLoader
    from src.event_bus import EventType
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    sm = StateMachine(event_bus, SpriteLoader())
    assert sm.set_state(PetState.SLING) is True
    sm.on_event(EventType.ANIMATION_FINISHED, {"state": PetState.SLING})
    assert sm.current_state == PetState.PANIC_RUN


def test_roach_window_chases_sights_and_exits(qapp, event_bus, monkeypatch):
    """The roach loads, spawns on a spawn request, emits ROACH_SIGHTED once it
    closes on a startle-able Modi, and heads out once he has calmed."""
    from PyQt6.QtGui import QGuiApplication
    from src.ui.roach_window import RoachWindow
    from src.event_bus import EventType
    from src.constants import ROACH_SEE_DISTANCE
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)

    geom = QGuiApplication.primaryScreen().availableGeometry()

    class _Renderer:
        current_state = PetState.IDLE

    class _FakePet:
        pet_width = 120

        def __init__(self):
            self.physics = type("P", (), {"x": float(geom.center().x() - 60)})()
            self.renderer = _Renderer()

        def screen(self):
            return QGuiApplication.primaryScreen()

    pet = _FakePet()
    roach = RoachWindow(event_bus, pet)
    assert roach._frames, "roach sprite frames must load"

    roach.spawn()
    assert roach._active

    pub = []
    monkeypatch.setattr(roach.event_bus, "publish", lambda et, d=None: pub.append((et, d)))

    # Bring it within sight of an idle (startle-able) Modi and tick once.
    modi_center = pet.physics.x + pet.pet_width / 2
    roach._center_x = modi_center - (ROACH_SEE_DISTANCE - 20)
    roach._tick()
    assert any(et == EventType.ROACH_SIGHTED for et, _ in pub)

    # Modi panics, then calms -> the roach should switch to leaving.
    roach._on_event(EventType.SPRITE_CHANGED, {"state": PetState.PANIC_RUN})
    roach._on_event(EventType.SPRITE_CHANGED, {"state": PetState.IDLE})
    assert roach._exiting
    roach.despawn()
    assert not roach._active
