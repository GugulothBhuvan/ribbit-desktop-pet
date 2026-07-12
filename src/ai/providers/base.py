import random
import asyncio
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any

# Retry policy (plan 5.2): retry timeouts/connection errors and retryable
# HTTP statuses with exponential backoff + jitter; never retry other 4xx.
MAX_ATTEMPTS = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_STATUS


async def backoff_sleep(attempt: int):
    """Exponential backoff with jitter: ~0.5s, ~1s between attempts."""
    await asyncio.sleep((2 ** attempt) * 0.5 + random.uniform(0.0, 0.3))

class LLMProvider(ABC):
    """Abstract interface defining the execution protocol for LLM endpoints."""
    
    @abstractmethod
    async def generate(self, prompt: str, context: Dict[str, Any]) -> str:
        """Sends a standard non-streaming prompt request. Returns the complete text."""
        pass

    @abstractmethod
    async def stream(self, prompt: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Streams response tokens sequentially for live typewriter printing."""
        pass

    @abstractmethod
    def supports_vision(self) -> bool:
        """Indicates if the LLM provider accepts image inputs (multimodal processing)."""
        pass

    @abstractmethod
    async def health(self) -> bool:
        """Performs a quick API ping. Returns True if operational, False otherwise."""
        pass

class VoiceProvider(ABC):
    """Abstract interface defining transcription service interactions."""
    
    @abstractmethod
    async def transcribe(self, audio_filepath: str) -> str:
        """Submits local audio file to STT endpoint. Returns raw text transcript."""
        pass

    @abstractmethod
    async def health(self) -> bool:
        """Validates STT endpoint connectivity and server state."""
        pass
