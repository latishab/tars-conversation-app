# TARS Omni - Real-time Voice AI

Real-time voice AI with transcription, vision, and intelligent conversation using Speechmatics, Qwen3-TTS (or ElevenLabs), Qwen LLM, and Moondream.

## Features

- 🎤 **Real-time Transcription** - Speechmatics with speaker diarization
- 🔊 **Dual TTS** - Qwen3-TTS (local, free) or ElevenLabs (cloud)
- 🤖 **LLM** - Qwen via DeepInfra
- 👁️ **Vision** - Moondream image analysis
- 🎯 **Smart Turn Detection** - VAD prevents interruptions
- 🚦 **Gating Layer** - AI decides when to respond
- 🌐 **WebRTC** - Peer-to-peer audio/video
- 🧠 **Memory** - Optional Mem0 long-term memory
- 🎙️ **Voice Cloning** - 3 seconds of audio with Qwen3-TTS
- 😊 **Emotional Monitoring** - Real-time detection of confusion/hesitation/frustration

## Quick Start

### 1. Install Dependencies

```bash
# Python
pip install -r requirements.txt

# Node.js
npm install
```

### 2. Configure

```bash
cp env.example .env.local
# Edit .env.local with your API keys
```

Required keys:
- `SPEECHMATICS_API_KEY`
- `DEEPINFRA_API_KEY`
- `TTS_PROVIDER=qwen3` (or `elevenlabs`)

Optional:
- `ELEVENLABS_API_KEY` (if using cloud TTS)
- `MEM0_API_KEY` (for memory)

### 3. Run

```bash
# Terminal 1: Backend
npm run dev:backend

# Terminal 2: Frontend
npm run dev
```

Open http://localhost:3000

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
├── loggers.py             # Monitoring processors
│
├── config/                # Environment config
├── character/             # TARS personality
├── processors/            # Frame processors
├── services/              # AI services (TTS/STT/LLM)
├── modules/               # LLM tools/functions
├── memory/                # Mem0 integration
└── scripts/               # Utilities
```

## Code Organization

| Type | Location | Purpose |
|------|----------|---------|
| **AI Service** | `services/` | TTS/STT/LLM/Vision integrations |
| **Processor** | `processors/` | Frame processing/filtering |
| **Logger** | `loggers.py` | Monitoring/debugging |
| **LLM Tool** | `modules/` | Functions the LLM can call |
| **Config** | `config/` | Environment variables |
| **Frontend** | `app/` | Next.js React app |

**Key Distinctions**:
- `services/` = AI engines (TTS, STT, LLM)
- `modules/` = LLM-callable functions (backend Python)
- `lib/` = Frontend utilities (TypeScript)
- `processors/` = Data processing
- `loggers.py` = Monitoring/observability

## TTS Configuration

### Qwen3-TTS (Default - Local & Free)

Best for Apple Silicon Macs. Voice cloning with `tars-clean-compressed.mp3`.

**M4 24GB Performance**:
- First load: ~15-20s
- Generation: 2.5-3x real-time
- Memory: ~2-3GB

```env
TTS_PROVIDER=qwen3
QWEN3_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-0.6B-Base
QWEN3_TTS_DEVICE=mps
QWEN3_TTS_REF_AUDIO=tars-clean-compressed.mp3
```

### ElevenLabs (Cloud)

Better quality, requires API key and credits.

```env
TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=your_key
```

## How It Works

1. **Audio/Video Input** → Browser captures via WebRTC
2. **Emotional Monitor** → Analyzes video for confusion/hesitation (every 3s)
3. **VAD** → Detects when user stops speaking
4. **STT** → Speechmatics transcribes with speaker labels
5. **Gating** → AI decides if TARS should respond
6. **LLM** → Qwen processes and generates response
7. **Vision** → Moondream analyzes images when requested
8. **TTS** → Qwen3-TTS or ElevenLabs synthesizes speech
9. **Audio Output** → Streamed back via WebRTC

## Tech Stack

**Frontend**: Next.js 16, React 19, Tailwind, shadcn/ui, WebRTC
**Backend**: Python 3.12, FastAPI, Pipecat.ai, PyTorch
**AI**: Speechmatics, Qwen3-TTS/ElevenLabs, Qwen LLM, Moondream

## Development

### Testing

```bash
python test_qwen_tts.py          # Qwen3-TTS standalone test
python test_qwen_pipecat.py      # Qwen3-TTS Pipecat integration
python test_emotional_monitor.py # Emotional monitoring test
```

### Switching TTS Providers

Edit `.env.local`:
```env
TTS_PROVIDER=elevenlabs  # or qwen3
```

### Voice Cloning

Place audio file in root, update `.env.local`:
```env
QWEN3_TTS_REF_AUDIO=your-voice.mp3
```

### Emotional Monitoring

TARS continuously analyzes your video feed for emotional cues and offers help proactively.

**Detects**:
- 😕 Confusion (puzzled expression, furrowed brow)
- 🤔 Hesitation (pauses, uncertain gestures)
- 😤 Frustration (tense posture, agitated movements)

**Configuration**:
```env
EMOTIONAL_MONITORING_ENABLED=true       # Enable/disable
EMOTIONAL_SAMPLING_INTERVAL=3.0        # Analysis frequency (seconds)
EMOTIONAL_INTERVENTION_THRESHOLD=2     # Consecutive states before help
```

**How it works**:
1. Samples video frames every 3 seconds
2. Moondream analyzes emotional/cognitive state
3. Detects patterns indicating difficulty
4. After 2 consecutive negative states, TARS offers help

**Disable**: Set `EMOTIONAL_MONITORING_ENABLED=false`

## API Endpoints

**Backend (Port 7860)**:
- `POST /api/offer` - WebRTC offer
- `PATCH /api/offer` - ICE candidates
- `GET /api/status` - Health check

**Frontend (Port 3000)**:
- `/` - Main UI
- Proxies to backend

## License

MIT
