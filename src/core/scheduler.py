import asyncio
import time
import httpx
from src.event_bus import EventBus, EventType
from src.storage.db import Database
from src.storage.repository import ReminderRepository
from src.ai.context_engine import ContextEngine
from src.utils.logger import get_logger

logger = get_logger("Scheduler")

def map_weather_code(code: int) -> str:
    """Maps Open-Meteo weather codes to short descriptive strings."""
    if code == 0: return "Sunny"
    if code in [1, 2, 3]: return "Partly Cloudy"
    if code in [45, 48]: return "Foggy"
    if code in [51, 53, 55]: return "Drizzling"
    if code in [61, 63, 65, 80, 81, 82]: return "Rainy"
    if code in [71, 73, 75]: return "Snowing"
    if code in [95, 96, 99]: return "Thunderstorms"
    return "Cloudy"

class PomodoroTimer:
    """Tracks work/break Pomodoro cycles."""
    
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.state = "idle"  # idle, work, break
        self.time_remaining = 0
        self.total_duration = 0
        
    def start_work(self, duration_mins: int = 25):
        self.state = "work"
        self.total_duration = duration_mins * 60
        self.time_remaining = self.total_duration
        logger.info(f"Pomodoro work session started: {duration_mins} mins")
        
    def start_break(self, duration_mins: int = 5):
        self.state = "break"
        self.total_duration = duration_mins * 60
        self.time_remaining = self.total_duration
        logger.info(f"Pomodoro break session started: {duration_mins} mins")
        
    def stop(self):
        self.state = "idle"
        self.time_remaining = 0
        logger.info("Pomodoro session cancelled.")
        
    def tick(self):
        """Called every second by the main scheduler loop."""
        if self.state == "idle":
            return
            
        self.time_remaining -= 1
        self.event_bus.publish(EventType.POMODORO_TICK, {
            "state": self.state,
            "time_remaining": self.time_remaining
        })
        
        if self.time_remaining <= 0:
            if self.state == "work":
                logger.info("Pomodoro work complete!")
                self.event_bus.publish(EventType.POMODORO_WORK_COMPLETE, {})
                self.start_break()  # Auto-transition to break
            elif self.state == "break":
                logger.info("Pomodoro break complete!")
                self.event_bus.publish(EventType.POMODORO_BREAK_COMPLETE, {})
                self.stop()

class AmbientScheduler:
    """
    Main polling loop running on background asyncio thread.
    Triggers weather fetch updates, low battery checks, calendar alarms,
    and handles Pomodoro time progression.
    Event handlers run on the async worker loop (executor="async").
    """

    # Events consumed by the AI-invocation decision engine
    SUBSCRIBED_EVENTS_ASYNC = [
        EventType.BATTERY_WARNING,
        EventType.TESTS_PASSED,
        EventType.TESTS_FAILED,
        EventType.USER_IDLE,
        EventType.USER_ACTIVE,
        EventType.APPLICATION_CHANGED,
        EventType.SCREEN_STABLE,
    ]

    def __init__(self, event_bus: EventBus, db: Database, context_engine: ContextEngine):
        self.event_bus = event_bus
        self.db = db
        self.reminder_repo = ReminderRepository(self.db)
        self.context_engine = context_engine
        self.pomodoro = PomodoroTimer(self.event_bus)
        
        # Track checking times
        self.last_reminder_check = 0.0
        self.last_weather_check = 0.0
        self.last_ide_check = 0.0
        self.prev_test_outcome = "unknown"
        self.prev_test_failed_count = 0
        
        # Stateful Event-Driven AI Scheduler parameters
        from src.config import Config
        self.last_ai_invocation = 0.0
        self.ai_cooldown_seconds = Config.AMBIENT_AI_COOLDOWN_SEC
        self.pending_low_priority_events = []
        
        # Subscribe to Event Bus to act as the central AI Scheduler decision engine
        for event_type in self.SUBSCRIBED_EVENTS_ASYNC:
            self.event_bus.subscribe(event_type, self.on_event, executor="async")

    def on_event(self, event_type: str, data: dict):
        """Processes and filters system events to throttle and coordinate AI invocation."""
        now = time.time()
        
        # High Priority Events: Enforce instant processing, bypass standard idle/stability debounces
        if event_type == EventType.BATTERY_WARNING:
            if now - self.last_ai_invocation >= 60.0:
                self.last_ai_invocation = now
                logger.info("Scheduler: High-priority Battery Warning received. Processing immediately.")
                
        elif event_type in [EventType.TESTS_PASSED, EventType.TESTS_FAILED]:
            logger.info(f"Scheduler: High-priority Test Outcome Event '{event_type}' received.")
            
        elif event_type == EventType.USER_IDLE:
            logger.info("Scheduler: User Idle event received. Scheduling idle behavior.")
            
        elif event_type == EventType.USER_ACTIVE:
            logger.info("Scheduler: User Active event received.")
            
        # Low Priority Events: Wait for SCREEN_STABLE to prevent multiple rapid queries
        elif event_type == EventType.APPLICATION_CHANGED:
            app_name = data.get("app_name", "")
            logger.info(f"Scheduler: Application change queued: {app_name}")
            self.pending_low_priority_events.append({
                "type": event_type,
                "data": data,
                "timestamp": now
            })
            
        elif event_type == EventType.SCREEN_STABLE:
            if self.pending_low_priority_events:
                merged_data = self.pending_low_priority_events[-1]["data"]
                self.pending_low_priority_events.clear()
                
                if now - self.last_ai_invocation >= self.ai_cooldown_seconds:
                    self.last_ai_invocation = now
                    logger.info("Scheduler: Screen stable and cooldown elapsed. Triggering vision query.")
                    self.event_bus.publish(EventType.VISION_CAPTURE_REQUESTED, {
                        "prompt": f"Analyze my screen. I just focused on application {merged_data.get('app_name')}.",
                        "pet_state": {}
                    })
                else:
                    logger.info("Scheduler: Screen stable, but AI invocation throttled due to active cooldown.")

    async def fetch_local_weather(self):
        """Fetches geolocation weather information using free, keyless APIs."""
        logger.info("Fetching ambient local weather...")
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                # 1. Geolocation lookup by host IP
                res = await client.get("http://ip-api.com/json")
                if res.status_code != 200:
                    logger.warning("Location lookup failed: wttr.in fallback...")
                    return
                    
                loc = res.json()
                if loc.get("status") != "success":
                    logger.warning("ip-api reported unsuccessful lookup.")
                    return
                    
                lat = loc.get("lat")
                lon = loc.get("lon")
                city = loc.get("city")
                
                # 2. Query forecast metrics
                weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                w_res = await client.get(weather_url)
                if w_res.status_code == 200:
                    w_data = w_res.json()
                    curr = w_data.get("current_weather", {})
                    temp = curr.get("temperature", 20.0)
                    code = curr.get("weathercode", 0)
                    
                    desc = map_weather_code(code)
                    
                    self.event_bus.publish(EventType.WEATHER_FETCHED, {
                        "city": city,
                        "temperature": float(temp),
                        "description": desc
                    })
                    logger.info(f"Weather fetched successfully: {city} -> {temp}°C, {desc}")
                else:
                    logger.warning(f"Open-Meteo query failed: status {w_res.status_code}")
        except Exception as e:
            logger.error(f"Failed to fetch local weather: {e}")

    async def run(self):
        """Continuous scheduler execution loop."""
        logger.info("AmbientScheduler background task started.")
        
        while True:
            now = time.time()
            
            # 1. Reminders Check (every 30 seconds)
            if now - self.last_reminder_check >= 30.0:
                self.last_reminder_check = now
                try:
                    pending = await self.reminder_repo.get_pending_reminders()
                    for reminder in pending:
                        logger.info(f"Triggering reminder: {reminder['task_description']}")
                        self.event_bus.publish(EventType.REMINDER_TRIGGERED, {
                            "description": reminder["task_description"]
                        })
                        await self.reminder_repo.mark_completed(reminder["id"])
                except Exception as e:
                    logger.error(f"Error checking pending reminders: {e}")
            
            # 2. Battery warnings are owned by Win32Observer (rate-limited there).

            # 3. Weather Check (every 1 hour / 3600 seconds - run first check immediately)
            if self.last_weather_check == 0.0 or now - self.last_weather_check >= 3600.0:
                self.last_weather_check = now
                # Fire task asynchronously to avoid slowing other checks
                asyncio.create_task(self.fetch_local_weather())
            
            # 4. Tick Pomodoro session progress (every 1 second)
            self.pomodoro.tick()
            
            # 5. IDE & Workflow Status check (every 5 seconds; only when a
            #    project directory is configured — see Config.WATCH_PROJECT_DIR)
            from src.config import Config
            if Config.WATCH_PROJECT_DIR and now - self.last_ide_check >= 5.0:
                self.last_ide_check = now
                try:
                    test_ctx = self.context_engine.get_test_context()
                    outcome = test_ctx.get("recent_test_run_outcome", "unknown")
                    failed_count = test_ctx.get("failed_tests_count", 0)
                    is_fresh = test_ctx.get("is_fresh", False)
                    
                    if is_fresh and self.prev_test_outcome != "unknown":
                        if outcome == "passed" and self.prev_test_outcome != "passed":
                            logger.info("IDE Sync: pytest outcome shifted to passed. Publishing EventType.TESTS_PASSED.")
                            self.event_bus.publish(EventType.TESTS_PASSED, {})
                        elif outcome == "failed" and (self.prev_test_outcome != "failed" or failed_count != self.prev_test_failed_count):
                            logger.info(f"IDE Sync: pytest outcome shifted to failed ({failed_count} tests). Publishing EventType.TESTS_FAILED.")
                            self.event_bus.publish(EventType.TESTS_FAILED, {"failed_count": failed_count})
                    
                    self.prev_test_outcome = outcome
                    self.prev_test_failed_count = failed_count
                except Exception as e:
                    logger.error(f"Error checking IDE/workflow status: {e}")
            
            await asyncio.sleep(1.0)
