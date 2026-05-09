import os

# Voice Configuration for Piper TTS

DEFAULT_MODEL = "pt_BR-faber-medium"
MAX_TEXT_LENGTH = 5000

# CORS Origins
raw_origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000,*")
CORS_ORIGINS = [origin.strip() for origin in raw_origins.split(",")]
