import os
from dotenv import load_dotenv
from src.constants import DEFAULT_DB_PATH
from src.utils.logger import get_logger

# Load environment variables from .env
load_dotenv()

logger = get_logger("Config")

class Config:
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "krutrim").lower()
    
    # Gemini API Settings
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # Krutrim API Settings
    KRUTRIM_API_KEY = os.getenv("KRUTRIM_API_KEY", "")
    # Default: gemma-4-E4B-it — small, fast, non-reasoning, supports images.
    # The TRD's Qwen3.6-35B-A3B is a reasoning model on Krutrim: it consumes the
    # whole max_tokens budget on hidden "reasoning" deltas and returns empty
    # replies at speech-bubble token limits (verified 2026-07-12).
    KRUTRIM_MODEL = os.getenv("KRUTRIM_MODEL", "gemma-4-E4B-it")
    
    # Deepgram Voice API
    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
    
    # Local Database
    DB_PATH = os.getenv("DB_PATH", DEFAULT_DB_PATH)
    
    # UI Configurations
    ANIMATION_SCALE = float(os.getenv("ANIMATION_SCALE", "1.0"))
    PET_VOLUME = float(os.getenv("PET_VOLUME", "0.8"))
    SPEECH_TYPING_SPEED_MS = int(os.getenv("SPEECH_TYPING_SPEED_MS", "40"))
    SPEECH_BUBBLE_COOLDOWN_SEC = int(os.getenv("SPEECH_BUBBLE_COOLDOWN_SEC", "10"))
    
    # Behavior Settings
    WANDER_INTERVAL_MIN = int(os.getenv("WANDER_INTERVAL_MIN", "2"))
    WANDER_INTERVAL_MAX = int(os.getenv("WANDER_INTERVAL_MAX", "5"))

    # Minimum seconds between ambient (non-user-initiated) AI invocations
    AMBIENT_AI_COOLDOWN_SEC = float(os.getenv("AMBIENT_AI_COOLDOWN_SEC", "20"))

    # Project directory to watch for git status / pytest results ("IDE sync").
    # Empty = feature disabled. Previously these probes scanned the pet's own
    # CWD, reporting the pet's own repo state to the LLM (audit M-9).
    WATCH_PROJECT_DIR = os.getenv("WATCH_PROJECT_DIR", "")
    
    # Mascot Settings
    SELECTED_MASCOT = "default"

    # Accessibility / behavior toggles (persisted in the settings table)
    MUTED = False
    REDUCED_MOTION = False  # "Calm mode": pet stays idle, no wandering/napping
    
    @classmethod
    def validate(cls):
        """Perform basic validation on configuration."""
        if cls.LLM_PROVIDER not in ["krutrim", "gemini"]:
            logger.warning(f"Unknown LLM_PROVIDER '{cls.LLM_PROVIDER}', defaulting to 'krutrim'")
            cls.LLM_PROVIDER = "krutrim"
        
        # Verify database directory exists
        db_dir = os.path.dirname(cls.DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    @classmethod
    async def load_db_overrides(cls, db):
        """Loads configuration overrides from the database settings table.

        `db` is the injected src.storage.db.Database instance."""
        try:
            # Query LLM Provider
            rows = await db.execute_query("SELECT value FROM settings WHERE key = 'LLM_PROVIDER';")
            if rows:
                cls.LLM_PROVIDER = rows[0]["value"].lower()
                
            # Query Krutrim Model
            rows = await db.execute_query("SELECT value FROM settings WHERE key = 'KRUTRIM_MODEL';")
            if rows:
                cls.KRUTRIM_MODEL = rows[0]["value"]
                
            # Query Selected Mascot
            rows = await db.execute_query("SELECT value FROM settings WHERE key = 'SELECTED_MASCOT';")
            if rows:
                cls.SELECTED_MASCOT = rows[0]["value"]
            else:
                cls.SELECTED_MASCOT = "default"

            # User preferences persisted from the context menu (plan 6.5)
            rows = await db.execute_query("SELECT value FROM settings WHERE key = 'PET_SCALE';")
            if rows:
                cls.ANIMATION_SCALE = float(rows[0]["value"])

            rows = await db.execute_query("SELECT value FROM settings WHERE key = 'MUTED';")
            if rows:
                cls.MUTED = rows[0]["value"] == "1"

            rows = await db.execute_query("SELECT value FROM settings WHERE key = 'REDUCED_MOTION';")
            if rows:
                cls.REDUCED_MOTION = rows[0]["value"] == "1"

            rows = await db.execute_query("SELECT value FROM settings WHERE key = 'SPEECH_TYPING_SPEED_MS';")
            if rows:
                cls.SPEECH_TYPING_SPEED_MS = int(rows[0]["value"])

            cls.validate()
            logger.info(f"Loaded config overrides: Provider={cls.LLM_PROVIDER}, Model={cls.KRUTRIM_MODEL}, Mascot={cls.SELECTED_MASCOT}")
        except Exception as e:
            logger.error(f"Error loading config overrides: {e}")
