"""Text-to-speech playback manager.

Gives the pet a voice: when a conversational reply (or a canned voice-flow line)
is ready, it is synthesized via Deepgram Aura and played aloud.

Threading model:
  - Event delivery is on the GUI thread (executor="gui").
  - Synthesis is an async HTTP call scheduled on the worker loop.
  - Playback (blocking PyAudio writes) runs on a threadpool thread, serialized
    by a lock. A newer utterance signals the current one to stop (barge-in), so
    replies never pile up on top of each other.

Everything degrades gracefully: no key, no PyAudio, muted, or a synthesis error
just means no audio — the text bubble still shows.
"""
import threading
from typing import Any

from PyQt6.QtCore import QObject
from src.config import Config
from src.event_bus import EventBus, EventType
from src.ai.providers.tts_base import AudioClip
from src.ai.providers.deepgram_tts import DeepgramTTSProvider
from src.ai.providers.sarvam_tts import SarvamTTSProvider
from src.utils.logger import get_logger

logger = get_logger("TTS")

_PLAY_CHUNK = 2048  # frames per PyAudio write; small enough for responsive stops


class TTSManager(QObject):
    SUBSCRIBED_EVENTS = [
        EventType.LLM_RESPONSE_RECEIVED,
        EventType.SPEECH_REQUESTED,
    ]

    def __init__(self, event_bus: EventBus, application):
        super().__init__()
        self.event_bus = event_bus
        self.application = application
        self.provider = self._build_provider()

        self._pa: Any = None                # lazily created PyAudio instance (untyped lib)
        self._play_lock = threading.Lock()  # serializes playback threads
        self._stop_flag = threading.Event() # asks the active playback to abort

        for event_type in self.SUBSCRIBED_EVENTS:
            self.event_bus.subscribe(event_type, self.on_event, executor="gui")

    @staticmethod
    def _build_provider():
        """Resolves the TTS engine from config. Sarvam gives the pet a genuine
        Indian-English voice; Deepgram Aura is the US-accented alternative.

        If Sarvam is selected but has no key, fall back to Deepgram rather than
        going mute — the pet keeps its voice until SARVAM_API_KEY is filled in,
        then switches automatically.
        """
        if Config.TTS_PROVIDER == "deepgram":
            logger.info(f"TTS: Deepgram Aura ({Config.TTS_VOICE})")
            return DeepgramTTSProvider()

        sarvam = SarvamTTSProvider()
        if not sarvam._configured():
            deepgram = DeepgramTTSProvider()
            if deepgram._configured():
                logger.warning("TTS_PROVIDER=sarvam but SARVAM_API_KEY is not set; "
                               "falling back to Deepgram Aura for now.")
                return deepgram
            logger.warning("TTS_PROVIDER=sarvam but SARVAM_API_KEY is not set "
                           "(and no Deepgram key either) — the pet will stay silent.")
            return sarvam

        logger.info(f"TTS: Sarvam {Config.SARVAM_TTS_MODEL} "
                    f"({Config.SARVAM_TTS_SPEAKER}, {Config.SARVAM_TTS_LANGUAGE})")
        return sarvam

    def on_event(self, event_type: str, data: dict):
        text = data.get("text", "")
        # A "response turn" is the pet answering the user: a conversational LLM
        # reply, or a canned voice-flow line (SPEECH_REQUESTED). Ambient screen
        # asides (conversational=False) are never spoken aloud.
        is_response_turn = (
            (event_type == EventType.LLM_RESPONSE_RECEIVED and data.get("conversational"))
            or event_type == EventType.SPEECH_REQUESTED
        )
        if not is_response_turn:
            return

        will_speak = bool(text) and Config.TTS_ENABLED and not Config.MUTED
        if will_speak:
            self.speak(text)  # emits SPEECH_PLAYBACK_FINISHED when playback ends
        else:
            # Nothing to play, but the turn is still complete — tell the
            # conversation loop it's safe to listen again.
            self.event_bus.publish(EventType.SPEECH_PLAYBACK_FINISHED, {})

    def speak(self, text: str):
        """Schedules synthesis + playback without blocking the GUI thread."""
        self.application.run_async(self._synthesize_and_play(text))

    async def _synthesize_and_play(self, text: str):
        import asyncio
        try:
            clip = await self.provider.synthesize(text)
            if clip:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._play, clip, text)  # blocking, off-loop
        finally:
            # Always signal completion — even on synthesis failure — so a
            # hands-free conversation never stalls waiting for audio.
            self.event_bus.publish(EventType.SPEECH_PLAYBACK_FINISHED, {})

    def _play(self, clip: AudioClip, text: str = ""):
        try:
            import pyaudio
        except ImportError:
            logger.warning("PyAudio missing; cannot play TTS audio.")
            return

        pcm = self._apply_volume(clip.pcm)
        duration_sec = len(clip.pcm) / float(
            clip.sample_rate * clip.channels * clip.sample_width)

        # Barge-in: interrupt whatever is currently speaking, then take the lock.
        self._stop_flag.set()
        with self._play_lock:
            self._stop_flag.clear()
            if self._pa is None:
                self._pa = pyaudio.PyAudio()
            stream = None
            try:
                stream = self._pa.open(
                    format=self._pa.get_format_from_width(clip.sample_width),
                    channels=clip.channels, rate=clip.sample_rate, output=True)

                # Audio starts NOW — hand the bubble the text and the exact
                # duration so it can type in lockstep with the voice.
                self.event_bus.publish(EventType.SPEECH_PLAYBACK_STARTED,
                                       {"text": text, "duration_sec": duration_sec})

                bytes_per_chunk = _PLAY_CHUNK * clip.channels * clip.sample_width
                for i in range(0, len(pcm), bytes_per_chunk):
                    if self._stop_flag.is_set():
                        break
                    stream.write(pcm[i:i + bytes_per_chunk])
            except Exception as e:
                logger.error(f"TTS playback failed: {e}")
            finally:
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass

    @staticmethod
    def _apply_volume(pcm: bytes) -> bytes:
        """Scales int16 PCM by Config.PET_VOLUME. No-ops without numpy or at 1.0."""
        vol = max(0.0, min(1.0, Config.PET_VOLUME))
        if vol >= 0.999 or not pcm:
            return pcm
        try:
            import numpy as np
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) * vol
            return samples.astype(np.int16).tobytes()
        except Exception:
            return pcm  # numpy absent or odd buffer length: play at full volume

    def cleanup(self):
        """Stops playback and releases the audio device."""
        self._stop_flag.set()
        with self._play_lock:
            if self._pa is not None:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None
