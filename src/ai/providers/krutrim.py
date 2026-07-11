import json
import httpx
from typing import AsyncGenerator, Dict, Any
from src.ai.providers.base import LLMProvider
from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("KrutrimProvider")

class KrutrimProvider(LLMProvider):
    """
    HTTP client for the Krutrim AI LLM API.
    Conforms to OpenAI-compatible endpoint structures.
    """
    def __init__(self):
        self.api_key = Config.KRUTRIM_API_KEY
        self.model = Config.KRUTRIM_MODEL
        self.api_url = "https://cloud.olakrutrim.com/v1/chat/completions"

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _build_payload(self, prompt: str, context: Dict[str, Any], stream: bool = False) -> dict:
        system_instruction = context.get("system_prompt", "You are a desktop pet assistant.")
        
        messages = [
            {"role": "system", "content": system_instruction}
        ]
        
        # Inject short term memory (chronological order) if available
        history = context.get("conversation_history", [])
        for msg in history:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("message", "")
            })
            
        # Append current user prompt
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.7,
            "stream": stream
        }
        return payload

    async def generate(self, prompt: str, context: Dict[str, Any]) -> str:
        if not self.api_key or "your_" in self.api_key:
            return "Krutrim API key is unconfigured. Please configure it in .env!"

        headers = self._get_headers()
        payload = self._build_payload(prompt, context, stream=False)
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Krutrim API generation failed: {e}")
            return "I'm having trouble thinking right now."

    async def stream(self, prompt: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        if not self.api_key or "your_" in self.api_key:
            yield "Krutrim API key is unconfigured."
            return

        headers = self._get_headers()
        payload = self._build_payload(prompt, context, stream=True)
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with client.stream("POST", self.api_url, headers=headers, json=payload) as response:
                    if response.status_code != 200:
                        raise RuntimeError(f"Krutrim API returned status {response.status_code}")

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                            
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                            
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            chunk = delta.get("content", "")
                            if chunk:
                                yield chunk
                        except Exception:
                            continue
        except Exception as e:
            logger.error(f"Krutrim API streaming failed: {e}")
            raise RuntimeError("Krutrim streaming request failed") from e

    def supports_vision(self) -> bool:
        # Standard Krutrim Qwen API might not support vision unless specifically configured.
        return False

    async def health(self) -> bool:
        if not self.api_key or "your_" in self.api_key:
            return False
        # Small check or ping
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                # Ping models list or similar API health check
                url = "https://api.krutrim.com/v1/models"
                res = await client.get(url, headers=self._get_headers())
                return res.status_code == 200
        except Exception:
            return False
