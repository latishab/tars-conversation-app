# TARS Omni - Real-time Voice AI

Real-time voice AI with transcription, vision, and intelligent conversation using Speechmatics/Deepgram, Qwen3-TTS/ElevenLabs, DeepInfra LLM, and Moondream.

## Features

- **Dual Mode Operation**
  - **Browser Mode** - Real-time voice AI in your browser
  - **Robot Mode** - Connect to Raspberry Pi TARS robot via WebRTC and gRPC
- **Real-time Transcription** - Speechmatics or Deepgram with smart turn detection
- **Dual TTS Options** - Qwen3-TTS (local, free, voice cloning) or ElevenLabs (cloud)
- **LLM Integration** - Any model via DeepInfra
- **Vision Analysis** - Moondream for image understanding
- **Smart Gating Layer** - AI-powered decision system for natural conversation flow
- **WebRTC Transport** - Low-latency peer-to-peer audio
- **gRPC Robot Control** - Hardware control with 5-10ms latency
- **Semantic Memory** - ChromaDB for conversation context and recall
- **Emotional Monitoring** - Real-time detection of confusion, hesitation, and frustration
- **Configurable** - Switch models and providers via web UI or config file

## Project Structure

```
tars-omni/
├── app/                    # Next.js frontend
│   ├── api/               # API routes
│   ├── components/        # React components
│   └── page.tsx           # Main UI
│
├── pipecat_service.py     # FastAPI server (Browser Mode)
├── tars_bot.py            # Robot Mode entry point
├── bot.py                 # Pipeline orchestration
│
├── transport/             # WebRTC transport layer
│   ├── aiortc_client.py  # WebRTC client for RPi
│   ├── audio_bridge.py   # Audio format conversion
│   └── state_sync.py     # DataChannel state sync
│
├── config/                # Environment config
├── character/             # TARS personality
├── processors/            # Frame processors
│   ├── emotional_monitor.py  # Real-time emotion detection
│   ├── gating.py         # Intervention decision system
│   ├── visual_observer.py    # Vision analysis
│   └── filters.py        # Audio filtering
├── services/              # AI services
│   ├── factories/        # Service factories (STT/TTS)
│   ├── tts_qwen.py       # Local voice cloning
│   ├── memory_chromadb.py # Semantic memory
│   └── tars_robot.py     # gRPC robot control
├── tools/                 # LLM callable functions
│   ├── robot.py          # Robot hardware control
│   ├── persona.py        # Identity and personality
│   ├── vision.py         # Vision analysis
│   └── crossword.py      # Game-specific utilities
├── observers/             # Pipeline observers
│   ├── state_observer.py # WebRTC state sync
│   └── ...
└── scripts/               # Utilities
```

## Quick Start

### 1. Install Dependencies

```bash
# Python dependencies
pip install -r requirements.txt

# Install TARS SDK (for robot mode)
pip install -e ../tars

# Node.js dependencies
npm install
```

### 2. Configure Environment

```bash
# Copy and edit environment file with your API keys
cp env.example .env.local

# Copy and edit configuration file
cp config.ini.example config.ini
```

Required API Keys (in `.env.local`):
- `SPEECHMATICS_API_KEY` or `DEEPGRAM_API_KEY` - For speech-to-text
- `DEEPINFRA_API_KEY` - For LLM
- `ELEVENLABS_API_KEY` - Optional (if using ElevenLabs TTS)

Settings (in `config.ini`):
```ini
[LLM]
model = openai/gpt-oss-20b

[STT]
provider = deepgram  # or speechmatics, deepgram-flux

[TTS]
provider = qwen3  # or elevenlabs
```

### 3. Run

#### Browser Mode

```bash
# Terminal 1: Backend
npm run dev:backend

# Terminal 2: Frontend
npm run dev
```

Open http://localhost:3000

#### Robot Mode

Prerequisites:
- Raspberry Pi TARS robot running with tars_daemon.py
- Network connection to RPi (LAN or Tailscale)
- TARS SDK installed

Configuration in `config.ini`:
```ini
[Connection]
mode = robot
rpi_url = http://<your-rpi-ip>:8001
rpi_grpc = <your-rpi-ip>:50051
auto_connect = true

[Display]
enabled = true
```

Deployment modes:
- **Remote** (Mac/computer): Uses configured addresses
- **Local** (on RPi): Automatically detects and uses localhost:50051

Run:
```bash
python tars_bot.py
```

## Architecture

Robot mode uses two communication channels:

| Channel | Protocol | Purpose | Latency |
|---------|----------|---------|---------|
| Audio | WebRTC (aiortc) | Voice conversation | ~20ms |
| Commands | gRPC | Hardware control | ~5-10ms |

Audio flow:
```
RPi Mic → WebRTC → Pipecat Pipeline → WebRTC → RPi Speaker
                   ↓
                   STT → LLM → TTS
                          ↓
                    gRPC commands → RPi servos/display
```

## Contributing

Contributions are welcome.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests if applicable
5. Commit with clear messages
6. Push to your fork
7. Open a Pull Request

Code Style:
- Python: Follow PEP 8
- TypeScript: Use existing ESLint configuration
- Add comments for complex logic
- Update documentation for new features
- See CLAUDE.md for documentation style guidelines

## License

MIT License - see LICENSE file for details
