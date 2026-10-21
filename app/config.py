import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_REASONING_EFFORT = os.getenv("GROQ_REASONING_EFFORT", "low")
GROQ_TIMEOUT = float(os.getenv("GROQ_TIMEOUT", "30"))
GROQ_MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "1200"))
GROQ_MAX_RETRIES = int(os.getenv("GROQ_MAX_RETRIES", "1"))

PHOTO_ENABLED = os.getenv("PHOTO_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
PHOTO_TIMEOUT = float(os.getenv("PHOTO_TIMEOUT", "4"))
PHOTO_CACHE_TTL = int(os.getenv("PHOTO_CACHE_TTL", "3600"))
PHOTO_FAILURE_TTL = int(os.getenv("PHOTO_FAILURE_TTL", "600"))
PHOTO_USER_AGENT = os.getenv(
    "PHOTO_USER_AGENT",
    "QuickChef/1.0 (https://github.com/quickchef-demo; quickchef-demo@users.noreply.github.com)",
)

CATALOG_PATH = BASE_DIR / "data" / "catalog.json"

FEEDBACK_ENABLED = os.getenv("FEEDBACK_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
FEEDBACK_PATH = Path(
    os.getenv("FEEDBACK_PATH", str(BASE_DIR / "evals" / "golden" / "feedback.jsonl"))
)

DELIVERY_FEE = float(os.getenv("DELIVERY_FEE", "25"))
FREE_DELIVERY_ABOVE = float(os.getenv("FREE_DELIVERY_ABOVE", "199"))
HANDLING_FEE = float(os.getenv("HANDLING_FEE", "9"))

LLM_ENABLED = bool(GROQ_API_KEY)

LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "quickchef")
_TRACING_FLAG = os.getenv("LANGSMITH_TRACING", "").strip().lower() in ("1", "true", "yes", "on")
LANGSMITH_ENABLED = _TRACING_FLAG and bool(os.getenv("LANGSMITH_API_KEY", "").strip())

# langsmith reads these from the environment at run time. Make the project default
# available, and force tracing off when there is no usable key (avoids 401 spam).
os.environ.setdefault("LANGSMITH_PROJECT", LANGSMITH_PROJECT)
if LANGSMITH_ENABLED:
    os.environ["LANGSMITH_TRACING"] = "true"
else:
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ.pop("LANGCHAIN_TRACING_V2", None)
