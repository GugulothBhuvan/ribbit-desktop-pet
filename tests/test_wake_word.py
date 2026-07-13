"""Tests for the local wake-word listener (openWakeWord).

Actual detection needs a mic + the optional dependency and can't run in CI;
these cover the wiring, config gating, and graceful-degradation paths.
"""
from src.config import Config
from src.observer.wake_word import WakeWordListener


def test_disabled_by_default(qapp, event_bus):
    """Off unless explicitly enabled — preserves the mic-off privacy posture."""
    original = Config.WAKE_WORD_ENABLED
    try:
        Config.WAKE_WORD_ENABLED = False
        listener = WakeWordListener(event_bus)
        # run() must return immediately without opening a mic or model
        listener.run()
        assert listener.active is False
    finally:
        Config.WAKE_WORD_ENABLED = original


def test_missing_dependency_degrades_gracefully(qapp, event_bus, monkeypatch):
    """Enabled but openwakeword not installed -> logs and disables, never raises."""
    import builtins
    original = Config.WAKE_WORD_ENABLED
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "openwakeword" or name.startswith("openwakeword."):
            raise ImportError("simulated missing dependency")
        return real_import(name, *args, **kwargs)

    try:
        Config.WAKE_WORD_ENABLED = True
        monkeypatch.setattr(builtins, "__import__", fake_import)
        listener = WakeWordListener(event_bus)
        listener.run()  # must not raise
        assert listener.active is False
    finally:
        Config.WAKE_WORD_ENABLED = original


def test_resolve_builtin_vs_custom_model():
    """Built-in name passes through; a custom file resolves to (abspath,
    basename-without-ext score key, framework). Getting the score key wrong
    means detections silently never match."""
    import os
    arg, key, fw = WakeWordListener._resolve_model("hey_jarvis")
    assert (arg, key, fw) == ("hey_jarvis", "hey_jarvis", None)

    arg, key, fw = WakeWordListener._resolve_model("assets/wake/hey_pet.onnx")
    assert key == "hey_pet"
    assert fw == "onnx"
    assert os.path.isabs(arg)

    arg, key, fw = WakeWordListener._resolve_model("models/my_phrase.tflite")
    assert key == "my_phrase"
    assert fw == "tflite"


def test_manual_trigger_sets_flag(qapp, event_bus):
    listener = WakeWordListener(event_bus)
    assert not listener._manual_trigger.is_set()
    listener.trigger_manual()
    assert listener._manual_trigger.is_set()


def test_hotkey_routes_to_listener_when_active(qapp, event_bus, tmp_db, monkeypatch):
    """With the wake word owning the mic, the hotkey must trigger the listener,
    not open a second mic stream via AudioRecorder."""
    from src.ui.window import PetWindow
    from src.animation.sprite_loader import SpriteLoader
    from src.core.audio_recorder import AudioRecorder
    from src.core.application import Application

    listener = WakeWordListener(event_bus)
    monkeypatch.setattr(type(listener), "active", property(lambda self: True))

    triggered = {"manual": False, "recorder_started": False}
    monkeypatch.setattr(listener, "trigger_manual", lambda: triggered.__setitem__("manual", True))

    recorder = AudioRecorder()
    monkeypatch.setattr(recorder, "start_recording",
                        lambda: triggered.__setitem__("recorder_started", True))
    try:
        win = PetWindow(event_bus, SpriteLoader(), recorder, tmp_db,
                        Application(), scheduler=None, wake_listener=listener)
        win._toggle_ptt()
        assert triggered["manual"] is True
        assert triggered["recorder_started"] is False
        win.close()
    finally:
        recorder.cleanup()
