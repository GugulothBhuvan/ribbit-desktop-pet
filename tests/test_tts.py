"""Tests for text-to-speech: provider guards + manager gating.

Real synthesis/playback needs the network + an audio device and can't run in
CI; these cover the wiring, the speak/skip decision, and volume scaling.
"""
import asyncio
from src.config import Config
from src.event_bus import EventType
from src.core.tts import TTSManager
from src.ai.providers.deepgram_tts import DeepgramTTSProvider
from src.ai.providers.sarvam_tts import SarvamTTSProvider


class _DummyApp:
    def run_async(self, coro):
        coro.close()  # never actually scheduled in these tests


def _manager(event_bus, monkeypatch):
    mgr = TTSManager(event_bus, _DummyApp())
    calls = []
    monkeypatch.setattr(mgr, "speak", lambda text: calls.append(text))
    return mgr, calls


def test_synthesize_empty_text_returns_empty_clip(qapp):
    """Both providers must no-op on blank text without touching the network."""
    for p in (DeepgramTTSProvider(), SarvamTTSProvider()):
        assert not asyncio.run(p.synthesize(""))
        assert not asyncio.run(p.synthesize("   "))


def test_sarvam_wav_unwraps_to_pcm_with_real_format():
    """Sarvam returns a WAV container; the clip must carry its true format so
    playback doesn't assume Deepgram's 24 kHz."""
    import io, wave
    pcm = b"\x01\x02" * 100
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(pcm)

    clip = SarvamTTSProvider._wav_to_clip(buf.getvalue())
    assert clip.pcm == pcm
    assert clip.sample_rate == 22050
    assert clip.channels == 1
    assert clip.sample_width == 2


def test_provider_selection_follows_config(qapp, monkeypatch):
    monkeypatch.setattr(Config, "TTS_PROVIDER", "deepgram")
    assert isinstance(TTSManager._build_provider(), DeepgramTTSProvider)

    monkeypatch.setattr(Config, "TTS_PROVIDER", "sarvam")
    monkeypatch.setattr(Config, "SARVAM_API_KEY", "sk-real-looking-key")
    assert isinstance(TTSManager._build_provider(), SarvamTTSProvider)


def test_sarvam_without_key_falls_back_to_deepgram(qapp, monkeypatch):
    """Selecting Sarvam before adding its key must not silence the pet."""
    monkeypatch.setattr(Config, "TTS_PROVIDER", "sarvam")
    monkeypatch.setattr(Config, "SARVAM_API_KEY", "")
    monkeypatch.setattr(Config, "DEEPGRAM_API_KEY", "dg-real-looking-key")
    assert isinstance(TTSManager._build_provider(), DeepgramTTSProvider)


def test_speaks_conversational_reply(qapp, event_bus, monkeypatch):
    mgr, calls = _manager(event_bus, monkeypatch)
    monkeypatch.setattr(Config, "TTS_ENABLED", True)
    monkeypatch.setattr(Config, "MUTED", False)
    mgr.on_event(EventType.LLM_RESPONSE_RECEIVED, {"text": "hi", "conversational": True})
    assert calls == ["hi"]


def test_stays_silent_on_ambient_reply(qapp, event_bus, monkeypatch):
    """Unprompted screen comments must NOT be spoken aloud."""
    mgr, calls = _manager(event_bus, monkeypatch)
    monkeypatch.setattr(Config, "TTS_ENABLED", True)
    monkeypatch.setattr(Config, "MUTED", False)
    mgr.on_event(EventType.LLM_RESPONSE_RECEIVED, {"text": "nice code", "conversational": False})
    assert calls == []


def test_speaks_canned_voice_line(qapp, event_bus, monkeypatch):
    mgr, calls = _manager(event_bus, monkeypatch)
    monkeypatch.setattr(Config, "TTS_ENABLED", True)
    monkeypatch.setattr(Config, "MUTED", False)
    mgr.on_event(EventType.SPEECH_REQUESTED, {"text": "Hmm, I didn't catch that!"})
    assert calls == ["Hmm, I didn't catch that!"]


def test_muted_and_disabled_suppress_speech(qapp, event_bus, monkeypatch):
    mgr, calls = _manager(event_bus, monkeypatch)

    monkeypatch.setattr(Config, "TTS_ENABLED", True)
    monkeypatch.setattr(Config, "MUTED", True)
    mgr.on_event(EventType.LLM_RESPONSE_RECEIVED, {"text": "hi", "conversational": True})
    assert calls == []  # muted

    monkeypatch.setattr(Config, "MUTED", False)
    monkeypatch.setattr(Config, "TTS_ENABLED", False)
    mgr.on_event(EventType.SPEECH_REQUESTED, {"text": "hi"})
    assert calls == []  # tts disabled


def test_muted_reply_still_signals_turn_complete(qapp, event_bus, monkeypatch):
    """When it won't speak (muted), it must still fire SPEECH_PLAYBACK_FINISHED
    so a hands-free conversation loop doesn't hang waiting for audio."""
    mgr = TTSManager(event_bus, _DummyApp())
    published = []
    monkeypatch.setattr(mgr.event_bus, "publish", lambda et, d=None: published.append(et))
    monkeypatch.setattr(Config, "TTS_ENABLED", True)
    monkeypatch.setattr(Config, "MUTED", True)
    mgr.on_event(EventType.LLM_RESPONSE_RECEIVED, {"text": "hi", "conversational": True})
    assert EventType.SPEECH_PLAYBACK_FINISHED in published


def test_spoken_reply_defers_completion_until_after_playback(qapp, event_bus, monkeypatch):
    """When it WILL speak, completion must not fire immediately (that happens
    after playback, inside _synthesize_and_play) — else we'd reopen the mic and
    record the pet's own voice."""
    mgr = TTSManager(event_bus, _DummyApp())
    spoken, published = [], []
    monkeypatch.setattr(mgr, "speak", lambda t: spoken.append(t))
    monkeypatch.setattr(mgr.event_bus, "publish", lambda et, d=None: published.append(et))
    monkeypatch.setattr(Config, "TTS_ENABLED", True)
    monkeypatch.setattr(Config, "MUTED", False)
    mgr.on_event(EventType.LLM_RESPONSE_RECEIVED, {"text": "hi", "conversational": True})
    assert spoken == ["hi"]
    assert EventType.SPEECH_PLAYBACK_FINISHED not in published


# --- bubble/audio sync -------------------------------------------------------

def test_show_text_timed_paces_typing_to_audio(qapp):
    """The typewriter interval must come from the audio's real duration, not the
    fixed 40ms/char that raced ahead of the voice."""
    from PyQt6.QtCore import QPoint
    from src.ui.speech_bubble import SpeechBubble

    bubble = SpeechBubble()
    try:
        bubble.show_text_timed("x" * 100, 5.0, QPoint(0, 0), 100)
        assert bubble.typewriter_timer.interval() == 50  # 5000ms / 100 chars
    finally:
        bubble.close()


def test_show_text_timed_falls_back_without_duration(qapp):
    from PyQt6.QtCore import QPoint
    from src.ui.speech_bubble import SpeechBubble

    bubble = SpeechBubble()
    try:
        bubble.show_text_timed("hello", 0.0, QPoint(0, 0), 100)
        assert bubble.typewriter_timer.interval() == Config.SPEECH_TYPING_SPEED_MS
    finally:
        bubble.close()


def test_bubble_waits_only_for_replies_that_will_be_spoken(monkeypatch):
    """Must mirror TTSManager's speak/skip decision exactly — if they disagree,
    the bubble either races the voice or hangs on 'Thinking...' forever."""
    from src.ui.window import PetWindow

    monkeypatch.setattr(Config, "TTS_ENABLED", True)
    monkeypatch.setattr(Config, "MUTED", False)
    assert PetWindow._reply_will_be_spoken({"conversational": True}) is True
    assert PetWindow._reply_will_be_spoken({"conversational": False}) is False

    monkeypatch.setattr(Config, "MUTED", True)
    assert PetWindow._reply_will_be_spoken({"conversational": True}) is False

    monkeypatch.setattr(Config, "MUTED", False)
    monkeypatch.setattr(Config, "TTS_ENABLED", False)
    assert PetWindow._reply_will_be_spoken({"conversational": True}) is False


def test_apply_volume_scales_samples():
    import numpy as np
    pcm = np.array([10000, -10000, 20000], dtype=np.int16).tobytes()
    orig = Config.PET_VOLUME
    try:
        # Full volume: returned untouched (fast path)
        Config.PET_VOLUME = 1.0
        assert TTSManager._apply_volume(pcm) == pcm
        # Half volume: samples halved
        Config.PET_VOLUME = 0.5
        out = np.frombuffer(TTSManager._apply_volume(pcm), dtype=np.int16)
        assert list(out) == [5000, -5000, 10000]
    finally:
        Config.PET_VOLUME = orig
