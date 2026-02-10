# TARS Omni - Real-time Voice AI

Real-time voice AI with transcription, vision, and intelligent conversation using Speechmatics/Deepgram, Qwen3-TTS/ElevenLabs, Qwen LLM, and Moondream.

**NEW**: ✅ Robot Mode - Connect to Raspberry Pi TARS robot via WebRTC for hardware interaction! (Phase 1 Complete)

## Features

- **Dual Mode Operation**
  - **Browser Mode** - Real-time voice AI in your browser
  - **Robot Mode** - Connect to Raspberry Pi TARS robot via WebRTC ✅ *(Phase 1 Complete)*
- **Real-time Transcription** - Speechmatics or Deepgram with smart turn detection
- **Dual TTS Options** - Qwen3-TTS (local, free, voice cloning) or ElevenLabs (cloud)
- **LLM Integration** - Qwen or other models via DeepInfra
- **Vision Analysis** - Moondream for image understanding
- **Smart Gating Layer** - AI-powered decision system for natural conversation flow
- **WebRTC Transport** - Low-latency peer-to-peer audio/video
- **Semantic Memory** - ChromaDB for conversation context and recall
- **Emotional Monitoring** - Real-time detection of confusion, hesitation, and frustration
- **Robot Control** - Movement, camera, and display integration *(Robot Mode)*
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
├── tars_bot.py            # Robot Mode entry point ✨ NEW
├── bot.py                 # Pipeline orchestration
│
├── transport/             # WebRTC transport layer ✨ NEW
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
│   └── tars_client.py    # RPi HTTP client
├── modules/               # LLM tools/functions
├── observers/             # Pipeline observers
│   ├── state_observer.py # WebRTC state sync ✨ NEW
│   └── ...
└── scripts/               # Utilities
```

## Quick Start

### 1. Install Dependencies

```bash
# Python dependencies
pip install -r requirements.txt

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

**Required API Keys** (in `.env.local`):
- `SPEECHMATICS_API_KEY` or `DEEPGRAM_API_KEY` - For speech-to-text
- `DEEPINFRA_API_KEY` - For LLM
- `ELEVENLABS_API_KEY` - Optional (if using ElevenLabs TTS)

**Settings** (in `config.ini`):
```ini
[LLM]
model = openai/gpt-oss-20b

[STT]
provider = speechmatics  # or deepgram, deepgram-flux

[TTS]
provider = qwen3  # or elevenlabs
```

### 3. Run

#### Browser Mode (Default)

```bash
# Terminal 1: Backend
npm run dev:backend

# Terminal 2: Frontend
npm run dev
```

Open http://localhost:3000

#### Robot Mode (New - Requires Raspberry Pi TARS)

**Prerequisites:**
- Raspberry Pi TARS robot running (see [tars repository](https://github.com/your-org/tars))
- Network connection to RPi (LAN or Tailscale)

**Configuration:**
Edit `config.ini`:
```ini
[Connection]
mode = robot
rpi_url = http://<your-rpi-ip>:8001
auto_connect = true
```

**Run:**
```bash
# Test connection first (optional)
python test_webrtc_connection.py

# Start robot mode
python tars_bot.py

# Or use the helper script
./start_robot_mode.sh
```

**Status**: ✅ Phase 1 complete - Full audio bridge integrated and ready to test!

For full robot mode documentation, see:
- `TARS_ARCHITECTURE_PLAN_V6.md` - Complete architecture
- `IMPLEMENTATION_SUMMARY.md` - Current implementation status
- `PHASE1_IMPLEMENTATION.md` - Phase 1 details

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Run tests if applicable
5. Commit with clear messages
6. Push to your fork
7. Open a Pull Request

### Code Style

- Python: Follow PEP 8
- TypeScript: Use existing ESLint configuration
- Add comments for complex logic
- Update documentation for new features

## License

MIT License - see LICENSE file for details
