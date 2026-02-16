# TARS Conversation App

Real-time voice AI with transcription, vision, and intelligent conversation using Speechmatics/Deepgram, Qwen3-TTS/ElevenLabs, DeepInfra LLM, and Moondream.

**Note:** To align with the project purpose, consider renaming this folder from `tars-omni` to `tars-conversation-app`:
```bash
cd .. && mv tars-omni tars-conversation-app && cd tars-conversation-app
```

## Features

- **Dual Operation Modes**
  - **WebRTC Mode** (`bot.py`) - Browser-based voice AI with real-time metrics dashboard
  - **Robot Mode** (`tars_bot.py`) - Connect to Raspberry Pi TARS robot via WebRTC and gRPC
- **Real-time Transcription** - Speechmatics or Deepgram with smart turn detection
- **Dual TTS Options** - Qwen3-TTS (local, free, voice cloning) or ElevenLabs (cloud)
- **LLM Integration** - Any model via DeepInfra
- **Vision Analysis** - Moondream for image understanding
- **Smart Gating Layer** - AI-powered decision system for natural conversation flow
- **Hybrid Memory** - SQLite-based hybrid search (70% vector + 30% BM25)
- **Emotional Monitoring** - Real-time detection of confusion, hesitation, and frustration
- **Gradio Dashboard** - Live TTFB metrics, latency charts, and conversation transcription
- **WebRTC Transport** - Low-latency peer-to-peer audio
- **gRPC Robot Control** - Hardware control with 5-10ms latency (robot mode only)

## Project Structure

```
tars-conversation-app/
├── bot.py                      # WebRTC mode - Browser voice AI
├── tars_bot.py                 # Robot mode - Raspberry Pi hardware
├── pipecat_service.py          # FastAPI backend (WebRTC signaling)
├── config.py                   # Configuration management
├── config.ini                  # User configuration file
├── requirements.txt            # Python dependencies
│
├── src/                        # Backend
│   ├── observers/              # Pipeline observers (metrics, transcription)
│   ├── processors/             # Pipeline processors (silence filter, gating)
│   ├── services/               # Services (STT, TTS, Memory, Robot)
│   ├── tools/                  # LLM callable functions
│   ├── transport/              # WebRTC transport (aiortc)
│   ├── character/              # TARS personality and prompts
│   └── shared_state.py         # Shared metrics storage
│
├── ui/                         # Frontend
│   └── app.py                  # Gradio dashboard (metrics + transcription)
│
├── tests/                      # Tests
│   └── gradio/
│       └── test_gradio.py      # UI integration test
│
├── character/                  # TARS character data
│   ├── TARS.json              # Character definition
│   └── persona.ini            # Personality parameters
```

## Operation Modes

### WebRTC Mode (`bot.py`)
- **Use case**: Browser-based voice AI conversations
- **Transport**: SmallWebRTC (browser ↔ Pipecat)
- **Features**: Full pipeline with STT, LLM, TTS, Memory
- **UI**: Gradio dashboard for metrics and transcription
- **Best for**: Development, testing, remote conversations

### Robot Mode (`tars_bot.py`)
- **Use case**: Physical TARS robot on Raspberry Pi
- **Transport**: aiortc (RPi ↔ Pipecat) + gRPC (commands)
- **Features**: Same pipeline + robot control (eyes, gestures, movement)
- **Hardware**: Requires TARS robot with servos and display
- **Best for**: Physical robot interactions, demos

## Quick Start

### 1. Install Dependencies

```bash
# Python dependencies
pip install -r requirements.txt

# For robot mode, install TARS SDK
pip install tars-robot[sdk]
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
model = meta-llama/Llama-3.3-70B-Instruct

[STT]
provider = deepgram  # or speechmatics

[TTS]
provider = qwen3  # or elevenlabs

[Memory]
type = hybrid  # SQLite-based hybrid search (vector + BM25)
```

### 3. Run

#### WebRTC Mode (Browser)

**Terminal 1: Python backend**
```bash
python pipecat_service.py
```

**Terminal 2: Gradio UI (optional)**
```bash
python ui/app.py
```

Then:
1. Open WebRTC client in browser (connect to pipecat_service)
2. Open Gradio dashboard at http://localhost:7861 (for metrics)
3. Start talking

#### Robot Mode (Raspberry Pi)

Prerequisites:
- Raspberry Pi TARS robot running tars_daemon.py
- Network connection (LAN or Tailscale)
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

Deployment detection:
- **Remote** (Mac/computer): Uses configured addresses
- **Local** (on RPi): Auto-detects localhost:50051

Run:
```bash
python tars_bot.py
```

## Gradio Dashboard

The Gradio UI (`ui/app.py`) provides real-time monitoring:

### Latency Dashboard
- Service configuration (STT, Memory, LLM, TTS)
- TTFB metrics with min/max/avg/last stats
- Line chart: Latency trends over time
- Bar chart: Stacked latency breakdown
- Metrics table: Last 15 turns

### Conversation Tab
- Live user and assistant transcriptions
- Auto-updates every second

### Connection Tab
- Architecture documentation
- Usage instructions

## Architecture

### WebRTC Mode Data Flow
```
Browser (WebRTC client)
    ↕ (audio)
SmallWebRTC Transport
    ↓
Pipeline: STT → Memory → LLM → TTS
    ↓
Observers (metrics, transcription, assistant)
    ↓
shared_state.py
    ↓
Gradio UI (http://localhost:7861)
```

### Robot Mode Data Flow
```
RPi Mic → WebRTC → Pipecat Pipeline → WebRTC → RPi Speaker
          (audio)        ↓              (audio)
                        STT → Memory → LLM → TTS
                                ↓
                         LLM Tools (set_emotion, do_gesture)
                                ↓
                        gRPC → RPi Hardware
                            (eyes, servos, display)
```

Communication channels (Robot Mode):

| Channel | Protocol | Purpose | Latency |
|---------|----------|---------|---------|
| Audio | WebRTC (aiortc) | Voice conversation | ~20ms |
| Commands | gRPC | Hardware control | ~5-10ms |
| State | DataChannel | Battery, movement status | ~10ms |

## Testing

```bash
# Test Gradio integration
python tests/gradio/test_gradio.py

# Test gesture recognition (robot mode)
python tests/test_gesture.py

# Test hardware connection (robot mode, from RPi)
ssh tars-pi "cd ~/tars && python tests/test_hardware.py"
```

## Development

### Adding Metrics
1. Emit `MetricsFrame` in your service/processor
2. `MetricsObserver` will capture it automatically
3. Metrics appear in Gradio dashboard

### Adding Tools
1. Create function in `src/tools/`
2. Create schema with `create_*_schema()`
3. Register in `bot.py` or `tars_bot.py`
4. LLM can now call your tool

### Modifying UI
1. Edit `ui/app.py`
2. Gradio hot-reloads automatically
3. Access `metrics_store` for data

## Troubleshooting

### No metrics in Gradio UI
- Ensure bot is running (`bot.py` or `tars_bot.py`)
- Check WebRTC client is connected
- Verify at least one conversation turn completed

### Robot mode connection issues
- Check RPi is reachable: `ping <rpi-ip>`
- Verify tars_daemon is running on RPi
- Check gRPC port 50051 is open
- Review config.ini addresses

### Import errors
```bash
pip install -r requirements.txt
pip install gradio plotly  # For UI
```

### Audio issues (robot mode)
- Check RPi mic/speaker with `arecord`/`aplay`
- Verify WebRTC connection in logs
- Test with `tests/test_hardware.py`

## Contributing

Contributions welcome.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with `python tests/gradio/test_gradio.py`
5. Commit with clear messages (see CLAUDE.md for style)
6. Push to your fork
7. Open a Pull Request

Code Style:
- Python: Follow PEP 8
- Add comments for complex logic
- Update docs for new features
- See CLAUDE.md for guidelines (concise, technical, no fluff)

## License

MIT License - see LICENSE file for details
