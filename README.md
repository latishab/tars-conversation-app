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
- 🎨 **Modern UI**: Beautiful, responsive user interface built with shadcn/ui
- 🧠 **Long-term Memory (optional)**: Persistent user memory via Mem0

## Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- Speechmatics API key ([Get one here](https://portal.speechmatics.com/))
- ElevenLabs API key ([Get one here](https://elevenlabs.io/app/settings/api-keys))
- DeepInfra API key for Qwen models ([Get one here](https://deepinfra.com/))
- Mem0 API key ([Docs](https://docs.mem0.ai/))

## Installation

1. Install Python dependencies:

```bash
pip install -r requirements.txt
```

This will install all required packages including:
- `pipecat-ai` with extensions: speechmatics, elevenlabs, webrtc, qwen, moondream, local-smart-turn-v3, silero
- `aiohttp` for async HTTP requests (Gating Layer API calls)
- FastAPI and Uvicorn for the web server
- Additional dependencies for SSL certificate handling and logging

2. Install frontend dependencies:

```bash
npm install
```

3. Create a `.env.local` file in the root directory:

```bash
cp env.example .env.local
```

4. Add your API keys to `.env.local`:

```env
# Speechmatics API Key
SPEECHMATICS_API_KEY=your_speechmatics_api_key_here

# ElevenLabs API Key
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_VOICE_ID=ry8mpwRw6nugb2qjP0tu

# DeepInfra API Key (for Qwen LLM and Gating Layer)
DEEPINFRA_API_KEY=your_deepinfra_api_key_here

# Frontend configuration
NEXT_PUBLIC_PIPECAT_URL=http://localhost:7860

# Mem0 API Key (optional, enables long-term memory)
MEM0_API_KEY=your_mem0_api_key_here
```

## Running the Application

You need to run TWO servers:

1. **Start the Pipecat FastAPI service** (in one terminal):

```bash
npm run dev:backend
# or
python3 pipecat_service.py
```

This will start the FastAPI service on `http://localhost:7860`

2. **Start the Next.js server** (in another terminal):

```bash
npm run dev
```

The application will be available at `http://localhost:3000`

**Note**: Make sure both services are running before connecting from the browser!

## Project Structure

```
├── app/                        # Next.js application (completely self-contained)
│   ├── api/
│   │   ├── offer/route.ts       # WebRTC offer handling (proxies to backend)
│   │   └── status/route.ts      # Health check endpoint
│   ├── components/              # Reusable React components
│   │   └── ui/                  # shadcn/ui components
│   │       ├── button.tsx
│   │       └── card.tsx
│   ├── lib/                     # Utility functions
│   │   └── utils.ts
│   ├── public/                  # Static assets
│   ├── globals.css              # Global styles with shadcn/ui + Tailwind
│   ├── layout.tsx               # Root layout
│   ├── page.tsx                 # Main React component with WebRTC
│   ├── favicon.ico              # App favicon
│   ├── package.json             # Next.js dependencies and scripts
│   ├── tsconfig.json            # TypeScript configuration
│   ├── next.config.ts           # Next.js configuration
│   ├── tailwind.config.ts       # Tailwind CSS configuration
│   ├── components.json          # shadcn/ui configuration
│   ├── postcss.config.mjs       # PostCSS configuration
│   └── eslint.config.mjs        # ESLint configuration
├── config/                      # Configuration module
│   └── __init__.py              # Environment variable loading and config
├── processors/                  # Custom Pipecat processors
│   ├── __init__.py              # Processor exports
│   ├── gating.py                # Gating Layer (AI decision system)
│   ├── transcription_logger.py  # Transcription logging and frontend messaging
│   ├── assistant_logger.py      # Assistant response logging
│   ├── tts_state_logger.py      # TTS state broadcasting
│   ├── vision_logger.py         # Vision frame logging
│   ├── latency_logger.py        # Pipeline latency tracking
│   └── filters.py               # Audio filters (silence, input)
├── bot.py                       # Main bot pipeline setup and execution
├── pipecat_service.py           # FastAPI server with SmallWebRTC transport
├── character/                   # Character configuration
│   ├── persona.ini              # Character personality settings
│   ├── prompts.py               # Prompt generation utilities
│   └── TARS.json                # TARS character definition
├── memory/                      # Memory management
│   └── mem0_client.py           # Mem0 integration for persistent memory
├── modules/                     # Module tools and utilities
│   └── module_tools.py          # Tool definitions for LLM
├── package.json                 # Root scripts for running both frontend/backend
├── requirements.txt             # Python dependencies
├── env.example                  # Environment variables template
└── README.md                    # This file
```

## API Endpoints

### FastAPI Backend Server (Port 7860)

- `POST /api/offer` - Handle WebRTC offer requests (creates bot pipeline)
- `PATCH /api/offer` - Handle ICE candidate updates
- `GET /api/status` - Health check endpoint (shows API key configuration status)

### Next.js Frontend Server (Port 3000)

- `/` - Main application UI
- `POST /api/offer` - Proxy WebRTC offers to backend service
- `PATCH /api/offer` - Proxy ICE candidates to backend service
- `GET /api/status` - Proxy status checks to backend service

## Tech Stack

### Frontend
- **Next.js 16** - React framework with App Router
- **React 19** - UI library
- **Tailwind CSS** - Utility-first CSS framework
- **shadcn/ui** - Modern component library
- **TypeScript** - Type-safe JavaScript
- **WebRTC** - Real-time communication

### Backend
- **Python 3.9+** - Programming language
- **FastAPI** - Modern web framework
- **Pipecat.ai** - Real-time AI pipeline framework
- **SmallWebRTC** - WebRTC transport
- **Speechmatics** - Speech-to-text with diarization
- **ElevenLabs** - Text-to-speech
- **Qwen** - Large language model via DeepInfra
- **Moondream** - Vision AI model

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
3. **Media Streaming**: Audio and video streamed bidirectionally via WebRTC
4. **Smart Turn Detection**: VAD analyzes audio to determine when user stops speaking
5. **Transcription**: Speechmatics processes audio with speaker diarization
6. **Gating Decision**: AI analyzes transcription to decide if TARS should respond
7. **LLM Processing**: If gating passes, Qwen LLM processes transcription
8. **Vision Analysis**: Moondream analyzes camera images when requested
9. **Text-to-Speech**: ElevenLabs converts responses to speech
10. **Audio Output**: Synthesized speech streamed back via WebRTC

## Migration Summary

This project has been successfully migrated from CSS modules to a modern stack:

- ✅ **CSS Modules** → **Tailwind CSS + shadcn/ui**
- ✅ **Legacy styling** → **Modern component library**
- ✅ **Complex CSS** → **Utility-first classes**
- ✅ **Old structure** → **Clean Next.js App Router**
- ✅ **Manual components** → **shadcn/ui components**
- ✅ **TypeScript support** → **Full type safety**

The voice AI functionality, WebRTC streaming, and all backend integrations remain fully intact while providing a much better development experience.