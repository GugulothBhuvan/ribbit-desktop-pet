# Asset Dimensions
DEFAULT_PET_WIDTH = 128
DEFAULT_PET_HEIGHT = 128

# Frames per second
TARGET_FPS = 60
FRAME_INTERVAL_MS = int(1000 / TARGET_FPS)

# Physics Settings — all values in pixels and SECONDS, integrated with a
# measured dt (previously per-frame units assumed a perfect 60 Hz timer, and
# gravity hit terminal velocity within 2 frames — audit m-2/m-3)
GRAVITY = 2200.0            # px/s^2 — visible acceleration over ~0.5s falls
TERMINAL_VELOCITY = 1300.0  # px/s
WALK_SPEED = 110.0          # px/s horizontal wander speed
AIR_DRAG_PER_SEC = 3.0      # fraction of horizontal velocity shed per second airborne
GROUND_DRAG_PER_SEC = 4.0   # fraction shed per second sliding on the floor
MIN_SLIDE_SPEED = 5.0       # px/s below which sliding stops dead
MAX_THROW_SPEED = 1800.0    # px/s clamp on drag-release fling velocity
JUMP_IMPULSE = -700.0       # px/s vertical kick at jump launch
JUMP_FORWARD_SPEED = 120.0  # px/s horizontal component of a jump
COYOTE_MARGIN_PX = 2.0      # floor tolerance preventing idle/fall flapping
MAX_PHYSICS_DT = 0.05       # seconds; clamps dt after event-loop stalls
PHYSICS_TIME_STEP = 1.0 / TARGET_FPS  # fallback dt when none is measured
BOUNCE_COEFFICIENT = 0.3

# Behavior & Wandering
MIN_WANDER_TIME = 2.0  # Min seconds in walk state before idling
MAX_WANDER_TIME = 5.0
MIN_IDLE_TIME = 3.0
MAX_IDLE_TIME = 10.0

# Animation States
class PetState:
    IDLE = "idle"
    WALK = "walk"
    WAVE = "wave"
    CROUCH = "crouch"
    LAUNCH = "launch"
    FALL = "fall"
    LANDING = "landing"
    THINK = "think"
    LISTEN = "listen"
    TALK = "talk"
    DRAGGED = "dragged"
    SLEEP = "sleep"
    SIT = "sit"

# Mouse Interaction
CLICK_DRAG_THRESHOLD_PX = 6     # Movement beyond this is a drag, not a click
SINGLE_CLICK_DELAY_MS = 280     # Wait for a possible double-click before acting

# Dialogue Configuration
MAX_BUBBLE_WIDTH = 300
MAX_CHARACTERS = 150
DEFAULT_TYPING_SPEED_MS = 40
FADE_DURATION_MS = 500
READING_TIME_PER_WORD_MS = 250  # Additional reading window before fade

# Database Path Default
DEFAULT_DB_PATH = "storage/pet_memory.db"
