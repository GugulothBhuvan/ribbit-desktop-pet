"""Sarvam AI (Bulbul) text-to-speech client.

Chosen over Deepgram Aura for this pet because Sarvam ships genuine Indian-English
voices, which match the persona's accent instead of only its vocabulary.

Sarvam returns base64-encoded WAV; we decode and unwrap it to raw PCM so the
player can stream it straight to PyAudio. The clip carries its own sample rate
(see tts_base.AudioClip) because Sarvam's rate is configurable.

Returns EMPTY_CLIP on any failure so a TTS problem never breaks a reply.
"""
import io
import base64
import wave

import httpx
from src.config import Config
from src.ai.providers.tts_base import AudioClip, EMPTY_CLIP
from src.utils.logger import get_logger

logger = get_logger("SarvamTTS")

# Bulbul caps a single request; our replies are clamped well under this.
MAX_TEXT_CHARS = 500


class SarvamTTSProvider:
    def __init__(self):
        self.api_key = Config.SARVAM_API_KEY
        self.api_url = "https://api.sarvam.ai/text-to-speech"

    def _configured(self) -> bool:
        return bool(self.api_key) and "your_" not in self.api_key

    async def synthesize(self, text: str) -> AudioClip:
        text = (text or "").strip()
        if not text:
            return EMPTY_CLIP
        if not self._configured():
            logger.warning("SARVAM_API_KEY unconfigured; skipping TTS. "
                           "Set it in .env, or set TTS_PROVIDER=deepgram.")
            return EMPTY_CLIP

        payload = {
            "inputs": [text[:MAX_TEXT_CHARS]],
            "target_language_code": Config.SARVAM_TTS_LANGUAGE,
            "speaker": Config.SARVAM_TTS_SPEAKER,
            "model": Config.SARVAM_TTS_MODEL,
            "speech_sample_rate": Config.SARVAM_TTS_SAMPLE_RATE,
            "enable_preprocessing": True,
        }
        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(self.api_url, headers=headers, json=payload)
                if res.status_code >= 400:
                    # Surface the API's own message — it names the bad field.
                    logger.error(f"Sarvam TTS {res.status_code}: {res.text[:400]}")
                    return EMPTY_CLIP
                audios = res.json().get("audios") or []
                if not audios:
                    logger.error("Sarvam TTS returned no audio.")
                    return EMPTY_CLIP
                return self._wav_to_clip(base64.b64decode(audios[0]))
        except Exception as e:
            logger.error(f"Sarvam TTS request failed: {e}")
            return EMPTY_CLIP

    @staticmethod
    def _wav_to_clip(wav_bytes: bytes) -> AudioClip:
        """Unwraps a WAV container into raw PCM + its real format."""
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                return AudioClip(
                    pcm=wf.readframes(wf.getnframes()),
                    sample_rate=wf.getframerate(),
                    channels=wf.getnchannels(),
                    sample_width=wf.getsampwidth(),
                )
        except Exception as e:
            logger.error(f"Could not decode Sarvam WAV: {e}")
            return EMPTY_CLIP
