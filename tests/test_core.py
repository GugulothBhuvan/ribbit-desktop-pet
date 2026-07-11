import os
import pytest
from src.config import Config
from src.event_bus import EventBus, EventType
from src.physics.gravity import GravitySimulator
from src.storage.db import Database
from src.storage.repository import ConversationRepository, MemoryRepository, SettingsRepository

def test_config():
    Config.validate()
    assert Config.LLM_PROVIDER in ["krutrim"]

def test_event_bus():
    bus = EventBus.get_instance()
    events = []
    
    def on_event(event_type, data):
        events.append((event_type, data))
        
    bus.subscribe(on_event)
    bus.publish(EventType.APPLICATION_STARTED, {"test": True})
    bus.unsubscribe(on_event)
    
    assert len(events) == 1
    assert events[0] == (EventType.APPLICATION_STARTED, {"test": True})

def test_gravity():
    vy = 0.0
    new_vy = GravitySimulator.apply_gravity(vy)
    assert new_vy > vy
    
@pytest.mark.asyncio
async def test_database_and_repos():
    # Use temporary DB for test isolation
    original_db = Config.DB_PATH
    Config.DB_PATH = "storage/test_memory.db"
    
    db = Database.get_instance()
    db.db_path = Config.DB_PATH
    await db.initialize()
    
    conv_repo = ConversationRepository(db)
    memory_repo = MemoryRepository(db)
    
    # Assert clean slate
    await conv_repo.clear_history()
    await memory_repo.clear_memory()
    
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
    
    # Cleanup DB connection and file
    Config.DB_PATH = original_db
    db.db_path = original_db
    
    # Safely remove test database
    try:
        if os.path.exists("storage/test_memory.db"):
            os.remove("storage/test_memory.db")
    except Exception:
        pass

@pytest.mark.asyncio
async def test_mascot_and_config_overrides(qapp):
    # Setup test isolate DB
    original_db = Config.DB_PATH
    Config.DB_PATH = "storage/test_config.db"
    
    db = Database.get_instance()
    db.db_path = Config.DB_PATH
    await db.initialize()
    
    # Persist overrides
    repo = SettingsRepository(db)
    await repo.set_setting("SELECTED_MASCOT", "default")
    await repo.set_setting("LLM_PROVIDER", "krutrim")
    await repo.set_setting("KRUTRIM_MODEL", "krutrim-2-flash")
    
    # Load overrides
    await Config.load_db_overrides()
    assert Config.SELECTED_MASCOT == "default"
    assert Config.LLM_PROVIDER == "krutrim"
    assert Config.KRUTRIM_MODEL == "krutrim-2-flash"
    
    # Test SpriteLoader swapping
    from src.animation.sprite_loader import SpriteLoader
    loader = SpriteLoader.get_instance()
    loader.set_mascot("default")
    assert loader.sprite_dir == os.path.join("assets", "sprites", "default")
    assert loader.metadata["sprite_sheet"] == "spritesheet.png"
    
    # Reset config for other tests
    Config.SELECTED_MASCOT = "default"
    Config.LLM_PROVIDER = "krutrim"
    
    # Cleanup DB connection and file
    Config.DB_PATH = original_db
    db.db_path = original_db
    try:
        if os.path.exists("storage/test_config.db"):
            os.remove("storage/test_config.db")
    except Exception:
        pass

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
    assert parts[1]["inlineData"]["mimeType"] == "image/png"
    assert len(parts[1]["inlineData"]["data"]) > 0

def test_audio_recorder():
    from src.core.audio_recorder import AudioRecorder
    recorder = AudioRecorder.get_instance()
    assert recorder is not None
    assert recorder.is_recording is False
    assert recorder.channels == 1
    assert recorder.rate == 16000
    assert recorder.chunk_size == 1024
    assert recorder.output_filename == "speech_record.wav"

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
