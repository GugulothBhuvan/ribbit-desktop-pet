import os
from dotenv import load_dotenv
from src.constants import DEFAULT_DB_PATH, DEFAULT_PET_NAME, DEFAULT_PET_PERSONA
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
    
    # Deepgram Voice API (speech-to-text AND text-to-speech / Aura)
    DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

    # Text-to-speech: the pet speaks its replies aloud. Only conversational
    # replies (you spoke to it) and canned voice-flow lines are spoken; ambient
    # screen comments stay text-only.
    TTS_ENABLED = os.getenv("TTS_ENABLED", "1") == "1"
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "sarvam").lower()  # sarvam | deepgram
    TTS_VOICE = os.getenv("TTS_VOICE", "aura-asteria-en")  # Deepgram Aura model

    # Sarvam AI (Bulbul) TTS — real Indian-English voices, matching the persona.
    SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
    # Verified live 2026-07-17: bulbul:v1 is retired (API accepts only v2/v3);
    # v3 rejects the v2 speaker roster. v2 + 'karun' returns 22050Hz mono PCM.
    SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "karun")
    SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v2")
    SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "en-IN")
    SARVAM_TTS_SAMPLE_RATE = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "22050"))
    
    # Local Database
    DB_PATH = os.getenv("DB_PATH", DEFAULT_DB_PATH)
    
    # UI Configurations
    ANIMATION_SCALE = float(os.getenv("ANIMATION_SCALE", "1.0"))
    PET_VOLUME = float(os.getenv("PET_VOLUME", "0.8"))
    SPEECH_TYPING_SPEED_MS = int(os.getenv("SPEECH_TYPING_SPEED_MS", "40"))
    SPEECH_BUBBLE_COOLDOWN_SEC = int(os.getenv("SPEECH_BUBBLE_COOLDOWN_SEC", "10"))

    # Global push-to-talk hotkey (e.g. "ctrl+space", "ctrl+alt+j").
    # NOTE: "ctrl+space" is also IDE autocomplete — a global binding shadows it
    # everywhere. Change this if that bothers you.
    PTT_HOTKEY = os.getenv("PTT_HOTKEY", "ctrl+space")

    # Local wake word (opt-in — this turns the mic ON continuously, processed
    # entirely on-device via openWakeWord; audio only leaves the machine after
    # the phrase triggers a recording). Off by default to preserve the "mic is
    # off until you act" privacy posture.
    WAKE_WORD_ENABLED = os.getenv("WAKE_WORD_ENABLED", "0") == "1"
    WAKE_WORD_MODEL = os.getenv("WAKE_WORD_MODEL", "hey_jarvis")  # openWakeWord builtin
    WAKE_WORD_RECORD_SEC = float(os.getenv("WAKE_WORD_RECORD_SEC", "5"))
    WAKE_WORD_THRESHOLD = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
    
    # Hands-free conversation mode: trigger once (Ctrl+Space), then just talk.
    # VAD (Silero, bundled with openWakeWord) auto-detects when you stop speaking,
    # the pet replies (text + voice), and the mic reopens for the next turn until
    # you go silent past the idle timeout or press the hotkey again.
    CONVERSATION_MODE = os.getenv("CONVERSATION_MODE", "1") == "1"
    CONVERSATION_VAD_THRESHOLD = float(os.getenv("CONVERSATION_VAD_THRESHOLD", "0.5"))
    CONVERSATION_ENDPOINT_MS = int(os.getenv("CONVERSATION_ENDPOINT_MS", "800"))       # silence that ends a turn
    CONVERSATION_IDLE_TIMEOUT_SEC = float(os.getenv("CONVERSATION_IDLE_TIMEOUT_SEC", "12"))  # no speech -> end session
    CONVERSATION_MAX_UTTERANCE_SEC = float(os.getenv("CONVERSATION_MAX_UTTERANCE_SEC", "15"))
    CONVERSATION_MIN_SPEECH_MS = int(os.getenv("CONVERSATION_MIN_SPEECH_MS", "200"))   # ignore shorter blips

    # Desktop agent: let voice commands drive the OS (open apps, URLs, search;
    # later keyboard/mouse/vision). OFF by default — this hands an LLM the
    # keyboard, so it must be a deliberate opt-in. Risky actions always confirm.
    AGENT_ENABLED = os.getenv("AGENT_ENABLED", "0") == "1"
    AGENT_CONFIRM_RISKY = os.getenv("AGENT_CONFIRM_RISKY", "1") == "1"
    # ReAct loop (observe->reason->act until done). The riskiest capability — it
    # acts autonomously — so it's a SEPARATE opt-in on top of AGENT_ENABLED, with
    # a hard step cap. Requires a vision-capable model.
    AGENT_REACT_ENABLED = os.getenv("AGENT_REACT_ENABLED", "0") == "1"
    AGENT_REACT_MAX_STEPS = int(os.getenv("AGENT_REACT_MAX_STEPS", "6"))
    # Extra app launchers as "name=command" pairs, comma-separated, merged onto
    # the built-in allowlist. e.g. "slack=slack,steam=steam"
    AGENT_EXTRA_APPS = os.getenv("AGENT_EXTRA_APPS", "")

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

    # Persona — the character the pet plays. Fully customizable via .env so the
    # pet's name, species, tone and quirks live in config, not in code.
    PET_NAME = os.getenv("PET_NAME", DEFAULT_PET_NAME)
    PET_PERSONA = os.getenv("PET_PERSONA", DEFAULT_PET_PERSONA)

    # Accessibility / behavior toggles (persisted in the settings table)
    MUTED = False
    REDUCED_MOTION = False  # "Calm mode": pet stays idle, no wandering/napping
    
    @classmethod
    def validate(cls):
        """Perform basic validation on configuration."""
        if cls.LLM_PROVIDER not in ["krutrim", "gemini"]:
            logger.warning(f"Unknown LLM_PROVIDER '{cls.LLM_PROVIDER}', defaulting to 'krutrim'")
            cls.LLM_PROVIDER = "krutrim"

        if cls.TTS_PROVIDER not in ["sarvam", "deepgram"]:
            logger.warning(f"Unknown TTS_PROVIDER '{cls.TTS_PROVIDER}', defaulting to 'sarvam'")
            cls.TTS_PROVIDER = "sarvam"
        
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
