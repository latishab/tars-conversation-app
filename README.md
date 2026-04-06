---
title: TARS Conversation App
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: static
short_description: Real-time AI voice assistant for TARS
pinned: false
---

> **FYP Project 25CS048** | Latisha Besariani Hendra | Supervisor: Prof. Shengdong Zhao
> Department of Computer Science, City University of Hong Kong

# TARS Conversation App

Real-time voice AI brain for the TARS robot. Connects to a Raspberry Pi hardware daemon via WebRTC and gRPC.

## Modes

**Robot mode** (`src/tars_bot.py`) -- connects to RPi over WebRTC + gRPC. Controls eyes, gestures, and movement.

**Browser mode** (`src/bot.py`) -- browser mic/speaker via SmallWebRTC. Includes hybrid memory and Gradio dashboard.

## Stack

| Layer | Options |
|-------|---------|
| STT | Deepgram, Speechmatics, Soniox |
| LLM | Cerebras, Gemini, DeepInfra (any OpenAI-compatible) |
| TTS | ElevenLabs, Qwen3-TTS (local) |
| Vision | Moondream (local), DeepInfra Qwen-VL |
| Memory | SQLite hybrid search (70% vector + 30% BM25) |

## Quick Start

**Via TARS daemon dashboard:**
1. Open `http://tars.local:8000` -> Apps tab -> Install
2. Configure API keys in `.env.local`
3. Click Start

**Manual:**
```bash
git clone https://github.com/latishab/tars-conversation-app.git
cd tars-conversation-app
bash install.sh
cp env.example .env.local   # add API keys
cp config.ini.example config.ini
```

## Requirements

- Python 3.10+
- macOS (Apple Silicon) or Linux for AI host
- Raspberry Pi 5 for robot hardware
- System packages: `portaudio19-dev`, `ffmpeg`
- API keys: see `env.example` for all options

## Run

```bash
# Robot mode (requires Pi running tars_daemon.py)
python src/tars_bot.py

# Browser mode
python src/pipecat_service.py
```

See [Running TARS](docs/RUN.md) for Gradio UI, split routing, and troubleshooting.

## Docs

- [Installation](docs/INSTALLATION_GUIDE.md) -- full install steps, connection setup, systemd service
- [Running TARS](docs/RUN.md) -- run modes, Gradio UI, split routing, troubleshooting
- [Configuration](docs/CONFIGURATION.md) -- config.ini and .env.local reference
- [Architecture](docs/ARCHITECTURE.md) -- pipeline, processors, observers, tools
- [Persona](docs/PERSONA.md) -- character customization and personality parameters
- [App Development](docs/DEVELOPING_APPS.md) -- building apps with the TARS SDK
- [Daemon Integration](docs/DAEMON_INTEGRATION.md) -- how the Pi daemon manages apps

## License

MIT
