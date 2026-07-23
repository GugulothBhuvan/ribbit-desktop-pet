import time
import random
from PyQt6.QtCore import QPoint
from src.constants import (
    PetState, PHYSICS_TIME_STEP, MAX_PHYSICS_DT, WALK_SPEED,
    AIR_DRAG_PER_SEC, GROUND_DRAG_PER_SEC, MIN_SLIDE_SPEED, MAX_THROW_SPEED,
    COYOTE_MARGIN_PX,
    MIN_WANDER_TIME, MAX_WANDER_TIME, MIN_IDLE_TIME, MAX_IDLE_TIME,
    PANIC_CHANCE, PANIC_RUN_SPEED, PANIC_MIN_BOUNCES, PANIC_MAX_BOUNCES, PANIC_MAX_TIME
)
from src.physics.gravity import GravitySimulator
from src.physics.collision import CollisionResolver
from src.event_bus import EventBus, EventType
from src.utils.logger import get_logger

logger = get_logger("Movement")

class MovementController:
    """
    Main coordinates physics loop. Calculates kinematics updates,
    autonomous wandering, friction drag dampening, and mouse drag tracking.

    All velocities are px/s and every update integrates the caller-measured
    dt, so pet speed no longer depends on timer accuracy (audit m-3). Exactly
    one boundary resolution runs per tick (audit m-4).
    """
    def __init__(self, event_bus: EventBus, initial_x: float, initial_y: float, width: int, height: int):
        self.event_bus = event_bus

        self.x = initial_x
        self.y = initial_y
        self.w = width
        self.h = height

        self.vx = 0.0
        self.vy = 0.0

        # Wandering / AI behavior attributes
        self.walk_direction = 1  # 1 for right, -1 for left
        self.wander_timer = 0.0
        self.idle_timer = 0.0

        # Cockroach panic run
        self._panic_active = False
        self.panic_bounces_left = 0
        self.panic_timer = 0.0

        # Mouse dragging variables
        self.prev_drag_pos = QPoint(int(self.x), int(self.y))
        self.prev_drag_time = time.time()

    def update(self, current_state: str, is_dragged: bool,
               dt: float = PHYSICS_TIME_STEP) -> tuple[float, float, str]:
        """
        Computes one physics step for the measured time delta.
        Returns: (new_x, new_y, recommended_state)
        """
        dt = min(max(dt, 0.0), MAX_PHYSICS_DT)
        recommended_state = current_state

        # 1. Handlers for dragged state
        if is_dragged:
            # Gravity suspended; throw velocity tracked from mouse displacement
            curr_time = time.time()
            drag_dt = max(curr_time - self.prev_drag_time, 0.001)

            self.vx = (self.x - self.prev_drag_pos.x()) / drag_dt
            self.vy = (self.y - self.prev_drag_pos.y()) / drag_dt

            # Clamp instantaneous velocity to avoid insane fling speeds
            self.vx = max(min(self.vx, MAX_THROW_SPEED), -MAX_THROW_SPEED)
            self.vy = max(min(self.vy, MAX_THROW_SPEED), -MAX_THROW_SPEED)

            self.prev_drag_pos = QPoint(int(self.x), int(self.y))
            self.prev_drag_time = curr_time

            # Boundary check so user can't drag pet offscreen entirely
            self.x, self.y, self.vx, self.vy, _ = CollisionResolver.resolve_boundaries(
                self.x, self.y, self.w, self.h, self.vx, self.vy
            )
            return self.x, self.y, recommended_state

        # 2. Determine the active floor once (no throwaway resolve pass)
        center = QPoint(int(self.x + self.w / 2), int(self.y + self.h / 2))
        screen_geom = CollisionResolver.get_active_screen_geometry(center)
        floor_y = screen_geom.top() + screen_geom.height() - self.h
        is_above_floor = self.y < floor_y - COYOTE_MARGIN_PX

        if is_above_floor and current_state not in [PetState.FALL, PetState.LAUNCH]:
            recommended_state = PetState.FALL

        # 3. Integrate kinematics for the active state
        if current_state == PetState.FALL:
            self.vy = GravitySimulator.apply_gravity(self.vy, dt)
            self.vx *= max(0.0, 1.0 - AIR_DRAG_PER_SEC * dt)  # air resistance
            self.x += self.vx * dt
            self.y += self.vy * dt

        elif current_state == PetState.WALK:
            self.vx = WALK_SPEED * self.walk_direction
            self.vy = 0.0
            self.x += self.vx * dt

            # Wander timing logic
            self.wander_timer -= dt
            if self.wander_timer <= 0:
                recommended_state = PetState.IDLE
                self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)

        elif current_state == PetState.PANIC_RUN:
            if not self._panic_active:          # first tick of a panic run
                self._panic_active = True
                self.walk_direction = random.choice([-1, 1])
                self.panic_bounces_left = random.randint(PANIC_MIN_BOUNCES, PANIC_MAX_BOUNCES)
                self.panic_timer = PANIC_MAX_TIME
            self.vx = PANIC_RUN_SPEED * self.walk_direction
            self.vy = 0.0
            self.x += self.vx * dt
            self.panic_timer -= dt
            if self.panic_timer <= 0:            # safety cap: calm down
                recommended_state = PetState.IDLE
                self._panic_active = False
                self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)

        elif current_state == PetState.SLEEP:
            self.vx = 0.0
            self.vy = 0.0
            self.idle_timer -= dt
            if self.idle_timer <= 0:
                # Wake up -> transition back to idle
                recommended_state = PetState.IDLE
                self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)
            return self.x, self.y, recommended_state  # stationary: skip resolve

        else:
            # Idle, thinking, listening, talking, waving, landing:
            # decelerate any residual horizontal slide
            self.vx *= max(0.0, 1.0 - GROUND_DRAG_PER_SEC * dt)
            if abs(self.vx) < MIN_SLIDE_SPEED:
                self.vx = 0.0
            self.vy = 0.0
            self.x += self.vx * dt

            if current_state == PetState.IDLE:
                # Idle timing loop -> random chance of napping or walking
                self.idle_timer -= dt
                if self.idle_timer <= 0:
                    recommended_state = self._roll_idle_behavior()

        # 4. Single boundary resolution for this tick
        self.x, self.y, self.vx, self.vy, details = CollisionResolver.resolve_boundaries(
            self.x, self.y, self.w, self.h, self.vx, self.vy
        )

        # 4b. Never linger in dead space between non-adjacent monitors: hop the
        # pet across the gap onto the next display so it stays visible while roaming.
        self.x = CollisionResolver.skip_dead_gap(self.x, self.w, self.vx)

        if current_state == PetState.FALL and details["collided_floor"]:
            # Collided with taskbar, trigger landing
            recommended_state = PetState.LANDING
            self.event_bus.publish(EventType.PET_DROPPED, {"above_floor": False})

        elif current_state == PetState.WALK and details["collided_wall"]:
            # Reverse direction on wall hit
            self.walk_direction *= -1

        elif current_state == PetState.PANIC_RUN and details["collided_wall"]:
            # Bounce off the wall; after enough bounces he calms down.
            self.walk_direction *= -1
            self.panic_bounces_left -= 1
            if self.panic_bounces_left <= 0:
                recommended_state = PetState.IDLE
                self._panic_active = False
                self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)

        return self.x, self.y, recommended_state

    def _roll_idle_behavior(self) -> str:
        """Random chance wheel deciding what an idle pet does next."""
        from src.config import Config
        if Config.REDUCED_MOTION:
            # Calm mode (PRD §15 reduced motion): stay put
            self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)
            return PetState.IDLE

        # Rare cockroach-panic run (Modi only): lift the jhola, then sprint. The
        # SLING one-shot chains into PANIC_RUN via ANIMATION_FINISHED.
        if Config.SELECTED_MASCOT == "modi" and random.random() < PANIC_CHANCE:
            self._panic_active = False   # armed; PANIC_RUN initialises on entry
            return PetState.SLING

        roll = random.random()
        if roll < 0.55:  # 55% walk — the pet should roam, not mostly stand
            self.walk_direction = random.choice([-1, 1])
            self.wander_timer = random.uniform(MIN_WANDER_TIME, MAX_WANDER_TIME)
            return PetState.WALK
        if roll < 0.65:  # 10% wave
            self.idle_timer = 2.0  # short delay after wave
            return PetState.WAVE
        if roll < 0.75:  # 10% nap / sleep
            self.idle_timer = random.uniform(8.0, 15.0)
            return PetState.SLEEP
        # Continue idling
        self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)
        return PetState.IDLE

    def start_drag(self, pos: QPoint):
        """Prepare variables for manual dragging tracking."""
        self.prev_drag_pos = pos
        self.prev_drag_time = time.time()
        self.vx = 0.0
        self.vy = 0.0
