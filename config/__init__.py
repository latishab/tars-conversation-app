"""Configuration and constants for the Pipecat service."""

import os
import configparser
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env.local first, then .env
load_dotenv('.env.local')
load_dotenv()  # Also load from .env if .env.local doesn't exist

# Load config.ini for user-configurable settings
config = configparser.ConfigParser()
config_path = Path(__file__).parent.parent / 'config.ini'

def reload_config():
    """Reload configuration from config.ini."""
    global config
    config = configparser.ConfigParser()
    if config_path.exists():
        config.read(config_path)
        return True
    return False

def get_fresh_config():
    """Get fresh configuration values by reloading config.ini.

    Returns a dict with current config values. This is useful for
    getting runtime updates without restarting the service.
    """
    reload_config()
    return {
        'DEEPINFRA_MODEL': get_config("LLM", "model", "DEEPINFRA_MODEL", "openai/gpt-oss-20b"),
        'DEEPINFRA_GATING_MODEL': get_config("LLM", "gating_model", "DEEPINFRA_GATING_MODEL", "meta-llama/Llama-3.2-3B-Instruct"),
        'STT_PROVIDER': get_config("STT", "provider", "STT_PROVIDER", "speechmatics"),
        'TTS_PROVIDER': get_config("TTS", "provider", "TTS_PROVIDER", "qwen3"),
        'QWEN3_TTS_MODEL': get_config("TTS", "qwen3_model", "QWEN3_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base"),
        'QWEN3_TTS_DEVICE': get_config("TTS", "qwen3_device", "QWEN3_TTS_DEVICE", "mps"),
        'QWEN3_TTS_REF_AUDIO': get_config("TTS", "qwen3_ref_audio", "QWEN3_TTS_REF_AUDIO", "tars-clean-compressed.mp3"),
        'EMOTIONAL_MONITORING_ENABLED': get_config("Emotional", "enabled", "EMOTIONAL_MONITORING_ENABLED", "true").lower() == "true",
        'EMOTIONAL_SAMPLING_INTERVAL': float(get_config("Emotional", "sampling_interval", "EMOTIONAL_SAMPLING_INTERVAL", "3.0")),
        'EMOTIONAL_INTERVENTION_THRESHOLD': int(get_config("Emotional", "intervention_threshold", "EMOTIONAL_INTERVENTION_THRESHOLD", "2")),
        'TARS_DISPLAY_URL': get_config("Display", "tars_url", "TARS_DISPLAY_URL", "http://100.64.0.0:8001"),
        'TARS_DISPLAY_ENABLED': get_config("Display", "enabled", "TARS_DISPLAY_ENABLED", "false").lower() == "true",
    }

# Initial load
if config_path.exists():
    config.read(config_path)

def get_config(section: str, key: str, env_key: str = None, default: str = "") -> str:
    """Get config from config.ini, fallback to .env, then default."""
    try:
        if config.has_option(section, key):
            return config.get(section, key)
    except:
        pass

    return default

# API Keys (always from .env for security)
SPEECHMATICS_API_KEY = os.getenv("SPEECHMATICS_API_KEY", "")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "ry8mpwRw6nugb2qjP0tu")
DEEPINFRA_API_KEY = os.getenv("DEEPINFRA_API_KEY", "")
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
PIPECAT_PORT = int(os.getenv("PIPECAT_PORT", "7860"))
PIPECAT_HOST = os.getenv("PIPECAT_HOST", "localhost")

# Mem0 (optional)
MEM0_API_KEY = os.getenv("MEM0_API_KEY", "")

# LLM Configuration (config.ini with .env fallback)
DEEPINFRA_MODEL = get_config("LLM", "model", "DEEPINFRA_MODEL", "openai/gpt-oss-20b")

# STT Configuration (config.ini with .env fallback)
# Options: "speechmatics", "deepgram", "deepgram-flux"
STT_PROVIDER = get_config("STT", "provider", "STT_PROVIDER", "deepgram-flux")

# TTS Configuration (config.ini with .env fallback)
TTS_PROVIDER = get_config("TTS", "provider", "TTS_PROVIDER", "qwen3")
QWEN3_TTS_MODEL = get_config("TTS", "qwen3_model", "QWEN3_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
QWEN3_TTS_DEVICE = get_config("TTS", "qwen3_device", "QWEN3_TTS_DEVICE", "mps")
QWEN3_TTS_REF_AUDIO = get_config("TTS", "qwen3_ref_audio", "QWEN3_TTS_REF_AUDIO", "tars-clean-compressed.mp3")

# Gating Model Configuration (config.ini with .env fallback)
DEEPINFRA_GATING_MODEL = get_config("LLM", "gating_model", "DEEPINFRA_GATING_MODEL", "meta-llama/Llama-3.2-3B-Instruct")

# Emotional State Monitoring (config.ini with .env fallback)
EMOTIONAL_MONITORING_ENABLED = get_config("Emotional", "enabled", "EMOTIONAL_MONITORING_ENABLED", "true").lower() == "true"
EMOTIONAL_SAMPLING_INTERVAL = float(get_config("Emotional", "sampling_interval", "EMOTIONAL_SAMPLING_INTERVAL", "3.0"))
EMOTIONAL_INTERVENTION_THRESHOLD = int(get_config("Emotional", "intervention_threshold", "EMOTIONAL_INTERVENTION_THRESHOLD", "2"))

# TARS Display (Raspberry Pi) Configuration
TARS_DISPLAY_URL = get_config("Display", "tars_url", "TARS_DISPLAY_URL", "http://100.64.0.0:8001")
TARS_DISPLAY_ENABLED = get_config("Display", "enabled", "TARS_DISPLAY_ENABLED", "false").lower() == "true"

