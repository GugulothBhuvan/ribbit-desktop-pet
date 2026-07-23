"""Tests for Modi's cockroach panic run: trigger -> lift jhola -> sprint
(bouncing off walls) -> calm. Movement/state logic only; the live composite
render needs eyes."""
import src.physics.movement as mv
from src.config import Config
from src.constants import PetState
from src.physics.movement import MovementController


def test_panic_triggers_sling_for_modi(qapp, event_bus, monkeypatch):
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "modi")
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)
    monkeypatch.setattr(mv.random, "random", lambda: 0.0)   # < PANIC_CHANCE
    mc = MovementController(event_bus, 100.0, 100.0, 100, 100)
    assert mc._roll_idle_behavior() == PetState.SLING


def test_only_modi_panics(qapp, event_bus, monkeypatch):
    """A non-Modi mascot never panics; the same roll just walks."""
    monkeypatch.setattr(Config, "SELECTED_MASCOT", "default")
    monkeypatch.setattr(Config, "REDUCED_MOTION", False)
    monkeypatch.setattr(mv.random, "random", lambda: 0.0)   # panic skipped -> roll -> walk
    mc = MovementController(event_bus, 100.0, 100.0, 100, 100)
    assert mc._roll_idle_behavior() == PetState.WALK


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
