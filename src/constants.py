# Asset Dimensions
DEFAULT_PET_WIDTH = 128
DEFAULT_PET_HEIGHT = 128

# Frames per second
TARGET_FPS = 60
FRAME_INTERVAL_MS = int(1000 / TARGET_FPS)

# Physics Settings
GRAVITY = 9.8  # Pixels per second squared (scaled for desktop physics)
PHYSICS_TIME_STEP = 1.0 / TARGET_FPS
TERMINAL_VELOCITY = 15.0
DRAG_COEFFICIENT = 0.05
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
