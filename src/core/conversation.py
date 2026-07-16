"""Hands-free conversation mode.

Trigger once (Ctrl+Space) and just talk. This thread owns the mic for the
duration of a session and drives a turn-taking loop:

    listen -> (VAD detects you stopped) -> transcribe+reply+speak -> listen ...

Voice-activity detection uses Silero VAD (bundled with openWakeWord, already on
disk), so no new dependency. Each turn:

  1. Wait for speech onset (end the session if nobody speaks within the idle
     timeout).
  2. Record until CONVERSATION_ENDPOINT_MS of trailing silence (auto-endpoint).
  3. Publish VOICE_RECORD_STOPPED — the exact event the orchestrator already
     consumes — then PAUSE the mic and wait for SPEECH_PLAYBACK_FINISHED so we
     never record the pet's own TTS coming back through the speakers (echo).
  4. Resume listening for the next turn.

The session ends on: idle timeout, a second hotkey press (stop_session), or app
shutdown. Everything degrades gracefully — missing deps / mic / VAD just logs
and disables the feature, leaving the rest of the app untouched.
"""
import os
import time
import wave
import uuid
import tempfile
import threading
from collections import deque
from typing import Any

from PyQt6.QtCore import QThread
from src.config import Config
from src.constants import PetState
from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger("Conversation")

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280   # 80 ms — the frame size Silero VAD accepts here
FRAME_MS = 80
CHANNELS = 1
SAMPLE_WIDTH = 2       # int16
PRE_ROLL_FRAMES = 3    # ~240 ms kept before speech onset so first word isn't clipped
RESPONSE_TIMEOUT_SEC = 30.0  # give up waiting on a stuck reply and listen again


class ConversationManager(QThread):
    def __init__(self, event_bus: EventBus):
        super().__init__()
        self.event_bus = event_bus
        self._running = True
        self._session_requested = threading.Event()
        self._end_session = threading.Event()
        self._turn_done = threading.Event()
        self._active = False
        # Cleared once we know conversation mode cannot run here (voice extra
        # missing / VAD won't init), so the hotkey can fall back to push-to-talk
        # instead of silently doing nothing.
        self._usable = True

        # Handles to optional, untyped deps, imported lazily in run() so the app
        # still starts without the [voice] extra. Typed Any deliberately: they
        # are None until run() populates them, and none of these libraries ship
        # type information anyway.
        self._pa: Any = None
        self._stream: Any = None
        self._vad: Any = None
        self._np: Any = None
        self._pyaudio: Any = None

        # The pet finishing its reply (spoken or not), or an error, unblocks the
        # next listening turn. Both are thread-safe Event.set() calls.
        for et in (EventType.SPEECH_PLAYBACK_FINISHED, EventType.LLM_ERROR_OCCURRED):
            self.event_bus.subscribe(et, self._on_turn_signal, executor="gui")

    @property
    def active(self) -> bool:
        return self._active

    @property
    def usable(self) -> bool:
        """False once conversation mode is known to be unavailable here. Callers
        must fall back to push-to-talk rather than leaving a dead hotkey."""
        return self._usable

    def _on_turn_signal(self, event_type: str, data: dict):
        self._turn_done.set()

    # --- Session control (called from the GUI thread) -----------------------

    def toggle_session(self):
        if self._active:
            self.stop_session()
        else:
            self.start_session()

    def start_session(self):
        self._end_session.clear()
        self._session_requested.set()

    def stop_session(self):
        self._end_session.set()

    def stop(self):
        """App shutdown: end any session and exit the thread."""
        self._running = False
        self._end_session.set()
        self._session_requested.set()  # unblock the idle wait
        self.wait(3000)

    # --- Thread body --------------------------------------------------------

    def run(self):
        try:
            import numpy as np
            import pyaudio
            from openwakeword.vad import VAD
        except ImportError:
            self._usable = False
            logger.warning("Conversation mode needs the voice extra "
                           "(pip install -e .[voice]); falling back to "
                           "press-to-start / press-to-stop push-to-talk.")
            return
        self._np = np
        self._pyaudio = pyaudio
        try:
            self._vad = VAD()
        except Exception as e:
            self._usable = False
            logger.error(f"Could not initialise VAD: {e}. "
                         "Falling back to push-to-talk.")
            return

        logger.info("Conversation mode ready (press the talk hotkey to start).")
        while self._running:
            self._session_requested.wait()
            self._session_requested.clear()
            if not self._running:
                break
            try:
                self._run_session()
            except Exception as e:
                logger.error(f"Conversation session error: {e}")
            finally:
                self._teardown_stream()
                self._active = False

    def _run_session(self):
        self._pa = self._pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=self._pyaudio.paInt16, channels=CHANNELS, rate=SAMPLE_RATE,
                input=True, frames_per_buffer=FRAME_SAMPLES)
        except Exception as e:
            logger.error(f"Conversation could not open microphone: {e}")
            self.event_bus.publish(EventType.SPEECH_REQUESTED,
                                   {"text": "I couldn't reach the microphone!"})
            return

        self._active = True
        self._vad.reset_states()
        logger.info("Conversation started.")
        self.event_bus.publish(EventType.CONVERSATION_STARTED, {})
        self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.LISTEN})

        while self._active and not self._end_session.is_set() and self._running:
            frames = self._capture_utterance()
            if frames is None:
                break              # idle timeout, mic error, or stop requested
            if not frames:
                continue           # too-short blip: keep listening

            # Pause the mic while the pet answers, so its TTS can't feed back in.
            self._pause_stream()
            self._turn_done.clear()
            wav_path = self._save_wav(frames)
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.THINK})
            self.event_bus.publish(EventType.VOICE_RECORD_STOPPED, {"wav_path": wav_path})

            # Wait for the full round-trip: transcribe -> LLM -> TTS playback.
            self._turn_done.wait(timeout=RESPONSE_TIMEOUT_SEC)
            if self._end_session.is_set() or not self._running:
                break

            # Resume: fresh stream, drop any buffered speaker tail, reset VAD.
            self._resume_stream()
            self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.LISTEN})

        logger.info("Conversation ended.")
        self.event_bus.publish(EventType.CONVERSATION_ENDED, {})
        self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})

    def _capture_utterance(self):
        """Returns recorded frames for one utterance, [] for a too-short blip,
        or None to end the session (idle timeout / mic error / stop)."""
        np = self._np
        pre_roll = deque(maxlen=PRE_ROLL_FRAMES)
        frames = []
        speech_started = False
        trailing_silence = 0
        voiced_frames = 0

        endpoint_frames = max(1, Config.CONVERSATION_ENDPOINT_MS // FRAME_MS)
        max_frames = int(Config.CONVERSATION_MAX_UTTERANCE_SEC * SAMPLE_RATE / FRAME_SAMPLES)
        threshold = Config.CONVERSATION_VAD_THRESHOLD
        idle_deadline = time.time() + Config.CONVERSATION_IDLE_TIMEOUT_SEC

        while self._active and not self._end_session.is_set() and self._running:
            try:
                data = self._stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            except Exception as e:
                logger.error(f"Conversation mic read error: {e}")
                return None

            prob = float(self._vad.predict(np.frombuffer(data, dtype=np.int16)))
            is_speech = prob >= threshold

            if not speech_started:
                pre_roll.append(data)
                if is_speech:
                    speech_started = True
                    frames.extend(pre_roll)
                    voiced_frames = 1
                elif time.time() > idle_deadline:
                    return None  # nobody spoke — end the session
            else:
                frames.append(data)
                if is_speech:
                    voiced_frames += 1
                    trailing_silence = 0
                else:
                    trailing_silence += 1
                    if trailing_silence >= endpoint_frames:
                        break
                if len(frames) >= max_frames:
                    break

        if not speech_started or voiced_frames * FRAME_MS < Config.CONVERSATION_MIN_SPEECH_MS:
            return []  # discard a cough/click, keep the session alive
        return frames

    # --- Stream helpers -----------------------------------------------------

    def _pause_stream(self):
        try:
            self._stream.stop_stream()
        except Exception:
            pass

    def _resume_stream(self):
        try:
            self._stream.start_stream()
        except Exception:
            pass
        self._vad.reset_states()
        # Discard ~200 ms so the tail of the spoken reply can't seed the next turn.
        deadline = time.time() + 0.2
        while time.time() < deadline:
            try:
                self._stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            except Exception:
                break

    def _teardown_stream(self):
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

    def _save_wav(self, frames) -> str:
        if not frames:
            return ""
        path = os.path.join(
            tempfile.gettempdir(),
            f"desk_pet_conv_{os.getpid()}_{uuid.uuid4().hex[:12]}.wav")
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(frames))
            return path
        except Exception as e:
            logger.error(f"Failed to save conversation utterance: {e}")
            return ""
