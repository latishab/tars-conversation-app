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

**Robot mode** (`src/tars_bot.py`) — connects to RPi over WebRTC + gRPC. Controls eyes, gestures, and movement.

**Browser mode** (`src/bot.py`) — browser mic/speaker via SmallWebRTC. Includes hybrid memory and Gradio dashboard.

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
1. Open `http://tars.local:8000` → Apps tab → Install
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

## Run

```bash
# Robot mode (requires Pi running tars_daemon.py)
python src/tars_bot.py

# Browser mode
python src/pipecat_service.py
```

## Configuration

`config.ini` — runtime settings (provider, model, connection):
```ini
[LLM]
provider = cerebras
model = gpt-oss-120b

[STT]
provider = deepgram

[TTS]
provider = elevenlabs

[Connection]
connection_type = local   # local | manual | tailscale
auto_connect = true
```

`.env.local` — API keys:
```
CEREBRAS_API_KEY=
DEEPGRAM_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
DEEPINFRA_API_KEY=
GEMINI_API_KEY=
```

## Robot Connection

| Type | How |
|------|-----|
| `local` | `tars.local` via mDNS (default) |
| `manual` | Direct IP — set `rpi_ip` in config.ini |
| `tailscale` | Tailscale MagicDNS hostname `tars` |

If mDNS fails: `ssh tars-pi "hostname -I"` then set `connection_type = manual`.

## Project Structure

```
src/
├── tars_bot.py          # Robot mode entry point
├── bot.py               # Browser mode entry point
├── character/           # TARS persona and prompts
├── processors/          # Pipeline filters (silence, express tags, reasoning)
├── services/            # STT/TTS/LLM factories, memory, robot client
├── tools/               # LLM-callable tools (robot, vision, persona)
├── transport/           # aiortc WebRTC client
└── ui/                  # Gradio metrics dashboard
```

## Docs

- [Installation](docs/INSTALLATION_GUIDE.md)
- [App Development](docs/DEVELOPING_APPS.md)
- [Daemon Integration](docs/DAEMON_INTEGRATION.md)

## License

MIT
