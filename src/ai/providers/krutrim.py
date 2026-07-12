import json
import base64
import httpx
from typing import AsyncGenerator, Dict, Any, Optional
from src.ai.providers.base import (
    LLMProvider, MAX_ATTEMPTS, is_retryable_status, backoff_sleep
)
from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("KrutrimProvider")

FALLBACK_ERROR_TEXT = "I'm having trouble thinking right now."

# Model families on Krutrim that accept image input (verified via /v1/models
# input_modalities). gpt-oss models are text-only.
VISION_MODEL_PREFIXES = ("gemma-4", "Qwen3")


class KrutrimProvider(LLMProvider):
    """
    HTTP client for the Krutrim AI LLM API (OpenAI-compatible endpoints).

    Uses one pooled AsyncClient (bound to the persistent worker loop) and a
    retry policy with exponential backoff for transient failures. Vision
    queries attach the screenshot as an OpenAI-style image_url content part.
    """
    def __init__(self):
        self.api_key = Config.KRUTRIM_API_KEY
        self.api_url = "https://cloud.olakrutrim.com/v1/chat/completions"
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def model(self) -> str:
        # Resolved per-request so the context-menu model switch applies live
        return Config.KRUTRIM_MODEL

    def _get_client(self) -> httpx.AsyncClient:
        """Pooled client. All provider calls run on the one persistent worker
        loop, so a single client (with its connection pool) is safe."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _is_configured(self) -> bool:
        return bool(self.api_key) and "your_" not in self.api_key

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

        # Current user turn — multimodal when a screenshot is attached
        image_bytes = context.get("screenshot_bytes")
        if image_bytes and self.supports_vision():
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            })
        else:
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
        if not self._is_configured():
            return "Krutrim API key is unconfigured. Please configure it in .env!"

        payload = self._build_payload(prompt, context, stream=False)

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await self._get_client().post(
                    self.api_url, headers=self._get_headers(), json=payload)
                if is_retryable_status(response.status_code) and attempt < MAX_ATTEMPTS - 1:
                    logger.warning(f"Krutrim status {response.status_code}; retrying (attempt {attempt + 1})")
                    await backoff_sleep(attempt)
                    continue
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < MAX_ATTEMPTS - 1:
                    logger.warning(f"Krutrim transport error ({e}); retrying (attempt {attempt + 1})")
                    await backoff_sleep(attempt)
                    continue
                logger.error(f"Krutrim API generation failed after retries: {e}")
                return FALLBACK_ERROR_TEXT
            except Exception as e:
                logger.error(f"Krutrim API generation failed: {e}")
                return FALLBACK_ERROR_TEXT
        return FALLBACK_ERROR_TEXT

    async def stream(self, prompt: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        if not self._is_configured():
            yield "Krutrim API key is unconfigured."
            return

        payload = self._build_payload(prompt, context, stream=True)

        for attempt in range(MAX_ATTEMPTS):
            yielded_any = False
            try:
                async with self._get_client().stream(
                        "POST", self.api_url, headers=self._get_headers(), json=payload) as response:
                    if is_retryable_status(response.status_code) and attempt < MAX_ATTEMPTS - 1:
                        logger.warning(f"Krutrim status {response.status_code}; retrying stream (attempt {attempt + 1})")
                        await backoff_sleep(attempt)
                        continue
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
                                yielded_any = True
                                yield chunk
                        except Exception:
                            continue
                    return
            except (httpx.TimeoutException, httpx.TransportError) as e:
                # Never retry mid-stream: the user already saw partial text
                if yielded_any or attempt >= MAX_ATTEMPTS - 1:
                    logger.error(f"Krutrim API streaming failed: {e}")
                    raise RuntimeError("Krutrim streaming request failed") from e
                logger.warning(f"Krutrim transport error before first chunk ({e}); retrying (attempt {attempt + 1})")
                await backoff_sleep(attempt)

    def supports_vision(self) -> bool:
        return self.model.startswith(VISION_MODEL_PREFIXES)

    async def health(self) -> bool:
        if not self._is_configured():
            return False
        # Ping the models list on the same host the chat endpoint uses
        try:
            res = await self._get_client().get(
                "https://cloud.olakrutrim.com/v1/models", headers=self._get_headers())
            return res.status_code == 200
        except Exception:
            return False
