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
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_MODEL = os.getenv("DEEPINFRA_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507")
DEEPINFRA_GATING_MODEL = os.getenv("DEEPINFRA_GATING_MODEL", "meta-llama/Llama-3.2-3B-Instruct")
PIPECAT_PORT = int(os.getenv("PIPECAT_PORT", "7860"))
PIPECAT_HOST = os.getenv("PIPECAT_HOST", "localhost")

# Mem0 (optional)
MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")

