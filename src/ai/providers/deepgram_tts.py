"""Deepgram Aura text-to-speech client.

Reuses DEEPGRAM_API_KEY (same account as speech-to-text). Requests RAW PCM
(linear16, mono) rather than MP3 so the audio can be piped straight into
PyAudio without a decoder — see src/core/tts.py.

Returns b"" on any failure (missing key, network error, empty text) so the
caller can simply skip playback; TTS is never allowed to break a reply.
"""
import httpx
from src.config import Config
from src.ai.providers.tts_base import AudioClip, EMPTY_CLIP
from src.utils.logger import get_logger

logger = get_logger("DeepgramTTS")

# Raw PCM output format we request from Aura.
TTS_SAMPLE_RATE = 24000
TTS_CHANNELS = 1
TTS_SAMPLE_WIDTH = 2  # int16


class DeepgramTTSProvider:
    def __init__(self):
        self.api_key = Config.DEEPGRAM_API_KEY
        self.base_url = "https://api.deepgram.com/v1/speak"

    def _configured(self) -> bool:
        return bool(self.api_key) and "your_" not in self.api_key

    async def synthesize(self, text: str) -> AudioClip:
        """Synthesizes `text` to raw linear16 PCM. Returns EMPTY_CLIP on failure."""
        text = (text or "").strip()
        if not text:
            return EMPTY_CLIP
        if not self._configured():
            logger.warning("Deepgram API key unconfigured; skipping TTS.")
            return EMPTY_CLIP

        params = {
            "model": Config.TTS_VOICE,
            "encoding": "linear16",
            "sample_rate": str(TTS_SAMPLE_RATE),
            "container": "none",
        }
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(self.base_url, params=params,
                                        headers=headers, json={"text": text})
                res.raise_for_status()
                return AudioClip(res.content, TTS_SAMPLE_RATE,
                                 TTS_CHANNELS, TTS_SAMPLE_WIDTH)
        except Exception as e:
            logger.error(f"Deepgram TTS request failed: {e}")
            return EMPTY_CLIP
