import threading
import asyncio
import concurrent.futures
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

    def run_async(self, coro: Coroutine) -> Optional[concurrent.futures.Future]:
        """Schedules a coroutine to run on the background event loop thread safely.

        Returns a concurrent.futures.Future (use .result(timeout) to block)."""
        if not self.is_running or not self.loop:
            logger.error("Cannot run task. Background loop is not active.")
            return None
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def _drain_tasks(self):
        """Gives in-flight tasks (telemetry flush, DB writes) a moment to
        finish, then cancels stragglers (e.g. infinite scheduler loops)."""
        current = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks() if t is not current]
        if not tasks:
            return
        done, pending = await asyncio.wait(tasks, timeout=2.0)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info(f"Drained {len(done)} tasks, cancelled {len(pending)}.")

    def shutdown(self):
        """Cleanly stops the background loop: drain pending work first, then
        stop and close the loop (audit m-19)."""
        if not self.is_running:
            return

        logger.info("Stopping background event loop...")
        self.is_running = False

        if self.loop:
            try:
                asyncio.run_coroutine_threadsafe(self._drain_tasks(), self.loop).result(timeout=4.0)
            except Exception as e:
                logger.warning(f"Task drain did not complete cleanly: {e}")
            self.loop.call_soon_threadsafe(self.loop.stop)

        if self.loop_thread:
            self.loop_thread.join(timeout=3.0)

        if self.loop and not self.loop.is_running():
            try:
                self.loop.close()
            except Exception as e:
                logger.warning(f"Error closing event loop: {e}")

        logger.info("Application loop shut down successfully.")
