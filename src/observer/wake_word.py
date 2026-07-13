"""Local wake-word listener (openWakeWord).

Opt-in (Config.WAKE_WORD_ENABLED). When active it OWNS the microphone: a single
continuous 16 kHz stream is fed to an on-device openWakeWord model. On a
detection (or a manual hotkey trigger) it records the following utterance for a
fixed window, writes a temp WAV, and publishes VOICE_RECORD_STOPPED — the exact
event the AI orchestrator already consumes for push-to-talk. Because this thread
is the sole mic owner, there is no contention with AudioRecorder (which is only
used when the wake word is disabled).

Everything degrades gracefully: if the dependency is missing, the model can't
load, or the mic can't open, it logs a clear reason and disables itself, leaving
the Ctrl+Space hotkey as the working fallback.
"""
import os
import time
import wave
import uuid
import tempfile
import threading

from PyQt6.QtCore import QThread
from src.config import Config
from src.constants import PetState
from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger("WakeWord")

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280   # 80 ms — openWakeWord's expected chunk size
CHANNELS = 1
SAMPLE_WIDTH = 2       # int16


class WakeWordListener(QThread):
    def __init__(self, event_bus: EventBus):
        super().__init__()
        self.event_bus = event_bus
        self._running = True
        self._manual_trigger = threading.Event()
        self._capturing = False
        self._pa = None
        self._stream = None
        self._model = None

    @property
    def active(self) -> bool:
        """True once the mic stream and model are up and listening."""
        return self._stream is not None and self._model is not None

    def trigger_manual(self):
        """Capture an utterance without saying the phrase (hotkey path)."""
        self._manual_trigger.set()

    def run(self):
        if not Config.WAKE_WORD_ENABLED:
            logger.info("Wake word disabled (set WAKE_WORD_ENABLED=1 to enable). Using hotkey only.")
            return

        try:
            import numpy as np
            import pyaudio
            import openwakeword
            from openwakeword.model import Model
        except ImportError:
            logger.warning("Wake word enabled but dependencies missing. "
                           "Run: pip install openwakeword numpy. Hotkey still works.")
            return

        try:
            openwakeword.utils.download_models()  # no-op if already cached
            self._model = Model(wakeword_models=[Config.WAKE_WORD_MODEL])
        except Exception as e:
            logger.error(f"Could not load wake-word model '{Config.WAKE_WORD_MODEL}': {e}. Hotkey still works.")
            return

        try:
            self._pa = pyaudio.PyAudio()
            self._stream = self._pa.open(
                format=pyaudio.paInt16, channels=CHANNELS, rate=SAMPLE_RATE,
                input=True, frames_per_buffer=FRAME_SAMPLES)
        except Exception as e:
            logger.error(f"Wake word could not open microphone: {e}. Hotkey still works.")
            self._model = None
            return

        logger.info(f"Wake word active: say the '{Config.WAKE_WORD_MODEL}' phrase to talk.")
        try:
            while self._running:
                try:
                    data = self._stream.read(FRAME_SAMPLES, exception_on_overflow=False)
                except Exception as e:
                    logger.error(f"Wake word mic read error: {e}")
                    break

                if self._manual_trigger.is_set():
                    self._manual_trigger.clear()
                    self._capture_utterance()
                    continue

                audio = np.frombuffer(data, dtype=np.int16)
                scores = self._model.predict(audio)
                if scores.get(Config.WAKE_WORD_MODEL, 0.0) >= Config.WAKE_WORD_THRESHOLD:
                    logger.info("Wake word detected.")
                    self._capture_utterance()
        finally:
            self._teardown()

    def _capture_utterance(self):
        """Record the next few seconds on the already-open stream, save, emit."""
        self._capturing = True
        self.event_bus.publish(EventType.VOICE_RECORD_STARTED, {})
        self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.LISTEN})

        frames = []
        deadline = time.time() + Config.WAKE_WORD_RECORD_SEC
        while time.time() < deadline and self._running:
            try:
                frames.append(self._stream.read(FRAME_SAMPLES, exception_on_overflow=False))
            except Exception:
                break

        wav_path = self._save_wav(frames)
        # Reset the model so the tail of this utterance can't re-trigger
        try:
            self._model.reset()
        except Exception:
            pass
        self._capturing = False
        self.event_bus.publish(EventType.VOICE_RECORD_STOPPED, {"wav_path": wav_path})

    def _save_wav(self, frames) -> str:
        if not frames:
            return ""
        path = os.path.join(tempfile.gettempdir(), f"desk_pet_wake_{os.getpid()}_{uuid.uuid4().hex[:12]}.wav")
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(frames))
            return path
        except Exception as e:
            logger.error(f"Failed to save wake-word utterance: {e}")
            return ""

    def _teardown(self):
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        logger.info("Wake word listener stopped.")

    def stop(self):
        self._running = False
        self.wait(3000)
