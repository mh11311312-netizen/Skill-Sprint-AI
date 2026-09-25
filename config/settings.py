"""Central configuration. Secrets come from the .env file (never commit .env)."""
import os
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB = os.getenv("MONGO_DB", "skillsprint")
    USE_MONGOMOCK = os.getenv("USE_MONGOMOCK", "0") == "1"   # in-memory DB for tests only

    # Which GenAI provider to use: "openai" or "gemini"
    GENAI_PROVIDER = os.getenv("GENAI_PROVIDER", "openai").strip().lower()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    GENAI_TIMEOUT_SECONDS = int(os.getenv("GENAI_TIMEOUT_SECONDS", "180"))
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    GENAI_TEMPERATURE = float(os.getenv("GENAI_TEMPERATURE", "0.2"))
    GENAI_MAX_RETRIES = int(os.getenv("GENAI_MAX_RETRIES", "3"))

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024          # 10 MB upload limit
    ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "md"}
    WTF_CSRF_ENABLED = True
