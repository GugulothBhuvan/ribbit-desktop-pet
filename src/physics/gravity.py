from src.constants import GRAVITY, TERMINAL_VELOCITY, PHYSICS_TIME_STEP

class GravitySimulator:
    """
    Calculates velocity updates under gravitational force, capping velocity
    at terminal velocity to keep falls visually natural.
    Units: px/s, integrated with the caller's measured dt.
    """

    @staticmethod
    def apply_gravity(vy: float, dt: float = PHYSICS_TIME_STEP) -> float:
        """Applies gravity to vertical velocity (vy increases downwards)."""
        new_vy = vy + GRAVITY * dt

        # Cap at terminal velocity
        if new_vy > TERMINAL_VELOCITY:
            new_vy = TERMINAL_VELOCITY

        return new_vy
