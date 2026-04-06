# Architecture

## Pipeline

Both robot and browser modes use the same core pipeline built on Pipecat:

```
Mic -> STT -> ProactiveMonitor -> ContextAggregator(user)
  -> LLM (+ tools) -> ExpressTagFilter -> ReactiveGate
  -> SilenceFilter -> ReasoningLeakFilter -> SpaceNormalizer
  -> TTS -> Speaker -> ContextAggregator(assistant)
```

**Robot mode** (`tars_bot.py`) adds an AudioBridge between TTS and the speaker that resamples audio and sends it to the Pi over WebRTC. It also runs custom VAD to handle echo suppression during bot playback.

**Browser mode** (`bot.py`) uses SmallWebRTCTransport for audio I/O directly from the browser. No AudioBridge or custom echo handling needed.

## Processors

Processors sit in the pipeline and transform or gate frames in transit.

| Processor | What it does |
|-----------|-------------|
| `ProactiveMonitor` | Watches for prolonged silence (8s), hesitation fillers, or confusion phrases. Injects a system message to prompt TARS to help. Cooldown: 30s. |
| `ReactiveGate` | In task mode, suppresses LLM responses unless: (A) TARS surrenders the task, (B) user directly addresses TARS, or (C) user makes a correction. Deterministic, no LLM calls. |
| `ExpressTagFilter` | Extracts `[express(emotion, intensity)]` tags from LLM output and fires the corresponding expression on the robot. Strips the tag before TTS. |
| `ReasoningLeakFilter` | Strips `<think>` blocks and stray markdown (`*`, `_`) that leak from chain-of-thought models before they reach TTS. |
| `SilenceFilter` | Removes silence frames from the audio stream. |
| `SpaceNormalizer` | Fixes whitespace and punctuation artifacts in text before TTS. |
| `InputAudioFilter` | Blocks raw audio frames from flowing downstream (only allows them upstream to STT). |

## Observers

Observers watch pipeline frames without modifying them. Used for logging and metrics.

| Observer | What it tracks |
|----------|---------------|
| `MetricsObserver` | Per-turn latency: STT TTFB, LLM TTFB, TTS TTFB, end-to-end |
| `TranscriptionObserver` | Logs user speech transcriptions |
| `AssistantResponseObserver` | Logs bot responses |
| `StateObserver` | Syncs state over WebRTC DataChannel (robot mode only) |
| `VisionObserver` | Logs vision tool calls (browser mode) |
| `TTSStateObserver` | Tracks TTS speaking/idle state (browser mode) |

## Tools

Functions the LLM can call during a conversation.

| Tool | Description |
|------|-------------|
| `express(emotion, intensity)` | Set facial expression. 13 emotions: neutral, happy, sad, angry, excited, afraid, sleepy, side eye L, side eye R, curious, skeptical, smug, surprised. 3 intensities: low, medium, high. Rate-limited. |
| `execute_movement(movements)` | Trigger physical movement on the robot (wave, nod, etc). |
| `capture_robot_camera(question)` | Capture an image from the Pi camera and analyze it with Moondream (local) or Qwen VL (DeepInfra). |
| `capture_user_camera(question)` | Request an image from the user's browser camera (browser mode only). |
| `adjust_persona_parameter(param, value)` | Adjust a personality trait (0-100). Rebuilds the system prompt dynamically. |
| `set_task_mode(mode)` | Activate/deactivate task-focused mode. Turning off requires the user to directly address TARS with an end signal. |

## Transport

| Mode | Transport | Audio path |
|------|-----------|-----------|
| Robot | aiortc WebRTC + gRPC | Mic -> WebRTC -> Mac (STT/LLM/TTS) -> AudioBridge -> WebRTC -> Pi speaker |
| Browser | SmallWebRTC | Browser mic -> WebRTC -> Server (STT/LLM/TTS) -> WebRTC -> Browser speaker |

Robot mode uses gRPC (port 50051) for hardware commands (expressions, movement, camera) and WebRTC for audio streaming. The daemon HTTP server (port 8000) handles WebRTC signaling.
