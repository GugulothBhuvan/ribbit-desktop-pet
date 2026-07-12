import json
import httpx
from typing import AsyncGenerator, Dict, Any, Optional
from src.ai.providers.base import (
    LLMProvider, MAX_ATTEMPTS, is_retryable_status, backoff_sleep
)
from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("GeminiProvider")

FALLBACK_ERROR_TEXT = "I'm having trouble thinking right now."


class GeminiProvider(LLMProvider):
    """
    HTTP REST client for Google's Gemini API.
    Designed for low overhead without loading the bulky Google Cloud SDK.

    The API key is sent via the `x-goog-api-key` header — never as a URL query
    parameter — so exception messages and logs can never contain the secret.
    Uses one pooled AsyncClient and retry with backoff for transient failures.
    """
    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def model(self) -> str:
        return Config.GEMINI_MODEL

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def aclose(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _get_url(self, stream: bool = False) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:{action}"

    def _get_headers(self) -> dict:
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json"
        }

    def _is_configured(self) -> bool:
        return bool(self.api_key) and "your_" not in self.api_key

    def _build_payload(self, prompt: str, context: Dict[str, Any]) -> dict:
        # Extract system prompt from context or use default
        system_instruction = context.get("system_prompt", "You are a desktop pet assistant.")

        # Build contents structure
        parts = [{"text": prompt}]

        # Check for multimodal image attachment (Vision subsystem, JPEG)
        base64_image = context.get("screenshot_base64")
        image_bytes = context.get("screenshot_bytes")
        if image_bytes and not base64_image:
            import base64
            base64_image = base64.b64encode(image_bytes).decode("utf-8")

        if base64_image:
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": base64_image
                }
            })

        payload = {
            "contents": [{
                "parts": parts
            }],
            "systemInstruction": {
                "parts": [{"text": system_instruction}]
            },
            "generationConfig": {
                "maxOutputTokens": 150,  # Strict cap to fit speech bubbles
                "temperature": 0.7
            }
        }
        return payload

    async def generate(self, prompt: str, context: Dict[str, Any]) -> str:
        if not self._is_configured():
            return "Gemini API key is unconfigured. Please check your .env settings!"

        url = self._get_url(stream=False)
        payload = self._build_payload(prompt, context)

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await self._get_client().post(url, headers=self._get_headers(), json=payload)
                if is_retryable_status(response.status_code) and attempt < MAX_ATTEMPTS - 1:
                    logger.warning(f"Gemini status {response.status_code}; retrying (attempt {attempt + 1})")
                    await backoff_sleep(attempt)
                    continue
                response.raise_for_status()
                data = response.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
            except (httpx.TimeoutException, httpx.TransportError) as e:
                if attempt < MAX_ATTEMPTS - 1:
                    logger.warning(f"Gemini transport error ({e}); retrying (attempt {attempt + 1})")
                    await backoff_sleep(attempt)
                    continue
                logger.error(f"Gemini API generate failed after retries: {e}")
                return FALLBACK_ERROR_TEXT
            except Exception as e:
                logger.error(f"Gemini API generate content failed: {e}")
                return FALLBACK_ERROR_TEXT
        return FALLBACK_ERROR_TEXT

    async def stream(self, prompt: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Streams text chunks frame-by-frame for typewriter styling.

        Raises RuntimeError on transport/API failure so the caller's error
        path (LLM_ERROR_OCCURRED) handles user-facing messaging."""
        if not self._is_configured():
            yield "Gemini API key is unconfigured. Please configure it in .env!"
            return

        url = self._get_url(stream=True)
        payload = self._build_payload(prompt, context)

        for attempt in range(MAX_ATTEMPTS):
            yielded_any = False
            try:
                async with self._get_client().stream(
                        "POST", url, headers=self._get_headers(), json=payload) as response:
                    if is_retryable_status(response.status_code) and attempt < MAX_ATTEMPTS - 1:
                        logger.warning(f"Gemini status {response.status_code}; retrying stream (attempt {attempt + 1})")
                        await backoff_sleep(attempt)
                        continue
                    if response.status_code != 200:
                        raise RuntimeError(f"Gemini API returned status {response.status_code}")

                    buffer = ""
                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        # Gemini streaming returns a JSON array in fragments
                        buffer += line
                        try:
                            clean_buf = buffer.strip()
                            if clean_buf.startswith("["):
                                clean_buf = clean_buf[1:].strip()
                            if clean_buf.endswith("]"):
                                clean_buf = clean_buf[:-1].strip()
                            if clean_buf.startswith(","):
                                clean_buf = clean_buf[1:].strip()
                            if clean_buf.endswith(","):
                                clean_buf = clean_buf[:-1].strip()

                            data = json.loads(clean_buf)
                            buffer = ""  # Reset buffer if successfully parsed

                            items = data if isinstance(data, list) else [data]
                            for item in items:
                                if isinstance(item, dict) and "candidates" in item:
                                    candidates = item["candidates"]
                                    if candidates and isinstance(candidates, list) and "content" in candidates[0]:
                                        content = candidates[0]["content"]
                                        if "parts" in content and content["parts"]:
                                            text_chunk = content["parts"][0].get("text", "")
                                            if text_chunk:
                                                yielded_any = True
                                                yield text_chunk
                        except json.JSONDecodeError:
                            # Incomplete JSON frame, wait for more data
                            continue
                    return
            except (httpx.TimeoutException, httpx.TransportError) as e:
                # Never retry mid-stream: the user already saw partial text
                if yielded_any or attempt >= MAX_ATTEMPTS - 1:
                    logger.error(f"Gemini API streaming failed: {e}")
                    raise RuntimeError("Gemini streaming request failed") from e
                logger.warning(f"Gemini transport error before first chunk ({e}); retrying (attempt {attempt + 1})")
                await backoff_sleep(attempt)

    def supports_vision(self) -> bool:
        return True

    async def health(self) -> bool:
        """Pings Gemini backend to assert connection status."""
        if not self._is_configured():
            return False
        try:
            res = await self._get_client().get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers=self._get_headers())
            return res.status_code == 200
        except Exception:
            return False
