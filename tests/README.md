# TARS Tests

## Structure

```
tests/
├── hardware/       # Pi hardware: gestures, audio, expressions
├── latency/        # STT/TTS provider latency benchmarks
├── llm/            # LLM prompt and expression diagnostics
└── gradio/         # Gradio UI integration
```

## hardware/

| File | Description |
|------|-------------|
| `test_gesture.py` | Physical movements (head, arm) |
| `test_speaker.py` | Speaker output and mic recording |
| `test_expressions.py` | Facial emotions and eye states |
| `test_audio_bridge.py` | WebRTC mic loopback to Mac/Pi speakers |

Requires TARS daemon running on Pi. Connects via `tars.local` (mDNS) or Tailscale.

## latency/

| File | Description |
|------|-------------|
| `test_deepgram_latency.py` | Deepgram STT latency |
| `test_soniox_latency.py` | Soniox STT latency |
| `test_parakeet_latency.py` | Parakeet local STT latency |
| `test_cartesia_latency.py` | Cartesia TTS latency |
| `test_elevenlabs_latency.py` | ElevenLabs TTS latency |

## llm/

| File | Description |
|------|-------------|
| `test_inline_express.py` | Inline `[express(emotion, intensity)]` tag reliability |
| `test_prompts.py` | Express tool call + co-occurrence diagnostics |
| `test_tools_prompts.py` | Comprehensive prompt + tool diagnostic |

## Requirements

- TARS daemon running on Pi (for hardware tests)
- API keys set in environment or `.env`
- Python dependencies: `pip install -r requirements.txt`
