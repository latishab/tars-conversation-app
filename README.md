# TARS Omni - Real-time Voice AI

A Next.js application that provides real-time voice AI with transcription, vision capabilities, and intelligent conversation using Speechmatics, ElevenLabs, Qwen LLM, and Moondream, integrated with pipecat.ai and SmallWebRTC for peer-to-peer real-time audio/video processing.

## Features

- 🎤 **Real-time Transcription**: Live audio transcription using Speechmatics with speaker diarization
- 🔊 **Text-to-Speech**: Natural voice synthesis using ElevenLabs Flash model
- 🤖 **LLM Integration**: Conversational AI powered by Qwen Flash model
- 👁️ **Vision Capabilities**: Image analysis using Moondream vision service
- 🎯 **Smart Turn Detection**: Prevents interruptions with VAD and Smart Turn Detection
- 🌐 **WebRTC Communication**: Direct peer-to-peer WebRTC audio/video streaming (no WebSocket proxy needed)
- 📱 **Live Transcription Display**: Real-time transcription updates on the frontend
- 🎨 **Modern UI**: Beautiful, responsive user interface
 - 🧠 **Long-term Memory (optional)**: Persistent user memory via Mem0

## Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- Speechmatics API key ([Get one here](https://portal.speechmatics.com/))
- ElevenLabs API key ([Get one here](https://elevenlabs.io/app/settings/api-keys))
- Qwen API key ([Get one here](https://dashscope.aliyun.com/))
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
QWEN_API_KEY=your_qwen_api_key_here
QWEN_MODEL=qwen-flash  # Optional, defaults to qwen-flash

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

1. **Audio/Video Input**: The browser captures audio and video from the user's microphone and camera
2. **WebRTC Connection**: Browser establishes a peer-to-peer WebRTC connection directly with the FastAPI server
3. **Media Streaming**: Audio and video are streamed bidirectionally via WebRTC (no WebSocket proxy needed)
4. **Voice Activity Detection**: VAD and Smart Turn Detection analyze audio to determine when the user is speaking
5. **Transcription**: Speechmatics processes the audio in real-time with speaker diarization and returns transcriptions
6. **LLM Processing**: Qwen LLM processes transcriptions and can request camera images for vision analysis
7. **Vision Analysis**: Moondream analyzes camera images when requested by the LLM
8. **Text-to-Speech**: ElevenLabs converts LLM responses to speech using the Flash model
9. **Audio Output**: The synthesized speech is streamed back to the browser via WebRTC and played automatically
10. **Transcription Display**: Transcriptions and partial results are sent to the frontend via WebRTC data channel and displayed live

## Architecture

```
┌─────────────┐         ┌─────────────────┐         ┌─────────────┐
│   Browser   │◄───────►│  FastAPI Server │◄───────►│ Speechmatics│
│   (WebRTC)  │         │   (Port 7860)   │         │  API        │
│ Audio/Video │         │  (pipecat_service│         │ (STT +      │
│             │         │      .py)       │         │ Diarization)│
└─────────────┘         └─────────────────┘         └─────────────┘
                               │
                               │ (Pipecat Pipeline)
                               │ bot.py
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
        ┌─────────────┐ ┌──────────┐ ┌─────────────┐
        │ ElevenLabs  │ │  Qwen    │ │  Moondream  │
        │     API     │ │   LLM    │ │   Vision    │
        │  (TTS Flash)│ │ (Flash)  │ │   Service   │
        └─────────────┘ └──────────┘ └─────────────┘

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
- **Smart Turn Detection**: Prevents the bot from interrupting users mid-sentence using VAD and Smart Turn Detection
- **Vision Integration**: LLM can request and analyze camera images for contextual understanding
- **Parallel Processing**: Qwen LLM and Moondream vision service process in parallel for efficient responses
- **Mem0 Integration**: Stores final user transcriptions and injects recalled memories into the system context on connect

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
│   └── transcription_logger.py # Transcription logging and frontend messaging
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

### Qwen (Alibaba Cloud)

1. Sign up at [Alibaba Cloud DashScope](https://dashscope.aliyun.com/)
2. Navigate to API Keys section
3. Create a new API key
4. Copy the key to your `.env.local` file
5. (Optional) Set `QWEN_MODEL` to a different model (default: `qwen-flash`)

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
- Shows: Client connections, transcription events, pipeline status, LLM responses, vision analysis, errors
- Look for: `🎤 Transcription:`, `🎤 Partial:`, initialization messages (✓ or ⚠), and error messages
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

**Required:**
- `SPEECHMATICS_API_KEY` - Your Speechmatics API key
- `ELEVENLABS_API_KEY` - Your ElevenLabs API key
- `QWEN_API_KEY` - Your Qwen (Alibaba Cloud DashScope) API key

**Optional:**
- `ELEVENLABS_VOICE_ID` - ElevenLabs voice ID (default: `ry8mpwRw6nugb2qjP0tu`)
- `QWEN_MODEL` - Qwen model to use (default: `qwen-flash`)
- `PIPECAT_HOST` - FastAPI server host (default: `localhost`)
- `PIPECAT_PORT` - FastAPI server port (default: `7860`)
- `NEXT_PUBLIC_PIPECAT_URL` - Frontend WebRTC endpoint URL (default: `http://localhost:7860`)

All environment variables are loaded from `.env.local` (or `.env` as fallback) by the `config` module.

## Raspberry Pi Client

You can connect a Raspberry Pi to the Pipecat server as a WebRTC client. See [RASPBERRY_PI_CLIENT.md](RASPBERRY_PI_CLIENT.md) for detailed instructions.

Quick start:
```bash
# On Raspberry Pi
pip3 install aiortc aiohttp av opencv-python-headless
python3 raspberry_pi_client.py --server http://your-server-ip:7860
```

Two client implementations are provided:
- `raspberry_pi_client.py` - Full-featured client with OpenCV camera support
- `raspberry_pi_client_simple.py` - Simplified client using MediaPlayer (easier setup)

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
