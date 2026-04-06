# Configuration Reference

Runtime settings live in two files, both gitignored:

- `config.ini` -- provider selection, connection, display
- `.env.local` -- API keys and secrets

Create them from templates on first setup:

```bash
cp config.ini.example config.ini
cp env.example .env.local
```

Changes take effect on restart.

---

## config.ini

### [LLM]

| Key | Values | Default |
|-----|--------|---------|
| `provider` | `cerebras`, `deepinfra` | `cerebras` |
| `model` | Cerebras: `gpt-oss-120b`, `gpt-oss-20b`. DeepInfra: `meta-llama/Llama-3.3-70B-Instruct`, `openai/gpt-oss-20b` | `gpt-oss-120b` |

### [STT]

| Key | Values | Default |
|-----|--------|---------|
| `provider` | `deepgram-flux` (recommended), `deepgram`, `speechmatics` | `deepgram-flux` |

- `speechmatics` -- SMART_TURN mode with diarization
- `deepgram` -- Nova-3 with server-side endpointing
- `deepgram-flux` -- Flux model with built-in end-of-turn detection

### [TTS]

| Key | Values | Default |
|-----|--------|---------|
| `provider` | `elevenlabs`, `qwen3` | `elevenlabs` |
| `qwen3_model` | `Qwen/Qwen3-TTS-12Hz-0.6B-Base`, `Qwen/Qwen3-TTS-12Hz-1.7B-Base` | `0.6B` |
| `qwen3_device` | `mps` (Mac), `cuda` (NVIDIA), `cpu` | `mps` |
| `qwen3_ref_audio` | Path to reference audio for voice cloning | `assets/audio/tars-clean-compressed.mp3` |

### [Connection]

| Key | Values | Default |
|-----|--------|---------|
| `mode` | `robot` (Pi via aiortc), `browser` (SmallWebRTC) | `robot` |
| `connection_type` | `local`, `manual`, `tailscale` | `local` |
| `rpi_ip` | IP address (only for `manual`) | `192.168.1.100` |
| `auto_connect` | `true`, `false` | `true` |
| `reconnect_delay` | Seconds between reconnect attempts | `5` |
| `max_reconnect_attempts` | 0 = infinite | `0` |

Connection types:
- `local` -- mDNS `tars.local` (works on most home WiFi)
- `manual` -- direct IP, set `rpi_ip`
- `tailscale` -- MagicDNS hostname `tars` (for remote access)

### [Emotional]

| Key | Values | Default |
|-----|--------|---------|
| `enabled` | `true`, `false` | `true` |
| `sampling_interval` | Seconds between video frame samples | `3.0` |
| `intervention_threshold` | Consecutive negative states before intervention | `2` |

### [Display]

| Key | Values | Default |
|-----|--------|---------|
| `enabled` | `true`, `false` | `true` |

---

## .env.local

### Required (pick one per category)

**LLM** -- at least one:
| Key | Provider |
|-----|----------|
| `CEREBRAS_API_KEY` | Cerebras |
| `DEEPINFRA_API_KEY` | DeepInfra (also used for vision) |
| `GEMINI_API_KEY` | Google Gemini |

**STT** -- matching your `config.ini` STT provider:
| Key | Provider |
|-----|----------|
| `DEEPGRAM_API_KEY` | Deepgram / Deepgram Flux |
| `SPEECHMATICS_API_KEY` | Speechmatics |

**TTS** -- if using ElevenLabs:
| Key | Description |
|-----|-------------|
| `ELEVENLABS_API_KEY` | API key |
| `ELEVENLABS_VOICE_ID` | Voice ID (optional, has default) |

### Optional

| Key | Description |
|-----|-------------|
| `MEM0_API_KEY` | Mem0 long-term memory service |
| `PIPECAT_HOST` | FastAPI service host (default: `localhost`) |
| `PIPECAT_PORT` | FastAPI service port (default: `7860`) |
| `NEXT_PUBLIC_PIPECAT_URL` | Frontend WebRTC endpoint |
