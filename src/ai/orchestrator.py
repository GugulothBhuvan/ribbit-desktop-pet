import os
import asyncio
from typing import Dict, Any
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from src.config import Config
from src.event_bus import EventBus, EventType
from src.ai.context_engine import ContextEngine
from src.ai.providers.base import LLMProvider
from src.ai.providers.gemini import GeminiProvider
from src.ai.providers.krutrim import KrutrimProvider
from src.storage.db import Database
from src.storage.repository import ConversationRepository, MemoryRepository
from src.core.application import Application
from src.utils.logger import get_logger

logger = get_logger("AIOrchestrator")

SYSTEM_PROMPT_TEMPLATE = """
You are a tiny, animated, intelligent, and slightly sarcastic 2D desktop pet companion living on the user's screen.
Your personality: Playful, curious, developer-centric (likes technical jokes, comments on code issues, uncommitted git files), and encouraging.
Current environment details:
- User's active window: {active_window}
- System time: {current_time}
- Battery level: {battery_percent}%
- Pet physical state: {pet_active_state}
- Git status: {git_uncommitted} uncommitted files, last commit: "{git_last_commit}"
- Pytest run outcome: {recent_test_outcome} ({failed_tests_count} failed tests)

CRITICAL RULES:
1. Keep your reply extremely short: strictly under 150 characters (approx. 20 words).
2. Avoid generic chatbot pleasantries. Answer directly in character.
3. Be witty, encouraging, or tease the user playfully if they are working too long or compiling code.
4. Keep the tone friendly. Never be offensive.
"""

class LLMStreamWorker(QThread):
    """Background worker thread to run asynchronous HTTP streaming to avoid GUI freezes.

    Signal names deliberately avoid QThread's built-in `finished` signal —
    shadowing it silently breaks delivery of the response payload."""
    chunk_received = pyqtSignal(str)
    stream_finished = pyqtSignal(str)
    stream_error = pyqtSignal(str)

    def __init__(self, provider: LLMProvider, prompt: str, context: Dict[str, Any]):
        super().__init__()
        self.provider = provider
        self.prompt = prompt
        self.context = context

    def run(self):
        try:
            # Setup thread-local async event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._execute_stream())
            loop.close()
        except Exception as e:
            logger.error(f"Error in LLMStreamWorker: {e}")
            self.stream_error.emit(str(e))

    async def _execute_stream(self):
        full_response = ""
        async for chunk in self.provider.stream(self.prompt, self.context):
            full_response += chunk
            self.chunk_received.emit(chunk)
        self.stream_finished.emit(full_response)

class AIOrchestrator(QObject):
    """
    Coordinates context gathering, database history extraction, system prompts preparation,
    LLM API dispatch via worker threads, and event propagation.

    Constructed once by the CompositionRoot on the GUI thread. It is the SINGLE
    consumer of SCREEN_CAPTURED (the window owns the capture itself) — this
    prevents the previous double-capture design.
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

        self.worker = None

        for event_type in self.SUBSCRIBED_EVENTS:
            self.event_bus.subscribe(event_type, self.on_event, executor="gui")

    def on_event(self, event_type: str, data: dict):
        """Processes EventBus queries for voice recording releases and captured screens."""
        if event_type == EventType.SCREEN_CAPTURED:
            prompt = data.get("prompt", "Analyze my screen.")
            pet_state = data.get("pet_state", {})
            image_bytes = data.get("image_bytes")
            if image_bytes:
                self.handle_user_query_with_image(prompt, pet_state, image_bytes)
            else:
                logger.warning("SCREEN_CAPTURED event carried no image bytes; ignoring.")

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
            if transcript:
                logger.info(f"Orchestrator: Voice transcribed successfully: '{transcript}'")
                self.handle_user_query(transcript, {})
            else:
                self.event_bus.publish(EventType.LLM_ERROR_OCCURRED, {"error": "Could not transcribe audio."})
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

    def handle_user_query(self, user_prompt: str, pet_state: Dict[str, Any]):
        """Initiates the AI response pipeline asynchronously."""
        logger.info(f"Handling user query: '{user_prompt}'")

        # Check if the query asks the pet to look at screen / code / design.
        # Only route to vision when the active provider can actually see.
        visual_keywords = ["look", "screen", "code", "design", "window", "desktop", "ui", "showing"]
        is_visual = any(kw in user_prompt.lower() for kw in visual_keywords)

        if is_visual and self.get_active_provider().supports_vision():
            logger.info("Visual query detected. Requesting screen capture.")
            self.event_bus.publish(EventType.VISION_CAPTURE_REQUESTED, {
                "prompt": user_prompt,
                "pet_state": pet_state
            })
            return

        # Dispatch notification to transition to thinking state
        self.event_bus.publish(EventType.LLM_REQUEST_SENT, {"prompt": user_prompt})

        # We start a task to load database context and spin up LLM worker
        self.application.run_async(self._prepare_and_run_worker(user_prompt, pet_state))

    def handle_user_query_with_image(self, user_prompt: str, pet_state: Dict[str, Any], image_bytes: bytes):
        """Initiates the AI response pipeline with screenshot bytes included."""
        logger.info(f"Handling user query with screen capture: '{user_prompt}'")
        self.event_bus.publish(EventType.LLM_REQUEST_SENT, {"prompt": user_prompt})
        self.application.run_async(self._prepare_and_run_worker(user_prompt, pet_state, image_bytes))

    async def _prepare_and_run_worker(self, user_prompt: str, pet_state: Dict[str, Any], image_bytes: bytes = None):
        try:
            # 1. Gather active context
            context = self.context_engine.assemble_context(pet_state)
            if image_bytes:
                context["screenshot_bytes"] = image_bytes

            # 2. Extract recent conversation logs
            history = await self.conv_repo.get_recent_messages(limit=10)
            context["conversation_history"] = history

            # 3. Pull long term memories
            facts = await self.memory_repo.get_all_facts()
            context["long_term_memories"] = facts

            # 4. Generate system prompt
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                active_window=context["active_window"],
                current_time=context["current_time"],
                battery_percent=context["battery_percent"],
                pet_active_state=context["pet_active_state"],
                git_uncommitted=context["git_uncommitted_count"],
                git_last_commit=context["git_last_commit"],
                recent_test_outcome=context["test_outcome"],
                failed_tests_count=context["test_failed_count"]
            )

            # If user facts exist, append them to the system prompt context
            if facts:
                system_prompt += f"\nKnown user preferences/facts: {facts}\n"

            context["system_prompt"] = system_prompt

            # 5. Launch LLM worker thread
            provider = self.get_active_provider()
            # Connect ONLY bound methods of this QObject: their delivery is
            # queued to the orchestrator's (GUI) thread. A lambda connected
            # here would be bound to the asyncio thread, which has no Qt event
            # loop, and would never fire.
            self.worker = LLMStreamWorker(provider, user_prompt, context)
            self.worker.chunk_received.connect(self._on_chunk_received)
            self.worker.stream_finished.connect(self._on_stream_finished)
            self.worker.stream_error.connect(self._on_error_received)
            self.worker.start()

        except Exception as e:
            logger.error(f"Failed to prepare LLM query: {e}")
            self.event_bus.publish(EventType.LLM_ERROR_OCCURRED, {"error": "Failed to prepare query."})

    def _on_chunk_received(self, chunk: str):
        self.event_bus.publish(EventType.LLM_RESPONSE_CHUNK, {"text": chunk})

    def _on_stream_finished(self, text: str):
        prompt = self.worker.prompt if self.worker else ""
        self._on_generation_finished(prompt, text)

    def _on_error_received(self, error_msg: str):
        logger.error(f"LLM request error: {error_msg}")
        self.event_bus.publish(EventType.LLM_ERROR_OCCURRED, {"error": "LLM request failed."})

    def _on_generation_finished(self, prompt: str, complete_response: str):
        logger.info(f"LLM query finished. Complete response: '{complete_response}'")

        # Save messages to database history in background
        self.application.run_async(self._save_interaction(prompt, complete_response))

        # Broadcast completed response
        self.event_bus.publish(EventType.LLM_RESPONSE_RECEIVED, {"text": complete_response})

    async def _save_interaction(self, user_msg: str, assistant_msg: str):
        try:
            await self.conv_repo.add_message("user", user_msg)
            await self.conv_repo.add_message("assistant", assistant_msg)

            # Simple heuristic to extract memories: if user mentions name or programming preference
            # e.g., "my name is X", "I use React"
            lower_msg = user_msg.lower()
            if "my name is " in lower_msg:
                name = user_msg.split("my name is ")[1].strip(" .?!")
                await self.memory_repo.save_fact("user_name", name)
                logger.info(f"Extracted and saved long term memory: user_name = '{name}'")
            if "i prefer " in lower_msg or "i code in " in lower_msg:
                pref = user_msg.split("prefer ")[-1].strip(" .?!")
                await self.memory_repo.save_fact("coding_pref", pref)
                logger.info(f"Extracted and saved long term memory: coding_pref = '{pref}'")

        except Exception as e:
            logger.error(f"Error saving conversation logs: {e}")
