from src.constants import GRAVITY, TERMINAL_VELOCITY, PHYSICS_TIME_STEP

class GravitySimulator:
    """
    Calculates velocity updates under gravitational force, capping velocity
    at terminal velocity to keep falls visually natural.
    """
    
    @staticmethod
    def apply_gravity(vy: float) -> float:
        """Applies gravity to vertical velocity (vy increases downwards)."""
        # Gravity is scaled by 50 to look visually pleasing and snappy on screens
        vy_delta = (GRAVITY * 60.0) * PHYSICS_TIME_STEP
        new_vy = vy + vy_delta
        
        # Cap at terminal velocity
        if new_vy > TERMINAL_VELOCITY:
            new_vy = TERMINAL_VELOCITY
            
        return new_vy
