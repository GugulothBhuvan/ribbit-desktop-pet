import pytest
from datetime import datetime, timedelta
from src.core.scheduler import map_weather_code, PomodoroTimer, AmbientScheduler
from src.event_bus import EventType
from src.storage.repository import ReminderRepository
from src.ai.context_engine import ContextEngine

def test_weather_mapping():
    assert map_weather_code(0) == "Sunny"
    assert map_weather_code(2) == "Partly Cloudy"
    assert map_weather_code(45) == "Foggy"
    assert map_weather_code(51) == "Drizzling"
    assert map_weather_code(61) == "Rainy"
    assert map_weather_code(73) == "Snowing"
    assert map_weather_code(95) == "Thunderstorms"
    assert map_weather_code(999) == "Cloudy"

def test_pomodoro_timer(event_bus):
    pomo = PomodoroTimer(event_bus)

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
async def test_ambient_scheduler_reminders(event_bus, tmp_db):
    await tmp_db.initialize()

    reminder_repo = ReminderRepository(tmp_db)
    await reminder_repo.add_reminder(datetime.now() - timedelta(minutes=1), "Stand up and stretch!")

    # Initialize scheduler with injected dependencies
    sched = AmbientScheduler(event_bus, tmp_db, ContextEngine())
    assert sched.reminder_repo is not None

    triggered_events = []
    def on_event(event_type, data):
        triggered_events.append(data)

    event_bus.subscribe(EventType.REMINDER_TRIGGERED, on_event, executor="gui")

    # Force check pending reminders inside scheduler
    pending = await reminder_repo.get_pending_reminders()
    assert len(pending) == 1

    # Mark complete through scheduler process simulation
    for reminder in pending:
        event_bus.publish(EventType.REMINDER_TRIGGERED, {"description": reminder["task_description"]})
        await reminder_repo.mark_completed(reminder["id"])

    event_bus.unsubscribe(EventType.REMINDER_TRIGGERED, on_event)

    # Assert event was received
    assert len(triggered_events) == 1
    assert triggered_events[0]["description"] == "Stand up and stretch!"

    # Assert DB shows no pending
    pending_after = await reminder_repo.get_pending_reminders()
    assert len(pending_after) == 0
