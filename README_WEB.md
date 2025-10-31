# Qwen3 Omni Web (Next.js)

A minimal web UI that:
- Shows your camera preview
- Lets you send text prompts
- Streams model text and base64 WAV audio
- Plays the audio when the stream completes

## Setup

1) Create `.env.local` with your DashScope config:

DASHSCOPE_API_KEY=your_beijing_or_singapore_key
# Beijing (default):
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
# Or Singapore:
# DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1

2) Install and run:

npm install
npm run dev
# open http://localhost:3000

## Notes
- The API route `/api/chat` proxies streaming responses and emits JSON lines per chunk:
  { textDelta?: string, audioBase64Delta?: string }
- Audio chunks are concatenated and saved as a WAV Blob in the client.
- Camera is preview-only (no mic).
