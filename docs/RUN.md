# Running TARS

## Prerequisites

- Pi must be on the network (Tailscale: `tars`, or local: `tars.local`)
- Mac virtual environment activated

```bash
cd ~/Desktop/tars-conversation-app
conda activate base  # or however your env is set up
```

---

## Start

**1. Pi daemon** (if not already running)

```bash
ssh tars-pi "cd ~/tars && python tars_daemon.py"
```

**2. Mac bot + Gradio UI**

```bash
python src/tars_bot.py --gradio
```

Gradio opens at: `http://localhost:7860`

---

## Modes

| Command | Description |
|---|---|
| `python src/tars_bot.py --gradio` | Bot + Gradio UI (metrics, conversation log) |
| `python src/tars_bot.py` | Bot only, no UI |
| `python src/tars_bot.py --gradio --gradio-port 8080` | Custom port |

---

## Verify it's working

In Gradio:
- Status dot turns green when pipeline is ready
- Speak to the Pi mic — transcription appears in Conversation tab
- Metrics tab shows STT / LLM / TTS latency per turn

In terminal logs, look for:
```
pipeline is now ready
STT=Deepgram Nova-3, LLM=gpt-oss-120b, TTS=ElevenLabs
```

---

## Split Routing (Tailscale exit node)

If using a Tailscale exit node (e.g. Singapore), latency-sensitive services (Soniox JP, Deepgram, ElevenLabs) are routed directly via the real WiFi gateway to avoid the detour.

**One-time install** (persists across reboots):
```bash
sudo bash scripts/install-split-routes.sh
```

**Run manually** (current session only):
```bash
sudo bash scripts/split-routes.sh
```

**Verify routes are active:**
```bash
netstat -rn -f inet | grep -E 'soniox|deepgram|elevenlabs|172\.66|104\.20|34\.8|208\.184'
# Each entry should show en0, not utun*
```

**Logs:**
```bash
tail -f /tmp/tars-split-routes.log
```

Hosts routed directly:
- `stt-rt.jp.soniox.com` — Soniox JP STT
- `api.deepgram.com` — Deepgram STT
- `api.elevenlabs.io` — ElevenLabs TTS

---

## Troubleshooting

**Pi not reachable**
```bash
ping tars.local
ssh tars-pi
```

**Bot crashes on startup (Cerebras 429)**
Cerebras is rate-limited. Wait a few seconds and restart.

**Gradio not opening**
Make sure you passed `--gradio`. Without the flag, no UI starts.

**WebRTC disconnects mid-session**
Pi daemon may have crashed. SSH in and restart:
```bash
ssh tars-pi "cd ~/tars && python tars_daemon.py"
```
Then restart the Mac bot.

**STT N/A on a turn**
Occasionally happens when Silero VAD doesn't detect speech via the VAD path — Deepgram doesn't emit a TTFB metric for that turn. Not a bug, just a miss.
