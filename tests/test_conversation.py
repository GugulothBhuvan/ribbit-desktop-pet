"""Tests for hands-free conversation mode.

The VAD capture loop needs a live mic and can't run in CI; these cover the
session state machine and the turn-completion signalling that keeps the pet
from recording its own voice.
"""
from src.config import Config
from src.event_bus import EventType
from src.core.conversation import ConversationManager


def test_hotkey_falls_back_to_ptt_when_conversation_unusable(qapp, event_bus, tmp_db, monkeypatch):
    """Without the [voice] extra the conversation thread exits immediately.
    The hotkey must fall back to push-to-talk — routing to a dead session
    manager showed "I'm listening..." and then did nothing at all."""
    from src.ui.window import PetWindow
    from src.animation.sprite_loader import SpriteLoader
    from src.core.audio_recorder import AudioRecorder
    from src.core.application import Application

    mgr = ConversationManager(event_bus)
    mgr._usable = False  # simulate the voice extra not being installed

    called = {"session": False, "ptt": False}
    monkeypatch.setattr(mgr, "toggle_session", lambda: called.__setitem__("session", True))
    monkeypatch.setattr(Config, "CONVERSATION_MODE", True)

    recorder = AudioRecorder()
    monkeypatch.setattr(recorder, "start_recording", lambda: called.__setitem__("ptt", True))
    try:
        win = PetWindow(event_bus, SpriteLoader(), recorder, tmp_db, Application(),
                        scheduler=None, conversation_manager=mgr)
        win._toggle_ptt()
        assert called["session"] is False, "must not start a session it can't run"
        assert called["ptt"] is True, "must fall back to push-to-talk"
        win.close()
    finally:
        recorder.cleanup()


def test_usable_by_default(qapp, event_bus):
    assert ConversationManager(event_bus).usable is True


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
