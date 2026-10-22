import os
from dotenv import find_dotenv, load_dotenv

# Find .env next to where you start the app (or next to the code), tolerate Notepad's BOM, and let the file win over
# an empty variable that may already exist in the system environment.
ENV_FILE = find_dotenv(usecwd=True) or find_dotenv() or ""
load_dotenv(ENV_FILE or None, override=True, encoding="utf-8-sig")


def _clean(value) -> str:
    return (value or "").strip().strip("\"'").strip()


def _is_placeholder(value: str) -> bool:
    v = value.lower()
    return (not v) or any(p in v for p in ("your_", "your-", "_here", "xxxx"))


class Config:
    # Supabase
    SUPABASE_URL = _clean(os.getenv("SUPABASE_URL"))
    SUPABASE_ANON_KEY = _clean(os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY"))

    # Hugging Face
    HUGGINGFACE_API_KEY = _clean(os.getenv("HUGGINGFACE_API_KEY"))
    HUGGINGFACE_STT_MODEL = _clean(os.getenv("HUGGINGFACE_STT_MODEL")) or "openai/whisper-large-v3-turbo"
    HUGGINGFACE_TTS_MODEL = _clean(os.getenv("HUGGINGFACE_TTS_MODEL")) or "facebook/mms-tts-eng"
    # NOTE: google/vit-base-patch16-224 is an ImageNet classifier (cats, cars...), NOT a sign model.
    HUGGINGFACE_SIGN_MODEL = _clean(os.getenv("HUGGINGFACE_SIGN_MODEL")) or "dima806/asl_alphabet_image_detection"

    # Optional LLM used ONLY to tidy spelling/punctuation of a signed sentence (never to add content)
    HUGGINGFACE_TEXT_MODEL = _clean(os.getenv("HUGGINGFACE_TEXT_MODEL")) or "Qwen/Qwen2.5-7B-Instruct"

    # Post-meeting summary (Gemini is the first choice; Hugging Face text model, then an offline extractive summary, are fallbacks)
    GROQ_API_KEY = _clean(os.getenv("GROQ_API_KEY"))
    GROQ_MODEL = _clean(os.getenv("GROQ_MODEL")) or "llama-3.3-70b-versatile"
    # Groq's free tier has a tokens-per-minute cap, so long transcripts are clipped harder for it.
    GROQ_MAX_TRANSCRIPT_CHARS = int(os.getenv("GROQ_MAX_TRANSCRIPT_CHARS", "20000") or 20000)
    # whisper-large-v3 is the most accurate for Tamil/Indian languages; whisper-large-v3-turbo is faster/cheaper.
    GROQ_STT_MODEL = _clean(os.getenv("GROQ_STT_MODEL")) or "whisper-large-v3"
    GROQ_STT_MAX_MB = float(os.getenv("GROQ_STT_MAX_MB", "24") or 24)     # Groq free tier upload limit is 25 MB
    GEMINI_API_KEY = _clean(os.getenv("GEMINI_API_KEY"))
    GEMINI_MODEL = _clean(os.getenv("GEMINI_MODEL")) or "gemini-3.5-flash"
    # Tried in order when the chosen model answers 404 ("no longer available") - Google retires models regularly.
    GEMINI_FALLBACK_MODELS = [m.strip() for m in (os.getenv("GEMINI_FALLBACK_MODELS") or
                                                  "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-3-flash-preview").split(",") if m.strip()]
    GEMINI_RETRIES = int(os.getenv("GEMINI_RETRIES", "3") or 3)            # extra tries per model on 500/503/504
    GEMINI_RETRY_DELAY = float(os.getenv("GEMINI_RETRY_DELAY", "2") or 2)    # seconds, doubles each retry
    SUMMARY_TEMPERATURE = float(os.getenv("SUMMARY_TEMPERATURE", "0.2") or 0.2)
    SUMMARY_MAX_TRANSCRIPT_CHARS = int(os.getenv("SUMMARY_MAX_TRANSCRIPT_CHARS", "60000") or 60000)

    # Optional: summarize an uploaded meeting RECORDING (Whisper + pyannote, see requirements-audio.txt)
    WHISPER_MODEL = _clean(os.getenv("WHISPER_MODEL")) or "medium"
    VOICEPRINT_DIR = _clean(os.getenv("VOICEPRINT_DIR")) or "data/voiceprints"
    SPEAKER_MATCH_DISTANCE = float(os.getenv("SPEAKER_MATCH_DISTANCE", "0.5") or 0.5)

    # App
    APP_NAME = "Accessible Meeting App"
    TAGLINE = "Communication Without Barriers"
    APP_ENV = os.getenv("APP_ENV", "development")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    ENABLE_VOICE_GUIDANCE_DEFAULT = os.getenv("ENABLE_VOICE_GUIDANCE_DEFAULT", "true").lower() == "true"
    REFRESH_SECONDS = 3  # live-feed polling interval

    # Voice assistant (browser Web Speech API; use Chrome or Edge)
    VOICE_LANG = _clean(os.getenv("VOICE_LANG")) or "en-US"
    VOICE_RATE = float(os.getenv("VOICE_RATE", "1.0") or 1.0)      # 0.8 slow ... 1.6 fast
    VOICE_POLL_SECONDS = 2                                          # how often new meeting messages are announced

    # Sign detection (single photo)
    SIGN_CONFIDENCE_THRESHOLD = 0.65
    SIGN_COOLDOWN_SECONDS = 2.0

    # Sign detection (live stream -> letters -> words -> sentence)
    SIGN_LIVE_MIN_CONFIDENCE = float(os.getenv("SIGN_LIVE_MIN_CONFIDENCE", "0.70") or 0.70)
    SIGN_STABLE_FRAMES = int(os.getenv("SIGN_STABLE_FRAMES", "2") or 2)       # same letter N frames in a row
    SIGN_REPEAT_HOLD_SECONDS = 2.5      # hold one letter this long to type it twice (e.g. the LL in HELLO)
    SIGN_WORD_PAUSE_SECONDS = 2.0       # hands down this long -> word finished
    SIGN_SENTENCE_PAUSE_SECONDS = 4.5   # hands down this long -> sentence finished and sent
    SIGN_LIVE_SENTENCE_PAUSE_SECONDS = float(os.getenv("SIGN_LIVE_SENTENCE_PAUSE_SECONDS", "3.0") or 3.0)  # hands down this long -> live-word sentence is sent
    SIGN_FRAME_INTERVAL_MS = int(os.getenv("SIGN_FRAME_INTERVAL_MS", "600") or 600)
    SIGN_SKIN_MIN = float(os.getenv("SIGN_SKIN_MIN", "0.06") or 0.06)   # min. share of skin-coloured pixels to count as "hand in frame" (0 = off)
    SIGN_USE_LOCAL_MODEL = os.getenv("SIGN_USE_LOCAL_MODEL", "false").lower() == "true"  # needs transformers+torch

    # Live video meeting (WebRTC). STUN is enough on most home / office networks. Behind strict firewalls add a TURN server:
    # TURN_URL=turn:your.server:3478  TURN_USERNAME=...  TURN_PASSWORD=...
    TURN_URL = _clean(os.getenv("TURN_URL"))
    TURN_USERNAME = _clean(os.getenv("TURN_USERNAME"))
    TURN_PASSWORD = _clean(os.getenv("TURN_PASSWORD"))

    @classmethod
    def ice_servers(cls):
        servers = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]
        if cls.TURN_URL:
            servers.append({"urls": [cls.TURN_URL], "username": cls.TURN_USERNAME, "credential": cls.TURN_PASSWORD})
        return servers

    @classmethod
    def is_supabase_configured(cls) -> bool:
        return bool(cls.SUPABASE_URL and cls.SUPABASE_ANON_KEY
                    and not _is_placeholder(cls.SUPABASE_URL) and not _is_placeholder(cls.SUPABASE_ANON_KEY))

    @classmethod
    def is_groq_configured(cls) -> bool:
        return bool(cls.GROQ_API_KEY and not _is_placeholder(cls.GROQ_API_KEY))

    @classmethod
    def is_gemini_configured(cls) -> bool:
        return bool(cls.GEMINI_API_KEY and not _is_placeholder(cls.GEMINI_API_KEY))

    @classmethod
    def is_huggingface_configured(cls) -> bool:
        return bool(cls.HUGGINGFACE_API_KEY and not _is_placeholder(cls.HUGGINGFACE_API_KEY))
