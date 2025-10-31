# TARS-OMNI (CASE Framework)

A minimal multimodal web app and Python examples for Qwen3 Omni (text+audio) with optional vision snapshot.

- Web UI (Next.js): camera preview, text input, streamed text, and WAV audio playback.
- Python: OpenAI-compatible client for text+audio streaming.
- Goal: support CASE (Collaborative Assistance and Situational Engine) research workflow on the TARS robot platform.

## Run the Web UI

1) Create `.env.local`:

DASHSCOPE_API_KEY=your_key
# Beijing (default)
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# Or Singapore
# DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

2) Install and dev:

npm install
npm run dev
# http://localhost:3000

## Vision Snapshot
- Press "Send" to send your text and a JPEG snapshot from the camera to the model.
- If inline `image_url` data URLs are rejected, switch to a hosted URL or DashScope native multimodal endpoint.

## Python Demo
- `qwen3_omni_openai_stream.py` streams text+audio. Set `DASHSCOPE_API_KEY`.

## Repo Structure
- `app/` Next.js app router pages and API
- `app/api/chat/route.ts` streams from DashScope compatible-mode
- `app/page.tsx` UI with camera + chat
- `README_WEB.md` quick web notes

## CASE (High-Level)
- Multimodal capture → Contextual memory → Temporal fusion → Intervention planner → Embodied controller.
- This repo provides the multimodal I/O surface to iterate on those modules.
