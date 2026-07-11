import json
import httpx
from typing import AsyncGenerator, Dict, Any
from src.ai.providers.base import LLMProvider
from src.config import Config
from src.utils.logger import get_logger

logger = get_logger("GeminiProvider")

class GeminiProvider(LLMProvider):
    """
    HTTP REST client for Google's Gemini 2.5 Flash API.
    Designed for low overhead without loading the bulky Google Cloud SDK.
    """
    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.model = Config.GEMINI_MODEL
        
    def _get_url(self, stream: bool = False) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:{action}?key={self.api_key}"

    def _build_payload(self, prompt: str, context: Dict[str, Any]) -> dict:
        # Extract system prompt from context or use default
        system_instruction = context.get("system_prompt", "You are a desktop pet assistant.")
        
        # Build contents structure
        parts = [{"text": prompt}]
        
        # Check for multimodal image attachment (Vision subsystem)
        base64_image = context.get("screenshot_base64")
        image_bytes = context.get("screenshot_bytes")
        if image_bytes and not base64_image:
            import base64
            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            
        if base64_image:
            parts.append({
                "inlineData": {
                    "mimeType": "image/png",
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
        if not self.api_key or "your_" in self.api_key:
            return "Gemini API key is unconfigured. Please check your .env settings!"

        url = self._get_url(stream=False)
        payload = self._build_payload(prompt, context)
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                
                # Extract response text
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
        except Exception as e:
            logger.error(f"Gemini API generate content failed: {e}")
            return f"Oops! I couldn't reach the stars right now. (Error: {str(e)})"

    async def stream(self, prompt: str, context: Dict[str, Any]) -> AsyncGenerator[str, None]:
        """Streams text chunks frame-by-frame for typewriter styling."""
        if not self.api_key or "your_" in self.api_key:
            yield "Gemini API key is unconfigured. Please configure it in .env!"
            return

        url = self._get_url(stream=True)
        payload = self._build_payload(prompt, context)
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        yield f"API Error: Received status code {response.status_code}"
                        return
                        
                    buffer = ""
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        
                        # Strip Server-Sent Events headers if present (Gemini streaming returns a JSON array or chunks)
                        buffer += line
                        try:
                            clean_buf = buffer.strip()
                            # Clean leading/trailing brackets or commas from JSON stream segment
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
                                                yield text_chunk
                        except json.JSONDecodeError:
                            # Incomplete JSON frame, wait for more data
                            continue
                            
        except Exception as e:
            logger.error(f"Gemini API streaming failed: {e}")
            yield f" (Thinking connection interrupted: {str(e)})"

    def supports_vision(self) -> bool:
        return True

    async def health(self) -> bool:
        """Pings Gemini backend to assert connection status."""
        if not self.api_key or "your_" in self.api_key:
            return False
        # Minimal mock check or small call
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={self.api_key}"
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url)
                return res.status_code == 200
        except Exception:
            return False
