"""Tests for hands-free conversation mode.

The VAD capture loop needs a live mic and can't run in CI; these cover the
session state machine and the turn-completion signalling that keeps the pet
from recording its own voice.
"""
from src.event_bus import EventType
from src.core.conversation import ConversationManager


def test_turn_signal_unblocks_next_turn(qapp, event_bus):
    """SPEECH_PLAYBACK_FINISHED / LLM_ERROR must release the turn wait."""
    mgr = ConversationManager(event_bus)
    assert not mgr._turn_done.is_set()
    mgr._on_turn_signal(EventType.SPEECH_PLAYBACK_FINISHED, {})
    assert mgr._turn_done.is_set()


def test_toggle_starts_then_ends_session(qapp, event_bus):
    mgr = ConversationManager(event_bus)
    assert not mgr.active

    # Not active -> toggle requests a session.
    mgr.toggle_session()
    assert mgr._session_requested.is_set()
    assert not mgr._end_session.is_set()

    # Active -> toggle ends the session.
    mgr._active = True
    mgr.toggle_session()
    assert mgr._end_session.is_set()


def test_stop_requests_thread_exit(qapp, event_bus):
    mgr = ConversationManager(event_bus)
    mgr.stop()  # thread never started; wait() returns immediately
    assert mgr._running is False
    assert mgr._end_session.is_set()
    assert mgr._session_requested.is_set()  # unblocks the idle wait
