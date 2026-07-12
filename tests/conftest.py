import pytest

# `qapp` (session-scoped QApplication) is provided by pytest-qt.


@pytest.fixture
def event_bus(qapp):
    """A fresh EventBus constructed on the test (GUI) thread."""
    from src.event_bus import EventBus
    return EventBus()


@pytest.fixture
def tmp_db(tmp_path):
    """An isolated Database instance backed by a per-test temp file.
    The persistent connection is closed on teardown (aiosqlite spawns a
    non-daemon worker thread per open connection)."""
    import asyncio
    from src.storage.db import Database
    db = Database(str(tmp_path / "test.db"))
    yield db
    try:
        asyncio.run(db.close())
    except Exception:
        pass
