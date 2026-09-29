"""Configuration. Services read values via `import config as cfg` so tests can override them."""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # optional; env vars can be set directly
    pass


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


DB_PATH = os.getenv("DB_PATH", "incidentmind.db")

# Hindsight (Vectorize). Real Hindsight is the default. The local store only runs if you opt in.
HINDSIGHT_BASE_URL = os.getenv("HINDSIGHT_BASE_URL", "")
HINDSIGHT_API_KEY = os.getenv("HINDSIGHT_API_KEY", "")
HINDSIGHT_BANK_ID = os.getenv("HINDSIGHT_BANK_ID", "incidentmind-demo")
USE_LOCAL_FALLBACK = _flag("USE_LOCAL_FALLBACK", False)
STALE_DAYS = int(os.getenv("STALE_DAYS", "90"))

# LLM (Groq). Without a key the backend uses a deterministic mock so the UI still works.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "qwen/qwen3-32b")
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "2"))

CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
