# TARS Omni - Real-time Voice AI

A Next.js application that provides real-time voice transcription using Speechmatics and text-to-speech using ElevenLabs, integrated with pipecat.ai and SmallWebRTC for peer-to-peer real-time audio processing.

## Features

- 🎤 **Real-time Transcription**: Live audio transcription using Speechmatics
- 🔊 **Text-to-Speech**: Natural voice synthesis using ElevenLabs
- 🌐 **WebRTC Communication**: Direct peer-to-peer WebRTC audio streaming (no WebSocket proxy needed)
- 📱 **Live Transcription Display**: Real-time transcription updates on the frontend
- 🎨 **Modern UI**: Beautiful, responsive user interface

## Prerequisites

- Node.js 18+ and npm
- Python 3.9+
- Speechmatics API key ([Get one here](https://portal.speechmatics.com/))
- ElevenLabs API key ([Get one here](https://elevenlabs.io/app/settings/api-keys))

## Installation

1. Install Node.js dependencies:

```bash
npm install
```

2. Install Python dependencies:

```bash
pip install -r requirements.txt
```

Or manually install:

```bash
pip install "pipecat-ai[speechmatics,elevenlabs,webrtc]>=0.0.48"
pip install fastapi uvicorn[standard] loguru python-dotenv certifi
```

3. Create a `.env.local` file in the root directory:

```bash
cp env.example .env.local
```

4. Add your API keys to `.env.local`:

```env
SPEECHMATICS_API_KEY=your_speechmatics_api_key_here
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
ELEVENLABS_VOICE_ID=ry8mpwRw6nugb2qjP0tu  # Optional, defaults to custom voice

# Pipecat FastAPI service configuration
PIPECAT_HOST=localhost
PIPECAT_PORT=7860

# Frontend configuration
NEXT_PUBLIC_PIPECAT_URL=http://localhost:7860
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

1. **Audio Input**: The browser captures audio from the user's microphone
2. **WebRTC Connection**: Browser establishes a peer-to-peer WebRTC connection directly with the FastAPI server
3. **Audio Streaming**: Audio is streamed bidirectionally via WebRTC (no WebSocket proxy needed)
4. **Transcription**: Speechmatics processes the audio in real-time and returns transcriptions
5. **Transcription Display**: Transcriptions are sent to the frontend via WebRTC data channel and displayed live
6. **Text-to-Speech**: ElevenLabs converts transcriptions to speech
7. **Audio Output**: The synthesized speech is streamed back to the browser via WebRTC and played automatically

## Architecture

```
┌─────────────┐         ┌─────────────────┐         ┌─────────────┐
│   Browser   │◄───────►│  FastAPI Server │◄───────►│ Speechmatics│
│   (WebRTC)  │         │   (Port 7860)   │         │  API        │
└─────────────┘         └─────────────────┘         └─────────────┘
                               │
                               │ (Pipecat Pipeline)
                               │
                               ▼
                        ┌─────────────┐
                        │ ElevenLabs  │
                        │     API     │
                        └─────────────┘

┌─────────────┐         ┌──────────────┐
│   Browser   │         │  Next.js     │
│   (WebRTC)  │         │  (Port 3000) │
│             │         │              │
│ Displays    │◄────────│  Serves UI   │
│Transcriptions         │              │
└─────────────┘         └──────────────┘
```

### Key Differences from WebSocket Architecture

- **Direct Connection**: Browser connects directly to FastAPI server via WebRTC (no Node.js WebSocket proxy)
- **Lower Latency**: Peer-to-peer WebRTC connection reduces latency compared to WebSocket relay
- **Built-in Transport**: SmallWebRTC transport handles audio I/O directly in the pipeline
- **Data Channel**: Transcriptions sent via WebRTC data channel for real-time UI updates

## Project Structure

```
├── app/
│   ├── api/
│   │   ├── status/route.ts    # Health check endpoint
│   │   └── voice/route.ts     # Legacy endpoint (info only)
│   ├── globals.css            # Global styles
│   ├── page.tsx               # Main React component with WebRTC
│   ├── page.module.css        # Component styles
│   └── layout.tsx             # Root layout
├── lib/
│   └── voice-server.ts        # (Legacy - not used in WebRTC setup)
├── pipecat_service.py         # FastAPI server with SmallWebRTC transport
├── server.js                  # Next.js custom server (no WebSocket proxy)
├── requirements.txt           # Python dependencies
├── package.json               # Node.js dependencies
├── env.example                # Environment variables template
└── README.md                  # This file
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

## API Endpoints

### FastAPI Server (Port 7860)

- `POST /api/offer` - Handle WebRTC offer requests
- `PATCH /api/offer` - Handle ICE candidate updates
- `GET /api/status` - Health check endpoint

### Next.js Server (Port 3000)

- `/` - Main application UI
- `GET /api/status` - Service status info
- `GET /api/voice` - Legacy endpoint info

## Troubleshooting

### WebRTC Connection Issues

- Ensure the FastAPI service is running on port 7860
- Check that `NEXT_PUBLIC_PIPECAT_URL` in `.env.local` matches `http://localhost:7860`
- Check browser console for WebRTC connection errors
- Verify firewall settings allow WebRTC connections
- For production, configure STUN/TURN servers in `app/page.tsx`

### Audio Issues

- Grant microphone permissions in your browser
- Check browser console for errors
- Ensure your microphone is working in other applications
- Check that audio tracks are being sent/received (browser console logs)

### Transcription Not Appearing

- Check Python server logs for transcription messages (should see `🎤 Transcription:`)
- Check browser console for data channel messages
- Verify WebRTC connection is established (check connection state in console)
- Ensure data channel is opened (check console for "Data channel opened")

### API Errors

- Verify your API keys are correct in `.env.local`
- Check your API quota/credits
- Review the Python server logs for detailed error messages
- Check FastAPI logs for initialization errors

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
- Shows: Client connections, transcription events, pipeline status, errors
- Look for: `🎤 Transcription:` and `🎤 Partial:` messages

**Next.js Server:**
- Logs appear in the terminal where `npm run dev` is running
- Shows: HTTP requests, compilation status

**Browser Console:**
- Open browser DevTools (F12) and check the Console tab
- WebRTC connection status and events
- Data channel messages
- Transcription updates
- Any client-side errors

## Development

### Running in Verbose Mode

To see detailed logs from the Python service:

```bash
python3 pipecat_service.py --verbose
```

### Testing the Pipeline

```bash
python3 test_pipecat.py
```

## Environment Variables

See `env.example` for all available environment variables.

Required:
- `SPEECHMATICS_API_KEY` - Your Speechmatics API key
- `ELEVENLABS_API_KEY` - Your ElevenLabs API key

Optional:
- `ELEVENLABS_VOICE_ID` - ElevenLabs voice ID (default: `ry8mpwRw6nugb2qjP0tu`)
- `PIPECAT_HOST` - FastAPI server host (default: `localhost`)
- `PIPECAT_PORT` - FastAPI server port (default: `7860`)
- `NEXT_PUBLIC_PIPECAT_URL` - Frontend WebRTC endpoint URL (default: `http://localhost:7860`)

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
