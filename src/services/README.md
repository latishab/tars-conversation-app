# Services

Backend services for TARS voice AI. These provide core functionality like speech recognition, text-to-speech, memory, and robot control.

## Organization

| Service | Purpose |
|---------|---------|
| `tars_robot.py` | Robot hardware control via gRPC (movement, camera, display) |
| `tts_qwen.py` | Local text-to-speech using Qwen3 models |
| `memory_chromadb.py` | Semantic memory using ChromaDB |
| `memory_hybrid.py` | Hybrid memory combining ChromaDB and Mem0 |
| `factories/` | Factory functions for creating STT/TTS services |

## Robot Control

Robot hardware is controlled exclusively via gRPC using the TARS SDK.

### tars_robot.py

Provides functions for robot control in robot mode (tars_bot.py):

```python
from services import tars_robot

# Get robot client (singleton) - uses tars.local by default
client = tars_robot.get_robot_client(address="tars.local:50051")

# Control functions
await tars_robot.execute_movement(["wave_right", "step_forward"])
result = await tars_robot.capture_camera_view()
tars_robot.set_emotion("happy")
tars_robot.set_eye_state("listening")
status = tars_robot.get_robot_status()
available = tars_robot.is_robot_available()

# Cleanup
tars_robot.close_robot_client()
```

### Architecture

Robot mode uses two communication channels:

| Channel | Protocol | Purpose | Latency |
|---------|----------|---------|---------|
| Audio | WebRTC | Voice conversation | ~20ms |
| Commands | gRPC | Hardware control | ~5-10ms |

Audio flows through aiortc WebRTC connection.
All hardware commands (movement, camera, display) use gRPC.

### Browser Mode

Browser mode (bot.py) does NOT support robot control.
It only provides:
- WebRTC audio/video with browser
- Vision analysis
- Conversation

Display observers in browser mode are deprecated and do nothing.

## Service Factories

The `factories/` directory contains factory functions for creating STT and TTS services:

```python
from services.factories import create_stt_service, create_tts_service

# Create STT service
stt = create_stt_service(
    provider="deepgram",  # or "speechmatics", "deepgram-flux"
    deepgram_api_key=DEEPGRAM_API_KEY,
    language=Language.EN
)

# Create TTS service
tts = create_tts_service(
    provider="elevenlabs",  # or "qwen3"
    elevenlabs_api_key=ELEVENLABS_API_KEY,
    elevenlabs_voice_id=VOICE_ID
)
```

## Memory Services

### ChromaDB (memory_chromadb.py)

Simple semantic memory using ChromaDB vector database:

```python
from services.memory_chromadb import ChromaDBMemoryService

memory = ChromaDBMemoryService()
await memory.store("user_id", "The user likes pizza")
results = await memory.search("user_id", "What does the user like?")
```

### Hybrid Memory (memory_hybrid.py)

Combines ChromaDB with Mem0 for enhanced memory capabilities.

## Not Services

This directory is for backend services only. Other code belongs in:

- `tools/` - LLM callable functions
- `processors/` - Pipeline frame processors
- `transport/` - Network transport (WebRTC, gRPC)
- `observers/` - Pipeline observers
