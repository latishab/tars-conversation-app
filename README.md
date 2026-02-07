# TARS Omni - Real-time Voice AI

Real-time voice AI with transcription, vision, and intelligent conversation using Speechmatics/Deepgram, Qwen3-TTS/ElevenLabs, Qwen LLM, and Moondream.

## Features

- **Real-time Transcription** - Speechmatics or Deepgram with smart turn detection
- **Dual TTS Options** - Qwen3-TTS (local, free, voice cloning) or ElevenLabs (cloud)
- **LLM Integration** - Qwen or other models via DeepInfra
- **Vision Analysis** - Moondream for image understanding
- **Smart Gating Layer** - AI-powered decision system for natural conversation flow
- **WebRTC Transport** - Low-latency peer-to-peer audio/video
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
├── pipecat_service.py     # FastAPI server
├── bot.py                 # Pipeline orchestration
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
│   └── memory_chromadb.py # Semantic memory
├── modules/               # LLM tools/functions
├── observers/             # Pipeline observers
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

```bash
# Terminal 1: Backend
npm run dev:backend

# Terminal 2: Frontend
npm run dev
```

Open http://localhost:3000

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
