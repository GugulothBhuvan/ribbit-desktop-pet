import time
import random
from PyQt6.QtCore import QPoint
from src.constants import (
    PetState, PHYSICS_TIME_STEP, DRAG_COEFFICIENT,
    MIN_WANDER_TIME, MAX_WANDER_TIME, MIN_IDLE_TIME, MAX_IDLE_TIME
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
    """
    def __init__(self, initial_x: float, initial_y: float, width: int, height: int):
        self.event_bus = EventBus.get_instance()
        
        self.x = initial_x
        self.y = initial_y
        self.w = width
        self.h = height
        
        self.vx = 0.0
        self.vy = 0.0
        
        # Wandering / AI behavior attributes
        self.walk_speed = 1.8  # Pixels per frame (~100px/s)
        self.walk_direction = 1  # 1 for right, -1 for left
        self.wander_timer = 0.0
        self.idle_timer = 0.0
        self.next_state_cooldown = 0.0
        
        # Mouse dragging variables
        self.prev_drag_pos = QPoint(int(self.x), int(self.y))
        self.prev_drag_time = time.time()
        
    def update(self, current_state: str, is_dragged: bool) -> tuple[float, float, str]:
        """
        Computes the physics step based on active state.
        Returns: (new_x, new_y, recommended_state)
        """
        recommended_state = current_state
        
        # 1. Handlers for dragged state
        if is_dragged:
            # Gravity suspended; velocity calculated by mouse displacement in window
            curr_time = time.time()
            dt = max(curr_time - self.prev_drag_time, 0.001)
            
            # vx = dx / dt, vy = dy / dt
            self.vx = (self.x - self.prev_drag_pos.x()) / (dt * 60.0)
            self.vy = (self.y - self.prev_drag_pos.y()) / (dt * 60.0)
            
            # Clamp instantaneous velocity to avoid insane fling speeds
            self.vx = max(min(self.vx, 30.0), -30.0)
            self.vy = max(min(self.vy, 30.0), -30.0)
            
            self.prev_drag_pos = QPoint(int(self.x), int(self.y))
            self.prev_drag_time = curr_time
            
            # Force boundary check so user can't drag pet offscreen entirely
            self.x, self.y, self.vx, self.vy, details = CollisionResolver.resolve_boundaries(
                self.x, self.y, self.w, self.h, self.vx, self.vy
            )
            return self.x, self.y, recommended_state

        # 2. Check if pet is suspended above floor (forces Fall state)
        # We perform a tiny boundary check to see if gravity should take over
        temp_x, temp_y, temp_vx, temp_vy, test_details = CollisionResolver.resolve_boundaries(
            self.x, self.y, self.w, self.h, self.vx, self.vy
        )
        is_above_floor = (self.y < test_details["floor_y"])
        
        if is_above_floor and current_state not in [PetState.FALL, PetState.LAUNCH]:
            recommended_state = PetState.FALL
            
        # 3. Process kinematics based on active state
        if current_state == PetState.FALL:
            self.vy = GravitySimulator.apply_gravity(self.vy)
            self.vx *= (1.0 - DRAG_COEFFICIENT)  # Air resistance
            
            self.x += self.vx
            self.y += self.vy
            
            # Resolve collisions
            self.x, self.y, self.vx, self.vy, details = CollisionResolver.resolve_boundaries(
                self.x, self.y, self.w, self.h, self.vx, self.vy
            )
            
            if details["collided_floor"]:
                # Collided with taskbar, trigger landing
                recommended_state = PetState.LANDING
                self.event_bus.publish(EventType.PET_DROPPED, {"above_floor": False})
                
        elif current_state == PetState.WALK:
            # Walk horizontally
            self.vx = self.walk_speed * self.walk_direction
            self.vy = 0.0
            
            self.x += self.vx
            
            # Resolve collisions
            self.x, self.y, self.vx, self.vy, details = CollisionResolver.resolve_boundaries(
                self.x, self.y, self.w, self.h, self.vx, self.vy
            )
            
            if details["collided_wall"]:
                # Reverse direction on wall hit
                self.walk_direction *= -1
                
            # Wander timing logic
            self.wander_timer -= PHYSICS_TIME_STEP
            if self.wander_timer <= 0:
                recommended_state = PetState.IDLE
                self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)
                
        elif current_state == PetState.IDLE:
            # Decelerate sliding to stop
            self.vx *= (1.0 - DRAG_COEFFICIENT)
            if abs(self.vx) < 0.1:
                self.vx = 0.0
            self.vy = 0.0
            
            self.x += self.vx
            
            # Resolve boundaries
            self.x, self.y, self.vx, self.vy, details = CollisionResolver.resolve_boundaries(
                self.x, self.y, self.w, self.h, self.vx, self.vy
            )
            
            # Idle timing loop -> random chance of napping or walking
            self.idle_timer -= PHYSICS_TIME_STEP
            if self.idle_timer <= 0:
                # Random chance wheel
                roll = random.random()
                if roll < 0.4:  # 40% walk
                    recommended_state = PetState.WALK
                    self.walk_direction = random.choice([-1, 1])
                    self.wander_timer = random.uniform(MIN_WANDER_TIME, MAX_WANDER_TIME)
                elif roll < 0.55:  # 15% wave
                    recommended_state = PetState.WAVE
                    self.idle_timer = 2.0  # short delay after wave
                elif roll < 0.7:  # 15% nap / sleep
                    recommended_state = PetState.SLEEP
                    self.idle_timer = random.uniform(8.0, 15.0)
                else:
                    # Continue idling
                    self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)
                    
        elif current_state == PetState.SLEEP:
            # Sleep state - stationary
            self.vx = 0.0
            self.vy = 0.0
            self.idle_timer -= PHYSICS_TIME_STEP
            if self.idle_timer <= 0:
                # Wake up -> transition back to idle
                recommended_state = PetState.IDLE
                self.idle_timer = random.uniform(MIN_IDLE_TIME, MAX_IDLE_TIME)
                
        else:
            # Thinking, listening, talking, waving, landing - decelerate horizontal slide
            self.vx *= (1.0 - DRAG_COEFFICIENT)
            if abs(self.vx) < 0.1:
                self.vx = 0.0
            self.vy = 0.0
            
            self.x += self.vx
            self.x, self.y, self.vx, self.vy, details = CollisionResolver.resolve_boundaries(
                self.x, self.y, self.w, self.h, self.vx, self.vy
            )
            
        return self.x, self.y, recommended_state

    def start_drag(self, pos: QPoint):
        """Prepare variables for manual dragging tracking."""
        self.prev_drag_pos = pos
        self.prev_drag_time = time.time()
        self.vx = 0.0
        self.vy = 0.0
