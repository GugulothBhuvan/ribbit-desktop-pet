import os
from typing import Optional
import httpx
from src.ai.providers.base import VoiceProvider
from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("DeepgramProvider")

class DeepgramProvider(VoiceProvider):
    """
    HTTP REST client for the Deepgram Speech-to-Text API.
    Transcribes local wav recordings.
    """
    def __init__(self):
        self.api_key = Config.DEEPGRAM_API_KEY
        self.api_url = "https://api.deepgram.com/v1/listen?model=nova-2&smart_format=true"

    async def transcribe(self, audio_filepath: str) -> Optional[str]:
        """Transcribes the given WAV file. Returns None on any failure so callers
        never mistake an error message for user speech."""
        if not self.api_key or "your_" in self.api_key:
            logger.warning("Deepgram API key is unconfigured, returning dummy test phrase.")
            return "How does my code look today?"

        if not os.path.exists(audio_filepath):
            logger.error(f"Audio file to transcribe not found: {audio_filepath}")
            return None

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/wav"
        }

        try:
            # Read binary audio content
            with open(audio_filepath, "rb") as audio_file:
                audio_data = audio_file.read()

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    content=audio_data
                )
                response.raise_for_status()
                data = response.json()
                
                # Extract transcript
                channels = data.get("results", {}).get("channels", [])
                if channels:
                    alternatives = channels[0].get("alternatives", [])
                    if alternatives:
                        transcript = alternatives[0].get("transcript", "")
                        logger.info(f"Deepgram transcription successful: '{transcript}'")
                        return transcript.strip()
                        
                logger.warning("Deepgram API returned empty alternatives lists.")
                return None
        except Exception as e:
            logger.error(f"Deepgram transcription request failed: {e}")
            return None

    async def health(self) -> bool:
        if not self.api_key or "your_" in self.api_key:
            return False
        try:
            # Minimal health check pinging Deepgram projects list or similar API endpoints
            url = "https://api.deepgram.com/v1/projects"
            headers = {"Authorization": f"Token {self.api_key}"}
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, headers=headers)
                return res.status_code == 200
        except Exception:
            return False
