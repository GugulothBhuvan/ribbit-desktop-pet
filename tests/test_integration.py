"""IT-1 (MVP_PLAN Phase 8.3): boots the full composition root and drives the
core product loop end-to-end with a mocked LLM provider — the test that would
have caught the original audit's headline finding (an app whose state machine
and AI pipeline had never once functioned).

The window is never shown (its timers run regardless), the OS observer /
hotkey / scheduler are not started, and calm mode keeps the ambient behavior
deterministic.
"""
import pytest
from src.config import Config
from src.constants import PetState
from src.event_bus import EventType


class FakeProvider:
    """Streams a canned reply; never touches the network."""
    async def stream(self, prompt, context):
        for chunk in ["Beep ", "boop, ", "fake ", "LLM ", "here!"]:
            yield chunk

    async def generate(self, prompt, context):
        return "Beep boop, fake LLM here!"

    def supports_vision(self):
        return False

    async def health(self):
        return True

    async def aclose(self):
        pass


@pytest.fixture
def app_root(qapp, tmp_path):
    original_db = Config.DB_PATH
    original_provider = Config.LLM_PROVIDER
    original_calm = Config.REDUCED_MOTION
    Config.DB_PATH = str(tmp_path / "it1.db")
    Config.LLM_PROVIDER = "krutrim"
    Config.REDUCED_MOTION = True  # deterministic: no random wandering mid-test

    from src.core.composition import CompositionRoot
    root = CompositionRoot()
    root.orchestrator.krutrim_provider = FakeProvider()

    yield root

    root.window.close()
    root.shutdown()
    Config.DB_PATH = original_db
    Config.LLM_PROVIDER = original_provider
    Config.REDUCED_MOTION = original_calm


def test_it1_drop_land_chat_cycle(qtbot, app_root):
    root = app_root

    states = []
    responses = []
    root.event_bus.subscribe(
        EventType.SPRITE_CHANGED, lambda t, d: states.append(d.get("state")), executor="gui")
    root.event_bus.subscribe(
        EventType.LLM_RESPONSE_RECEIVED, lambda t, d: responses.append(d.get("text")), executor="gui")

    # --- Physics cycle: lift the pet, gravity must land it back on the floor
    root.window.physics.y = 100.0
    root.window.physics.vy = 0.0

    qtbot.waitUntil(lambda: PetState.FALL in states, timeout=5000)
    qtbot.waitUntil(lambda: PetState.LANDING in states, timeout=5000)
    qtbot.waitUntil(lambda: root.state_machine.current_state == PetState.IDLE, timeout=5000)

    screen_rect = root.window.screen().availableGeometry()
    floor_y = screen_rect.top() + screen_rect.height() - root.window.pet_height
    assert abs(root.window.physics.y - floor_y) <= 2

    # --- Chat cycle: click-equivalent query streams think -> chunks -> talk
    root.event_bus.publish(EventType.CHAT_QUERY_REQUESTED, {
        "prompt": "Tell me a joke", "pet_state": {"state": "idle", "x": 0, "y": 0}})

    qtbot.waitUntil(lambda: PetState.THINK in states, timeout=5000)
    qtbot.waitUntil(lambda: responses == ["Beep boop, fake LLM here!"], timeout=8000)
    qtbot.waitUntil(lambda: root.state_machine.current_state == PetState.TALK, timeout=5000)

    # Bubble holds exactly the reply (placeholder replaced, stream clamped)
    assert root.window.speech_bubble.full_text == "Beep boop, fake LLM here!"
