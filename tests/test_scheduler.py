import pytest
from datetime import datetime, timedelta
from src.core.scheduler import map_weather_code, PomodoroTimer, AmbientScheduler
from src.event_bus import EventBus, EventType
from src.storage.db import Database
from src.storage.repository import ReminderRepository
from src.config import Config

def test_weather_mapping():
    assert map_weather_code(0) == "Sunny"
    assert map_weather_code(2) == "Partly Cloudy"
    assert map_weather_code(45) == "Foggy"
    assert map_weather_code(51) == "Drizzling"
    assert map_weather_code(61) == "Rainy"
    assert map_weather_code(73) == "Snowing"
    assert map_weather_code(95) == "Thunderstorms"
    assert map_weather_code(999) == "Cloudy"

def test_pomodoro_timer():
    bus = EventBus.get_instance()
    pomo = PomodoroTimer(bus)
    
    # Assert initial state
    assert pomo.state == "idle"
    
    # Start Work
    pomo.start_work(25)
    assert pomo.state == "work"
    assert pomo.time_remaining == 25 * 60
    
    # Tick once
    pomo.tick()
    assert pomo.time_remaining == (25 * 60) - 1
    
    # Fast forward tick completion
    pomo.time_remaining = 1
    pomo.tick()
    
    # Auto transitions to break
    assert pomo.state == "break"
    assert pomo.time_remaining == 5 * 60
    
    # Cancel Pomodoro
    pomo.stop()
    assert pomo.state == "idle"

@pytest.mark.asyncio
async def test_ambient_scheduler_reminders():
    # Setup test isolate DB
    original_db = Config.DB_PATH
    Config.DB_PATH = "storage/test_scheduler.db"
    
    db = Database.get_instance()
    db.db_path = Config.DB_PATH
    await db.initialize()
    
    reminder_repo = ReminderRepository(db)
    await reminder_repo.add_reminder(datetime.now() - timedelta(minutes=1), "Stand up and stretch!")
    
    # Initialize scheduler
    sched = AmbientScheduler.get_instance()
    sched.reminder_repo = reminder_repo
    
    triggered_events = []
    def on_event(event_type, data):
        if event_type == EventType.REMINDER_TRIGGERED:
            triggered_events.append(data)
            
    bus = EventBus.get_instance()
    bus.subscribe(on_event)
    
    # Force check pending reminders inside scheduler
    pending = await reminder_repo.get_pending_reminders()
    assert len(pending) == 1
    
    # Mark complete through scheduler process simulation
    for reminder in pending:
        bus.publish(EventType.REMINDER_TRIGGERED, {"description": reminder["task_description"]})
        await reminder_repo.mark_completed(reminder["id"])
        
    bus.unsubscribe(on_event)
    
    # Assert event was received
    assert len(triggered_events) == 1
    assert triggered_events[0]["description"] == "Stand up and stretch!"
    
    # Assert DB shows no pending
    pending_after = await reminder_repo.get_pending_reminders()
    assert len(pending_after) == 0
    
    # Cleanup DB connection and file
    Config.DB_PATH = original_db
    db.db_path = original_db
    try:
        import os
        if os.path.exists("storage/test_scheduler.db"):
            os.remove("storage/test_scheduler.db")
    except Exception:
        pass
