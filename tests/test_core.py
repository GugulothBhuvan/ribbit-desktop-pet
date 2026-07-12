import os
import pytest
from src.config import Config
from src.event_bus import EventType
from src.physics.gravity import GravitySimulator
from src.storage.repository import ConversationRepository, MemoryRepository, SettingsRepository

def test_config():
    Config.validate()
    assert Config.LLM_PROVIDER in ["krutrim", "gemini"]

def test_event_bus(event_bus):
    events = []

    def on_event(event_type, data):
        events.append((event_type, data))

    event_bus.subscribe(EventType.APPLICATION_STARTED, on_event, executor="gui")
    event_bus.publish(EventType.APPLICATION_STARTED, {"test": True})
    event_bus.unsubscribe(EventType.APPLICATION_STARTED, on_event)

    # Same-thread GUI delivery is synchronous (direct connection)
    assert len(events) == 1
    assert events[0] == (EventType.APPLICATION_STARTED, {"test": True})

def test_event_bus_per_type_filtering(event_bus):
    received = []
    event_bus.subscribe(EventType.TESTS_PASSED, lambda t, d: received.append(t), executor="gui")

    event_bus.publish(EventType.TESTS_FAILED, {})
    event_bus.publish(EventType.TESTS_PASSED, {})

    assert received == [EventType.TESTS_PASSED]

def test_gravity():
    vy = 0.0
    new_vy = GravitySimulator.apply_gravity(vy)
    assert new_vy > vy

@pytest.mark.asyncio
async def test_database_and_repos(tmp_db):
    await tmp_db.initialize()

    conv_repo = ConversationRepository(tmp_db)
    memory_repo = MemoryRepository(tmp_db)

    # Test conversation history
    await conv_repo.add_message("user", "Hello world")
    history = await conv_repo.get_recent_messages(limit=5)
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert history[0]["message"] == "Hello world"

    # Test memory facts
    await memory_repo.save_fact("favorite_editor", "VS Code")
    fact = await memory_repo.get_fact("favorite_editor")
    assert fact == "VS Code"

@pytest.mark.asyncio
async def test_mascot_and_config_overrides(qapp, tmp_db):
    await tmp_db.initialize()

    # Persist overrides
    repo = SettingsRepository(tmp_db)
    await repo.set_setting("SELECTED_MASCOT", "default")
    await repo.set_setting("LLM_PROVIDER", "krutrim")
    await repo.set_setting("KRUTRIM_MODEL", "krutrim-2-flash")

    # Load overrides from the injected database
    await Config.load_db_overrides(tmp_db)
    assert Config.SELECTED_MASCOT == "default"
    assert Config.LLM_PROVIDER == "krutrim"
    assert Config.KRUTRIM_MODEL == "krutrim-2-flash"

    # Test SpriteLoader swapping
    from src.animation.sprite_loader import SpriteLoader
    loader = SpriteLoader()
    loader.set_mascot("default")
    assert loader.sprite_dir == os.path.join("assets", "sprites", "default")
    assert loader.metadata["sprite_sheet"] == "spritesheet.png"

    # Reset config for other tests
    Config.SELECTED_MASCOT = "default"
    Config.LLM_PROVIDER = "krutrim"

def test_gemini_multimodal_payload():
    from src.ai.providers.gemini import GeminiProvider
    provider = GeminiProvider()

    # 1. Text only context
    payload = provider._build_payload("Hello", {"system_prompt": "Prompt"})
    assert len(payload["contents"][0]["parts"]) == 1
    assert payload["contents"][0]["parts"][0]["text"] == "Hello"

    # 2. Multimodal context with bytes
    test_bytes = b"fake-png-data"
    payload = provider._build_payload("Check this screen", {
        "system_prompt": "Prompt",
        "screenshot_bytes": test_bytes
    })
    parts = payload["contents"][0]["parts"]
    assert len(parts) == 2
    assert parts[0]["text"] == "Check this screen"
    assert parts[1]["inlineData"]["mimeType"] == "image/jpeg"
    assert len(parts[1]["inlineData"]["data"]) > 0

def test_gemini_key_never_in_url():
    """Regression: the API key must be sent via header, never as a query param (C-5)."""
    from src.ai.providers.gemini import GeminiProvider
    provider = GeminiProvider()
    provider.api_key = "SECRET-KEY-123"
    assert "SECRET-KEY-123" not in provider._get_url(stream=False)
    assert "SECRET-KEY-123" not in provider._get_url(stream=True)
    assert provider._get_headers()["x-goog-api-key"] == "SECRET-KEY-123"

def test_audio_recorder():
    import tempfile
    from src.core.audio_recorder import AudioRecorder
    recorder = AudioRecorder()
    try:
        assert recorder.is_recording is False
        assert recorder.channels == 1
        assert recorder.rate == 16000
        assert recorder.chunk_size == 1024
        # PTT recordings must live in the OS temp dir, never the project folder
        assert recorder.output_filename.startswith(tempfile.gettempdir())
    finally:
        recorder.cleanup()

def test_ide_context_compilation():
    from src.ai.context_engine import ContextEngine
    engine = ContextEngine()

    # Check Git context
    git_ctx = engine.get_git_context()
    assert "git_available" in git_ctx
    assert "uncommitted_files_count" in git_ctx
    assert "last_commit_message" in git_ctx

    # Check Test context
    test_ctx = engine.get_test_context()
    assert "recent_test_run_outcome" in test_ctx
    assert "failed_tests_count" in test_ctx
    assert "is_fresh" in test_ctx

    # Check full context assembly
    full_ctx = engine.assemble_context({"state": "idle", "x": 10, "y": 20})
    assert "git_available" in full_ctx
    assert "git_uncommitted_count" in full_ctx
    assert "git_last_commit" in full_ctx
    assert "test_outcome" in full_ctx
    assert "test_failed_count" in full_ctx
    assert "test_is_fresh" in full_ctx
