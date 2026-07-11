import os
from dotenv import load_dotenv
from src.constants import DEFAULT_DB_PATH

# Load environment variables from .env
load_dotenv()

class Config:
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "krutrim").lower()
    
    # Gemini API Settings
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # Krutrim API Settings
    KRUTRIM_API_KEY = os.getenv("KRUTRIM_API_KEY", "")
    KRUTRIM_MODEL = os.getenv("KRUTRIM_MODEL", "Qwen/Qwen2.5-14B-Instruct")
    
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
    
    # Mascot Settings
    SELECTED_MASCOT = "default"
    
    @classmethod
    def validate(cls):
        """Perform basic validation on configuration."""
        if cls.LLM_PROVIDER not in ["krutrim"]:
            print(f"Warning: Unknown LLM_PROVIDER '{cls.LLM_PROVIDER}', defaulting to 'krutrim'")
            cls.LLM_PROVIDER = "krutrim"
        
        # Verify database directory exists
        db_dir = os.path.dirname(cls.DB_PATH)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

    @classmethod
    async def load_db_overrides(cls):
        """Loads configuration overrides from the database settings table."""
        from src.storage.db import Database
        db = Database.get_instance()
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
                
            cls.validate()
            print(f"Loaded config overrides: Provider={cls.LLM_PROVIDER}, Model={cls.KRUTRIM_MODEL}, Mascot={cls.SELECTED_MASCOT}")
        except Exception as e:
            print(f"Error loading config overrides: {e}")
