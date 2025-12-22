# TARS Omni - Real-time Voice AI

A Next.js application that provides real-time voice AI with transcription, vision capabilities, and intelligent conversation using Speechmatics, ElevenLabs, Qwen LLM, and Moondream, integrated with pipecat.ai and SmallWebRTC for peer-to-peer real-time audio/video processing.

## Features

- 🎤 **Real-time Transcription**: Live audio transcription using Speechmatics with speaker diarization
- 🔊 **Text-to-Speech**: Natural voice synthesis using ElevenLabs Flash model
- 🤖 **LLM Integration**: Conversational AI powered by Qwen models via DeepInfra
- 👁️ **Vision Capabilities**: Image analysis using Moondream vision service
- 🎯 **Smart Turn Detection**: Prevents interruptions with VAD and Smart Turn Detection
- 🚦 **Intelligent Gating Layer**: AI-powered decision system that determines when TARS should respond
- 👥 **Multi-Speaker Awareness**: Distinguishes between direct commands and inter-human conversations
- 🌐 **WebRTC Communication**: Direct peer-to-peer WebRTC audio/video streaming (no WebSocket proxy needed)
- 📱 **Live Transcription Display**: Real-time transcription updates on the frontend
- 🎨 **Modern UI**: Beautiful, responsive user interface
- 🧠 **Long-term Memory (optional)**: Persistent user memory via Mem0

## Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- Speechmatics API key ([Get one here](https://portal.speechmatics.com/))
- ElevenLabs API key ([Get one here](https://elevenlabs.io/app/settings/api-keys))
- DeepInfra API key for Qwen models ([Get one here](https://deepinfra.com/))
- Mem0 API key ([Docs](https://docs.mem0.ai/))

## Installation

1. Install Node.js dependencies:

```bash
npm install
```

2. Install Python dependencies:

```bash
pip install -r requirements.txt
```

This will install all required packages including:
- `pipecat-ai` with extensions: speechmatics, elevenlabs, webrtc, qwen, moondream, local-smart-turn-v3, silero
- `aiohttp` for async HTTP requests (Gating Layer API calls)
- FastAPI and Uvicorn for the web server
- Additional dependencies for SSL certificate handling and logging

3. Create a `.env.local` file in the root directory:

```bash
cp env.example .env.local
```

4. Add your API keys to `.env.local`:

```env
SPEECHMATICS_API_KEY=your_speechmatics_api_key_here
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_VOICE_ID=ry8mpwRw6nugb2qjP0tu  # Optional, defaults to custom voice
QWEN_API_KEY=your_deepinfra_api_key_here  # DeepInfra API key for Qwen models
QWEN_MODEL=Qwen/Qwen2.5-7B-Instruct  # Optional, defaults to Qwen2.5-7B-Instruct

# Pipecat FastAPI service configuration
PIPECAT_HOST=localhost
PIPECAT_PORT=7860

# Frontend configuration
NEXT_PUBLIC_PIPECAT_URL=http://localhost:7860

# Enable long-term memory with Mem0 (required)
MEM0_API_KEY=your_mem0_api_key_here
```

## Running the Application

You need to run TWO servers:

1. **Start the Pipecat FastAPI service** (in one terminal):

```bash
python3 pipecat_service.py
```

This will start the FastAPI service on `http://localhost:7860`

2. **Start the Next.js server** (in another terminal):

```bash
npm run dev
```

The application will be available at `http://localhost:3000`

**Note**: Make sure both services are running before connecting from the browser!

### Production

```bash
# Build Next.js app
npm run build

# Start Next.js server
npm start

# Start Pipecat service (in another terminal)
python3 pipecat_service.py --host 0.0.0.0 --port 7860
```

## How It Works

### Three-Layer Conversation Architecture

TARS uses a sophisticated three-layer system to ensure natural, context-aware conversations:

#### Layer 1: Smart Turn Detection (The Reflex ⚡)
- Instantly detects when someone stops talking using Silero VAD
- Low latency response (~1 second pause detection)
- Prevents awkward interruptions during natural pauses

#### Layer 2: Speechmatics STT (The Ears 👂)
- Transcribes speech to text in real-time
- **Speaker Diarization**: Identifies and labels different speakers (Speaker 1, Speaker 2, etc.)
- Enables multi-party conversation awareness

#### Layer 3: Gating Layer (The Brain 🧠)
- AI-powered decision system using Qwen via DeepInfra
- Analyzes transcribed text to determine: "Should TARS respond?"
- **Responds when:**
  - User directly addresses TARS ("TARS, help me with this")
  - Clear questions or commands directed at the AI
  - User asks for help or information
- **Stays silent when:**
  - Users are talking to each other ("Speaker 2: Yes, I agree")
  - User is thinking out loud ("Umm, let me see...")
  - Conversation is clearly inter-human, not directed at TARS

### Processing Pipeline

1. **Audio/Video Input**: Browser captures audio and video from microphone and camera
2. **WebRTC Connection**: Peer-to-peer connection established directly with FastAPI server
3. **Media Streaming**: Audio and video streamed bidirectionally via WebRTC (no WebSocket proxy)
4. **Smart Turn Detection**: VAD analyzes audio to determine when user stops speaking
5. **Transcription**: Speechmatics processes audio with speaker diarization and returns transcriptions
6. **Gating Decision**: AI analyzes transcription to decide if TARS should respond
7. **LLM Processing**: If gating passes, Qwen LLM processes transcription (can request camera images)
8. **Vision Analysis**: Moondream analyzes camera images when requested by the LLM
9. **Text-to-Speech**: ElevenLabs converts LLM responses to speech using Flash model
10. **Audio Output**: Synthesized speech streamed back via WebRTC and played automatically
11. **Transcription Display**: Transcriptions and partial results sent to frontend via WebRTC data channel

## Architecture

```
┌─────────────┐         ┌─────────────────┐         ┌─────────────┐
│   Browser   │◄───────►│  FastAPI Server │◄───────►│ Speechmatics│
│   (WebRTC)  │         │   (Port 7860)   │         │  API        │
│ Audio/Video │         │  (pipecat_service│         │ (STT +      │
│             │         │      .py)       │         │ Diarization)│
└─────────────┘         └─────────────────┘         └─────────────┘
                               │
                               │ (Pipecat Pipeline - bot.py)
                               │
                               ▼
                    ┌──────────────────────┐
                    │  Three-Layer System  │
                    ├──────────────────────┤
                    │ 1. Smart Turn (VAD)  │ ◄─── Detects pauses
                    │ 2. Speechmatics STT  │ ◄─── Transcribes + Speaker ID
                    │ 3. Gating Layer      │ ◄─── Decides: Reply or Ignore
                    └──────────────────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
        ┌─────────────┐ ┌──────────┐ ┌─────────────┐
        │ ElevenLabs  │ │  Qwen    │ │  Moondream  │
        │     API     │ │   LLM    │ │   Vision    │
        │  (TTS Flash)│ │(DeepInfra)│ │   Service   │
        └─────────────┘ └──────────┘ └─────────────┘
                               ▲
                               │
                        ┌──────┴───────┐
                        │ Gating Layer │
                        │  (DeepInfra) │ ◄─── Fast Qwen model
                        │ Qwen2.5-7B   │      for gating decisions
                        └──────────────┘

┌─────────────┐         ┌──────────────┐
│   Browser   │         │  Next.js     │
│   (WebRTC)  │         │  (Port 3000) │
│             │         │              │
│ Displays    │◄────────│  Serves UI   │
│Transcriptions         │              │
│ & Controls            │              │
└─────────────┘         └──────────────┘
```

### Key Components

- **Direct Connection**: Browser connects directly to FastAPI server via WebRTC (no Node.js WebSocket proxy)
- **Lower Latency**: Peer-to-peer WebRTC connection reduces latency compared to WebSocket relay
- **Built-in Transport**: SmallWebRTC transport handles audio/video I/O directly in the pipeline
- **Data Channel**: Transcriptions sent via WebRTC data channel for real-time UI updates
- **Smart Turn Detection**: Prevents the bot from interrupting users mid-sentence using Silero VAD
- **Gating Layer**: AI-powered traffic controller that filters false positives and multi-party conversations
- **Speaker Diarization**: Speechmatics identifies multiple speakers (up to 2) for context awareness
- **Vision Integration**: LLM can request and analyze camera images for contextual understanding
- **Parallel Processing**: Qwen LLM and Moondream vision service process in parallel for efficient responses
- **Mem0 Integration**: Stores final user transcriptions and injects recalled memories into the system context on connect
- **Conservative Response**: TARS only responds when directly addressed or when questions clearly directed at it

## Gating Layer (Conversation Intelligence)

The Gating Layer is an AI-powered traffic controller that sits between transcription and LLM processing. It analyzes each transcribed message to determine if TARS should respond or stay silent.

### How It Works

1. **Fast Decision**: Uses a lightweight Qwen model (`Qwen/Qwen2.5-7B-Instruct`) on DeepInfra for quick analysis
2. **Speaker-Aware**: Understands speaker labels from Speechmatics diarization (Speaker 1, Speaker 2)
3. **Context Analysis**: Examines the message content and context to make intelligent decisions

### Response Criteria

**TARS will respond when:**
- User explicitly addresses TARS ("TARS, help me with this")
- Message contains clear questions or commands directed at the AI
- User asks for help, information, or assistance
- Context clearly implies AI interaction

**TARS will stay silent when:**
- Users are talking to each other ("Speaker 2: Yes, I agree")
- User is thinking out loud or self-correcting
- User is pausing ("Umm...", "Let me see...", "Wait...")
- Conversation is clearly inter-human, not directed at TARS

### Configuration

The gating layer is automatically initialized in `bot.py` and uses the same `QWEN_API_KEY` as the main LLM. No additional configuration needed.

### Fail-Safe Design

- **Conservative by default**: When uncertain, TARS stays silent
- **Fail-open**: If the gating check fails (API error), TARS responds (ensures reliability)
- **Low latency**: Fast model ensures minimal delay in response time

### Monitoring

Watch for these log messages:
- `🟢 Gating: PASSING through | Message: '...'` - TARS will respond
- `🚦 Gating: BLOCKING response | Message: '...'` - TARS stays silent

## Mem0 (Persistent Memory)

With `MEM0_API_KEY` set and `mem0ai` installed (included in `requirements.txt`), the app will:

- Save each finalized user transcription to Mem0 (best-effort, non-blocking)
- On client connect, recall up to 8 relevant memories and inject them as an additional `system` message to personalize responses

Notes:
- User identity defaults to `user_1` for SmallWebRTC; adapt as needed for multi-user scenarios.
- Mem0 is required; the service will fail fast if the key or SDK is missing.

## Project Structure

```
├── app/                        # Next.js application
│   ├── api/
│   │   ├── status/route.ts    # Health check endpoint
│   │   └── voice/route.ts     # Legacy endpoint (info only)
│   ├── globals.css            # Global styles
│   ├── page.tsx               # Main React component with WebRTC
│   ├── page.module.css        # Component styles
│   └── layout.tsx             # Root layout
├── config/                     # Configuration module
│   └── __init__.py            # Environment variable loading and config
├── processors/                 # Custom Pipecat processors
│   ├── __init__.py            # Processor exports
│   ├── gating.py              # Gating Layer (AI decision system)
│   ├── transcription_logger.py # Transcription logging and frontend messaging
│   ├── assistant_logger.py    # Assistant response logging
│   ├── tts_state_logger.py    # TTS state broadcasting
│   ├── vision_logger.py       # Vision frame logging
│   ├── latency_logger.py      # Pipeline latency tracking
│   └── filters.py             # Audio filters (silence, input)
├── bot.py                      # Main bot pipeline setup and execution
├── pipecat_service.py          # FastAPI server with SmallWebRTC transport
├── character.json              # Character prompt/system message for LLM
├── server.js                   # Next.js custom server
├── requirements.txt            # Python dependencies
├── package.json                # Node.js dependencies
├── env.example                 # Environment variables template
└── README.md                   # This file
```

## API Keys Setup

### Speechmatics

1. Sign up at [Speechmatics Portal](https://portal.speechmatics.com/)
2. Navigate to API Keys section
3. Create a new API key
4. Copy the key to your `.env.local` file

### ElevenLabs

1. Sign up at [ElevenLabs](https://elevenlabs.io/)
2. Go to Settings > API Keys
3. Create a new API key
4. Copy the key to your `.env.local` file
5. (Optional) Choose a voice ID from the [Voices page](https://elevenlabs.io/app/voices)

### DeepInfra (for Qwen Models)

1. Sign up at [DeepInfra](https://deepinfra.com/)
2. Navigate to the Dashboard and create a new API key
3. Copy the key to your `.env.local` file as `QWEN_API_KEY`
4. (Optional) Set `QWEN_MODEL` to a different Qwen model available on DeepInfra
5. Available models: `Qwen/Qwen2.5-7B-Instruct`, `Qwen/QwQ-32B-Preview`, etc.

The same API key is used for both the main LLM and the Gating Layer.

## API Endpoints

### FastAPI Server (Port 7860)

- `POST /api/offer` - Handle WebRTC offer requests (creates bot pipeline)
- `PATCH /api/offer` - Handle ICE candidate updates
- `GET /api/status` - Health check endpoint (shows API key configuration status)

### Next.js Server (Port 3000)

- `/` - Main application UI
- `GET /api/status` - Service status info
- `GET /api/voice` - Legacy endpoint info

## Monitoring

### Check Status via API

```bash
# Check FastAPI service status
curl http://localhost:7860/api/status

# Check Next.js service status
curl http://localhost:3000/api/status
```

### View Logs

**Pipecat/FastAPI Service:**
- Logs appear in the terminal where `python3 pipecat_service.py` is running
- Shows: Client connections, transcription events, gating decisions, pipeline status, LLM responses, vision analysis, errors
- **Key log indicators:**
  - `🎤 Transcription:` - Final transcription from Speechmatics
  - `🎤 Partial:` - Interim transcription results
  - `🟢 Gating: PASSING through` - TARS will respond to this message
  - `🚦 Gating: BLOCKING response` - TARS is staying silent (thinking out loud or inter-human chat)
  - `✓` or `⚠` - Initialization status messages
- Speaker diarization will show speaker IDs in brackets: `🎤 Transcription [speaker_1]: ...`

**Next.js Server:**
- Logs appear in the terminal where `npm run dev` is running
- Shows: HTTP requests, compilation status

**Browser Console:**
- Open browser DevTools (F12) and check the Console tab
- WebRTC connection status and events
- Data channel messages (transcriptions, partial results)
- Transcription updates with speaker IDs
- Any client-side errors

## Development

### Running in Verbose Mode

To see detailed logs from the Python service:

```bash
python3 pipecat_service.py --verbose
```

### Character Configuration

The bot's personality and behavior are controlled by `character.json`. This file contains the system prompt for the Qwen LLM. You can customize the character by editing this file:

```json
{
  "role": "system",
  "content": "Your custom system prompt here..."
}
```

The default character is TARS from Interstellar, configured to be brief and direct.

## Environment Variables

See `env.example` for all available environment variables.
