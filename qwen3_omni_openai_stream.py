import os
import base64
from dotenv import load_dotenv
from openai import OpenAI

# Load env
load_dotenv()

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ),
)

if not client.api_key:
    raise RuntimeError("DASHSCOPE_API_KEY not set. Set it in env or .env.")

try:
    completion = client.chat.completions.create(
        model="qwen3-omni-flash",
        messages=[{"role": "user", "content": "Who are you"}],
        modalities=["text", "audio"],
        audio={"voice": "Cherry", "format": "wav"},
        stream=True,
        stream_options={"include_usage": True},
    )

    print("Model response:")
    audio_chunks = []

    for chunk in completion:
        if not chunk or not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        # Text tokens
        content = getattr(delta, "content", None)
        if content:
            print(content, end="", flush=True)

        # Audio base64 data (OpenAI-compatible returns incremental base64 in delta.audio.data)
        audio = getattr(delta, "audio", None)
        if isinstance(audio, dict):
            data_b64 = audio.get("data")
            if data_b64:
                audio_chunks.append(data_b64)

    if audio_chunks:
        audio_base64_string = "".join(audio_chunks)
        wav_bytes = base64.b64decode(audio_base64_string)
        with open("audio_assistant.wav", "wb") as f:
            f.write(wav_bytes)
        print("\nAudio file saved to: audio_assistant.wav")

except Exception as e:
    print(f"Request failed: {e}")
