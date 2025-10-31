"""Configuration and constants for the Pipecat service."""

import os
from dotenv import load_dotenv

# Load environment variables from .env.local first, then .env
load_dotenv('.env.local')
load_dotenv()  # Also load from .env if .env.local doesn't exist

# API Keys
SPEECHMATICS_API_KEY = os.getenv("SPEECHMATICS_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "ry8mpwRw6nugb2qjP0tu")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen-flash")
PIPECAT_PORT = int(os.getenv("PIPECAT_PORT", "7860"))
PIPECAT_HOST = os.getenv("PIPECAT_HOST", "localhost")

