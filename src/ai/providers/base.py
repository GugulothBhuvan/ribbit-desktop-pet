from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any

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
