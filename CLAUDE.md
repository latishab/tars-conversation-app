# TARS Conversation App

Real-time conversational AI connecting to Raspberry Pi hardware via WebRTC/gRPC.

## Pi Access
```
ssh tars-pi  # tars.local or Tailscale: tars, user: mac, repo: ~/tars-daemon
```

## Install

Pi (from tars-daemon dashboard):
- Apps tab → Install button

Pi (manual):
```bash
ssh tars-pi "cd ~/tars-conversation-app && bash install.sh"
```

## Run

**1. Pi daemon** (if not already running)
```bash
ssh tars-pi "cd ~/tars && python tars_daemon.py"
```

**2. Mac bot**
```bash
python src/tars_bot.py           # robot mode (Pi)
python src/tars_bot.py --gradio  # with Gradio UI at localhost:7860
python src/pipecat_service.py     # browser mode (WebRTC)
```

## Config

- `config.ini` — LLM, STT, TTS providers, connection mode, display
- `env.example` → `.env.local` — API keys

Key providers (set in `config.ini`):
- **LLM**: `cerebras` (gpt-oss-120b/20b), `deepinfra` (Llama-3.3-70B)
- **STT**: `deepgram-flux` (recommended), `deepgram`, `speechmatics`
- **TTS**: `elevenlabs`, `qwen3` (local, MPS/CUDA/CPU)
- **Connection**: `robot` (Pi via gRPC) or `browser` (SmallWebRTC)

## Project Structure

```
src/
  tars_bot.py          # entry point (robot mode)
  bot.py               # entry point (browser mode)
  character/           # TARS.json, persona.ini, prompts.py
  services/            # STT, TTS, LLM factories + memory
  tools/               # robot.py (emotions/movement), vision.py, persona.py
  observers/           # proactive/emotional monitoring
  processors/          # pipeline processors
  transport/           # WebRTC/gRPC transport
  ui/                  # Gradio dashboard
```

## Docs

- `docs/RUN.md` — run modes, split routing, troubleshooting
- `docs/INSTALLATION_GUIDE.md` — full install steps
- `docs/DEVELOPING_APPS.md` — app development
- `docs/DAEMON_INTEGRATION.md` — Pi daemon integration
- `src/DAEMON_INTEGRATION.md` — src-level daemon notes

## Claude Code Guidelines

- No emojis, no [NEW] markers, no "vs" comparisons
- Concise, technical, factual only
- No fluff, benefits sections, or marketing language
- Commits: imperative mood, no emojis, no Co-Authored-By lines
- Comments: minimal, explain "why" not "what"
