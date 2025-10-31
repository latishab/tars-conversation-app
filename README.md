# TARS Omni - Real-time Voice AI

A Next.js application that provides real-time voice transcription using Speechmatics and text-to-speech using ElevenLabs, integrated with pipecat.ai for real-time audio processing.

## Features

- 🎤 **Real-time Transcription**: Live audio transcription using Speechmatics
- 🔊 **Text-to-Speech**: Natural voice synthesis using ElevenLabs
- ⚡ **WebSocket Communication**: Low-latency real-time audio streaming
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
pip install "pipecat-ai[speechmatics,elevenlabs]"
pip install python-dotenv websockets
```

Or use the requirements file:

```bash
pip install -r requirements.txt
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
```

## Running the Application

You need to run TWO servers:

1. **Start the Pipecat Python service** (in one terminal):

```bash
python pipecat_service.py
```

This will start the Pipecat service on `ws://localhost:8765`

2. **Start the Next.js server** (in another terminal):

```bash
npm run dev
```

The application will be available at `http://localhost:3000`

**Note**: Make sure both services are running before connecting from the browser!

### Production

```bash
npm run build
npm start
```

## How It Works

1. **Audio Input**: The browser captures audio from the user's microphone using the MediaRecorder API
2. **WebSocket Streaming**: Audio chunks are sent to the server via WebSocket
3. **Transcription**: Speechmatics processes the audio in real-time and returns transcriptions
4. **Text-to-Speech**: When text is received, ElevenLabs converts it to speech
5. **Audio Output**: The synthesized speech is streamed back to the browser and played

## Architecture

```
┌─────────────┐         ┌──────────────┐         ┌─────────────┐
│   Browser   │◄───────►│  Next.js     │◄───────►│ Speechmatics│
│  (WebSocket)│         │   Server     │         │  API        │
└─────────────┘         └──────────────┘         └─────────────┘
                               │
                               ▼
                        ┌─────────────┐
                        │ ElevenLabs  │
                        │     API     │
                        └─────────────┘
```

## Project Structure

```
├── app/
│   ├── api/voice/      # API route for WebSocket
│   ├── page.tsx        # Main React component
│   └── layout.tsx      # Root layout
├── lib/
│   ├── services/
│   │   ├── speechmatics.js  # Speechmatics integration
│   │   └── elevenlabs.js    # ElevenLabs integration
│   └── voice-server.js      # WebSocket server logic
├── server.js           # Custom Next.js server with WebSocket support
└── package.json
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

## Troubleshooting

### WebSocket Connection Issues

- Ensure the server is running on port 3000
- Check that `NEXT_PUBLIC_WS_URL` matches your server URL
- Verify firewall settings allow WebSocket connections

### Audio Issues

- Grant microphone permissions in your browser
- Check browser console for errors
- Ensure your microphone is working in other applications

### API Errors

- Verify your API keys are correct
- Check your API quota/credits
- Review the server logs for detailed error messages

## Monitoring

### Quick Status Check

Run the monitoring script:
```bash
./monitor.sh
```

This shows:
- Service status (running/stopped)
- Process IDs
- Environment variable status
- Active connections

### Check Status via API

```bash
curl http://localhost:3000/api/status
```

### View Logs

**Pipecat Service:**
- If running in background: Check system logs or restart in foreground to see output
- Logs show: Client connections, transcription events, errors

**Next.js Server:**
- Logs appear in the terminal where `npm run dev` was started
- Shows: WebSocket connections, client activity, errors

### Browser Console

Open browser DevTools (F12) and check the Console tab for:
- WebSocket connection status
- Transcription messages
- Any client-side errors

### Troubleshooting WebSocket Code 1006

If you see "WebSocket closed: 1006", this means the connection closed abnormally. To debug:

1. **Check Pipecat service logs:**
   ```bash
   # Stop background service
   pkill -f pipecat_service.py
   
   # Run in foreground to see logs
   python3 pipecat_service.py
   ```

2. **Test service initialization:**
   ```bash
   python3 test_pipecat.py
   ```

3. **Check Next.js server logs** in the terminal where `npm run dev` is running

4. **Common causes:**
   - Missing or invalid API keys
   - Pipeline initialization error
   - Network/port conflicts

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

