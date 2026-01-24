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

# TTS Configuration
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "qwen3")  # Options: "elevenlabs" or "qwen3"
QWEN3_TTS_MODEL = os.getenv("QWEN3_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
QWEN3_TTS_DEVICE = os.getenv("QWEN3_TTS_DEVICE", "mps")  # "mps" for Mac, "cuda" for GPU
QWEN3_TTS_REF_AUDIO = os.getenv("QWEN3_TTS_REF_AUDIO", "tars-clean-compressed.mp3")

# Emotional State Monitoring
EMOTIONAL_MONITORING_ENABLED = os.getenv("EMOTIONAL_MONITORING_ENABLED", "true").lower() == "true"
EMOTIONAL_SAMPLING_INTERVAL = float(os.getenv("EMOTIONAL_SAMPLING_INTERVAL", "3.0"))  # seconds
EMOTIONAL_INTERVENTION_THRESHOLD = int(os.getenv("EMOTIONAL_INTERVENTION_THRESHOLD", "2"))  # consecutive states

