# Tests

```
tests/
├── gradio/         # Gradio UI integration
├── hardware/       # Pi hardware: gestures, audio, expressions, speaker
├── latency/        # STT/TTS provider latency benchmarks
├── llm/            # LLM prompt content, tool calls, persona, task mode
└── processors/     # Pipeline processors: reactive gate, proactive monitor
```

## Running

```bash
python -m pytest tests/                # everything
python -m pytest tests/llm/            # one directory
python -m pytest tests/llm/test_prompts.py -v  # one file, verbose
```

Tests that call external APIs need keys loaded first:

```bash
export $(grep -v '^#' .env.local | xargs)
```

## Prerequisites

- Python 3.10+
- `pip install -r requirements.txt`
- API keys in `.env.local` (LLM and latency tests)
- TARS daemon on Pi (hardware tests only)
