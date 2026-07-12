"""Regression tests for Phase 6 (persistence & ambient) and Phase 7 (lifecycle)."""
import pytest
from src.config import Config


# --- 6.1: WAL mode on the persistent connection ------------------------------

@pytest.mark.asyncio
async def test_database_uses_wal_and_single_connection(tmp_db):
    await tmp_db.initialize()
    rows = await tmp_db.execute_query("PRAGMA journal_mode;")
    assert rows[0]["journal_mode"].lower() == "wal"
    # Same connection object across calls (no per-query reconnect)
    conn1 = await tmp_db._get_conn()
    conn2 = await tmp_db._get_conn()
    assert conn1 is conn2


# --- 6.2: prune bounds table growth -------------------------------------------

@pytest.mark.asyncio
async def test_prune_bounds_conversation(tmp_db):
    from src.storage.db import CONVERSATION_KEEP_ROWS
    from src.storage.repository import ConversationRepository

    await tmp_db.initialize()
    repo = ConversationRepository(tmp_db)
    for i in range(CONVERSATION_KEEP_ROWS + 25):
        await repo.add_message("user", f"msg {i}")

    await tmp_db.prune()

    rows = await tmp_db.execute_query("SELECT COUNT(*) AS n FROM conversation;")
    assert rows[0]["n"] == CONVERSATION_KEEP_ROWS
    # The newest rows survive
    newest = await repo.get_recent_messages(limit=1)
    assert newest[0]["message"] == f"msg {CONVERSATION_KEEP_ROWS + 24}"


# --- 6.2: corrupt DB file is backed up and recreated ---------------------------

@pytest.mark.asyncio
async def test_corrupt_database_recovery(tmp_path):
    import os
    from src.storage.db import Database

    db_file = tmp_path / "corrupt.db"
    db_file.write_bytes(b"this is definitely not a sqlite database" * 100)

    db = Database(str(db_file))
    try:
        await db.initialize()  # must not raise
        # Works after recovery
        await db.execute_non_query(
            "INSERT INTO memory (key, val) VALUES (?, ?);", ("k", "v"))
        rows = await db.execute_query("SELECT val FROM memory WHERE key='k';")
        assert rows[0]["val"] == "v"
        # The corrupt original was preserved as a backup
        backups = [f for f in os.listdir(tmp_path) if "corrupt-" in f]
        assert len(backups) == 1
    finally:
        await db.close()


# --- 6.5: settings persistence round-trip -------------------------------------

@pytest.mark.asyncio
async def test_preferences_roundtrip_through_db_overrides(tmp_db):
    from src.storage.repository import SettingsRepository

    await tmp_db.initialize()
    repo = SettingsRepository(tmp_db)
    await repo.set_setting("PET_SCALE", "1.5")
    await repo.set_setting("MUTED", "1")
    await repo.set_setting("REDUCED_MOTION", "1")
    await repo.set_setting("SPEECH_TYPING_SPEED_MS", "80")

    orig = (Config.ANIMATION_SCALE, Config.MUTED, Config.REDUCED_MOTION, Config.SPEECH_TYPING_SPEED_MS)
    try:
        await Config.load_db_overrides(tmp_db)
        assert Config.ANIMATION_SCALE == 1.5
        assert Config.MUTED is True
        assert Config.REDUCED_MOTION is True
        assert Config.SPEECH_TYPING_SPEED_MS == 80
    finally:
        (Config.ANIMATION_SCALE, Config.MUTED,
         Config.REDUCED_MOTION, Config.SPEECH_TYPING_SPEED_MS) = orig


# --- 6.5: calm mode keeps the pet idle -----------------------------------------

def test_calm_mode_never_wanders(qapp, event_bus):
    from PyQt6.QtGui import QGuiApplication
    from src.constants import PetState
    from src.physics.movement import MovementController

    geom = QGuiApplication.primaryScreen().availableGeometry()
    floor_y = geom.top() + geom.height() - 100
    mc = MovementController(event_bus, float(geom.center().x()), float(floor_y), 100, 100)

    original = Config.REDUCED_MOTION
    try:
        Config.REDUCED_MOTION = True
        # Roll the idle wheel many times: must always stay idle
        for _ in range(50):
            assert mc._roll_idle_behavior() == PetState.IDLE
    finally:
        Config.REDUCED_MOTION = original


# --- 7: scheduler stops gracefully ---------------------------------------------

@pytest.mark.asyncio
async def test_scheduler_run_loop_exits_on_stop(event_bus, tmp_db):
    import asyncio
    from src.ai.context_engine import ContextEngine
    from src.core.scheduler import AmbientScheduler

    await tmp_db.initialize()
    sched = AmbientScheduler(event_bus, tmp_db, ContextEngine())

    # Weather fetch would hit the network on the first tick — neutralize
    async def _no_weather():
        pass
    sched.fetch_local_weather = _no_weather

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(1.2)  # let at least one tick happen
    sched.stop()
    await asyncio.wait_for(task, timeout=3.0)  # must exit, not hang
