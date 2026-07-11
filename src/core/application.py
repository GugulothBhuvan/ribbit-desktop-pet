import threading
import asyncio
from typing import Coroutine, Optional
from src.utils.logger import get_logger

logger = get_logger("Application")


class Application:
    """
    Owns the background asyncio worker loop thread.

    This class hosts *no* Qt objects and performs *no* subsystem construction —
    that is the CompositionRoot's job (src/core/composition.py). Its only
    responsibilities are: start the loop thread, schedule coroutines onto it
    from any thread, and stop it cleanly.
    """

    def __init__(self):
        self.loop_thread: Optional[threading.Thread] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.is_running = False

    def start(self):
        """Starts the background asynchronous event loop thread."""
        if self.is_running:
            return

        logger.info("Starting background asyncio worker thread...")
        self.is_running = True

        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(
            target=self._run_background_loop,
            args=(self.loop,),
            daemon=True,
            name="PetAsyncWorker"
        )
        self.loop_thread.start()

    def _run_background_loop(self, loop: asyncio.AbstractEventLoop):
        asyncio.set_event_loop(loop)
        logger.info("Background asyncio loop thread started.")
        loop.run_forever()

    def run_async(self, coro: Coroutine) -> Optional["asyncio.Future"]:
        """Schedules a coroutine to run on the background event loop thread safely.

        Returns a concurrent.futures.Future (use .result(timeout) to block)."""
        if not self.is_running or not self.loop:
            logger.error("Cannot run task. Background loop is not active.")
            return None
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def shutdown(self):
        """Cleanly stops the background loop."""
        if not self.is_running:
            return

        logger.info("Stopping background event loop...")
        self.is_running = False

        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

        if self.loop_thread:
            self.loop_thread.join(timeout=3.0)

        logger.info("Application loop shut down successfully.")
