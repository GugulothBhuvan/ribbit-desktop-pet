import os
import re
import asyncio
from typing import Dict, Any, Optional
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QImage
from src.config import Config
from src.constants import MAX_CHARACTERS, MAX_CHARACTERS_CONVERSATION, PetState
from src.event_bus import EventBus, EventType
from src.ai.context_engine import ContextEngine
from src.ai.prompts import build_system_prompt
from src.ai import vision
from src.ai.providers.base import LLMProvider
from src.ai.providers.gemini import GeminiProvider
from src.ai.providers.krutrim import KrutrimProvider
from src.storage.db import Database
from src.storage.repository import ConversationRepository, MemoryRepository
from src.core.application import Application
from src.utils.logger import get_logger

logger = get_logger("AIOrchestrator")


def sanitize_chunk(text: str) -> str:
    """Strips markdown decoration and newlines so bubble text stays clean."""
    text = text.replace("\n", " ").replace("\r", " ")
    text = re.sub(r"[*_`#]+", "", text)
    return text


def clamp_stream_text(accumulated_len: int, chunk: str, limit: int = MAX_CHARACTERS):
    """Enforces the PRD 100-150 char cap AT THE STREAM LAYER (PRD §12.2).

    Returns (text_to_emit, is_final). When the limit is hit mid-chunk the
    text is cut and terminated with an ellipsis; is_final=True tells the
    caller to stop consuming the stream."""
    remaining = limit - accumulated_len
    if remaining <= 0:
        return "", True
    if len(chunk) > remaining:
        return chunk[:remaining].rstrip() + "…", True
    return chunk, False


# Word-boundary patterns for long-term memory extraction. The previous
# substring splits captured garbage from sentences merely containing
# "prefer" (audit m-14).
# Second name word must be capitalized ("Bhuvan Raj" yes, "Bhuvan by the way" no)
_NAME_PATTERN = re.compile(
    r"\bmy name is\s+([A-Za-z][\w'-]*(?:\s+[A-Z][\w'-]*)?)")
_PREF_PATTERN = re.compile(
    r"\bi (?:prefer|code in|use)\s+([^.,!?\n]{2,40})", re.IGNORECASE)


def extract_memory_facts(user_msg: str) -> Dict[str, str]:
    """Extracts durable user facts (name, coding preference) from a message."""
    facts: Dict[str, str] = {}
    # Case-sensitive second word: match against the raw message but find the
    # phrase case-insensitively by normalizing only the trigger
    name_match = _NAME_PATTERN.search(
        re.sub(r"\bmy name is\b", "my name is", user_msg, flags=re.IGNORECASE))
    if name_match:
        facts["user_name"] = name_match.group(1).strip()
    pref_match = _PREF_PATTERN.search(user_msg)
    if pref_match:
        facts["coding_pref"] = pref_match.group(1).strip()
    return facts


class AIOrchestrator(QObject):
    """
    Coordinates context gathering, database history extraction, system prompt
    preparation, LLM streaming, and event propagation.

    Streaming runs as an async task on the persistent worker loop and reports
    progress by publishing events (the bus routes them thread-safely). The
    previous design spawned a QThread per query, whose signal connections were
    fragile across threads and whose overlapping instances crashed Qt.
    """

    SUBSCRIBED_EVENTS = [
        EventType.SCREEN_CAPTURED,
        EventType.VOICE_RECORD_STOPPED,
        EventType.CHAT_QUERY_REQUESTED,
    ]

    def __init__(self, event_bus: EventBus, context_engine: ContextEngine,
                 db: Database, application: Application):
        super().__init__()
        self.event_bus = event_bus
        self.context_engine = context_engine
        self.application = application

        # Instantiate providers
        self.gemini_provider = GeminiProvider()
        self.krutrim_provider = KrutrimProvider()

        # Database & Repositories
        self.conv_repo = ConversationRepository(db)
        self.memory_repo = MemoryRepository(db)

        # Single in-flight query guard (audit M-6 / plan 3.5)
        self._query_in_flight = False

        # Desktop agent: intercepts voice/chat lines that are OS commands
        # (opt-in via Config.AGENT_ENABLED) before they reach the chat LLM.
        from src.agent.agent import DesktopAgent
        self.agent = DesktopAgent()

        for event_type in self.SUBSCRIBED_EVENTS:
            self.event_bus.subscribe(event_type, self.on_event, executor="gui")

    def on_event(self, event_type: str, data: dict):
        """Processes EventBus queries for voice recording releases and captured screens."""
        if event_type == EventType.SCREEN_CAPTURED:
            prompt = data.get("prompt", "Analyze my screen.")
            pet_state = data.get("pet_state", {})
            image = data.get("image")
            conversational = data.get("conversational", False)
            if isinstance(image, QImage) and not image.isNull():
                self.handle_user_query_with_image(prompt, pet_state, image, conversational)
            else:
                logger.warning("SCREEN_CAPTURED event carried no usable image; ignoring.")

        elif event_type == EventType.VOICE_RECORD_STOPPED:
            wav_path = data.get("wav_path", "")
            if wav_path:
                self.event_bus.publish(EventType.LLM_REQUEST_SENT, {"prompt": "Voice input"})
                self.application.run_async(self._transcribe_and_query(wav_path))

        elif event_type == EventType.CHAT_QUERY_REQUESTED:
            prompt = data.get("prompt", "")
            pet_state = data.get("pet_state", {})
            self.handle_user_query(prompt, pet_state)

    async def _transcribe_and_query(self, wav_path: str):
        """Transcribes the PTT recording and pushes the text through the pipeline.

        The temp WAV is always deleted afterwards (privacy: no voice data at rest)."""
        try:
            from src.ai.providers.deepgram import DeepgramProvider
            dp = DeepgramProvider()
            transcript = await dp.transcribe(wav_path)
            if transcript and transcript.strip():
                logger.info(f"Orchestrator: Voice transcribed successfully: '{transcript}'")
                # Voice is the user talking directly TO the pet -> conversational.
                self.handle_user_query(transcript, {}, conversational=True)
            else:
                # Empty transcript = silence / too-short clip. That's not an
                # error — nudge and settle back to idle rather than showing
                # the "I'm having trouble thinking" failure line.
                logger.info("Orchestrator: empty transcript (silence); returning to idle.")
                self.event_bus.publish(EventType.SPEECH_REQUESTED, {"text": "Hmm, I didn't catch that!"})
                self.event_bus.publish(EventType.STATE_TRANSITION_TRIGGERED, {"state": PetState.IDLE})
        except Exception as e:
            logger.error(f"Orchestrator voice transcription failed: {e}")
            self.event_bus.publish(EventType.LLM_ERROR_OCCURRED, {"error": "Transcription failed."})
        finally:
            try:
                if wav_path and os.path.exists(wav_path):
                    os.remove(wav_path)
            except OSError as e:
                logger.warning(f"Could not delete PTT temp recording {wav_path}: {e}")

    def get_active_provider(self) -> LLMProvider:
        """Resolves the LLM client engine from configuration."""
        if Config.LLM_PROVIDER == "krutrim":
            return self.krutrim_provider
        return self.gemini_provider

    def handle_user_query(self, user_prompt: str, pet_state: Dict[str, Any],
                          conversational: bool = False):
        """Initiates the AI response pipeline asynchronously.

        conversational=True (voice / direct chat) unlocks the longer, back-and-
        forth reply mode; ambient/canned prompts stay terse."""
        if self._query_in_flight:
            logger.info("Query already in flight; ignoring new query.")
            return
        logger.info(f"Handling user query: '{user_prompt}'")

        # Desktop agent (opt-in): if this line is a computer command ("open
        # Chrome", "search YouTube for ..."), do it and speak the result instead
        # of chatting. Returns None for anything that isn't a clear command.
        agent_reply = self.agent.try_handle(user_prompt)
        if agent_reply is not None:
            logger.info(f"Agent handled command; reply: '{agent_reply}'")
            self.event_bus.publish(EventType.SPEECH_REQUESTED, {"text": agent_reply})
            return

        # Check if the query asks the pet to look at screen / code / design.
        # Only route to vision when the active provider can actually see.
        visual_keywords = ["look", "screen", "code", "design", "window", "desktop", "ui", "showing"]
        is_visual = any(kw in user_prompt.lower() for kw in visual_keywords)

        if is_visual and self.get_active_provider().supports_vision():
            logger.info("Visual query detected. Requesting screen capture.")
            self.event_bus.publish(EventType.VISION_CAPTURE_REQUESTED, {
                "prompt": user_prompt,
                "pet_state": pet_state,
                "conversational": conversational
            })
            return

        self._query_in_flight = True
        self.event_bus.publish(EventType.LLM_REQUEST_SENT, {"prompt": user_prompt})
        self.application.run_async(self._stream_query(user_prompt, pet_state, conversational=conversational))

    def handle_user_query_with_image(self, user_prompt: str, pet_state: Dict[str, Any],
                                     image: QImage, conversational: bool = False):
        """Initiates the AI response pipeline with a raw screen capture attached.

        The heavy downscale/JPEG encode happens on the worker loop, never here."""
        if self._query_in_flight:
            logger.info("Query already in flight; dropping vision query.")
            return
        if not self.get_active_provider().supports_vision():
            logger.info("Active model cannot process images; informing user.")
            self.event_bus.publish(EventType.SPEECH_REQUESTED, {
                "text": "My current AI model can't see screenshots. Pick a vision model in my menu!"
            })
            return

        logger.info(f"Handling user query with screen capture: '{user_prompt}'")
        self._query_in_flight = True
        self.event_bus.publish(EventType.LLM_REQUEST_SENT, {"prompt": user_prompt})
        self.application.run_async(
            self._stream_query(user_prompt, pet_state, image, conversational=conversational))

    async def _stream_query(self, user_prompt: str, pet_state: Dict[str, Any],
                            image: Optional[QImage] = None, conversational: bool = False):
        """Full query pipeline on the worker loop: context -> prompt -> stream."""
        try:
            loop = asyncio.get_running_loop()

            # 1. Gather system context (blocking subprocess probes) off the loop
            context = await loop.run_in_executor(
                None, self.context_engine.assemble_context, pet_state)

            # 2. Screenshot post-processing (downscale + JPEG) on this thread,
            #    not the GUI thread (audit M-10)
            if image is not None:
                context["screenshot_bytes"] = await loop.run_in_executor(
                    None, vision.process_capture, image)

            # 3. Conversation history (PRD §13: last 20 messages)
            context["conversation_history"] = await self.conv_repo.get_recent_messages(limit=20)

            # 4. Long-term memories + system prompt (mode-aware persona/rules)
            facts = await self.memory_repo.get_all_facts()
            context["system_prompt"] = build_system_prompt(context, facts, conversational)

            # 5. Stream, sanitize, and clamp. Conversation gets a longer budget
            #    than a terse ambient aside.
            char_limit = MAX_CHARACTERS_CONVERSATION if conversational else MAX_CHARACTERS
            provider = self.get_active_provider()
            full_response = ""
            async for raw_chunk in provider.stream(user_prompt, context):
                chunk = sanitize_chunk(raw_chunk)
                if not chunk:
                    continue
                chunk, is_final = clamp_stream_text(len(full_response), chunk, char_limit)
                if chunk:
                    full_response += chunk
                    # `conversational` tells the window whether this reply will
                    # also be spoken — if so it holds the bubble until the audio
                    # starts instead of racing ahead of the voice.
                    self.event_bus.publish(EventType.LLM_RESPONSE_CHUNK,
                                           {"text": chunk, "conversational": conversational})
                if is_final:
                    break

            full_response = full_response.strip()
            logger.info(f"LLM query finished. Complete response: '{full_response}'")
            await self._save_interaction(user_prompt, full_response)
            self.event_bus.publish(EventType.LLM_RESPONSE_RECEIVED,
                                   {"text": full_response, "conversational": conversational})

        except Exception as e:
            logger.error(f"LLM query failed: {e}")
            self.event_bus.publish(EventType.LLM_ERROR_OCCURRED, {"error": "LLM request failed."})
        finally:
            self._query_in_flight = False

    async def _save_interaction(self, user_msg: str, assistant_msg: str):
        try:
            await self.conv_repo.add_message("user", user_msg)
            await self.conv_repo.add_message("assistant", assistant_msg)

            for key, value in extract_memory_facts(user_msg).items():
                await self.memory_repo.save_fact(key, value)
                logger.info(f"Extracted and saved long term memory: {key} = '{value}'")

        except Exception as e:
            logger.error(f"Error saving conversation logs: {e}")
