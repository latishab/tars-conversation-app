"""
Deepgram STT Streaming Latency Test

Two phases, no microphone required:

  Phase 1 – Connection test
    Times WebSocket connect/close N times for network + TLS overhead baseline.

  Phase 2 – Transcription test, per model:

    nova-2 / nova-3 (v1 API):
      audio_cursor     = total seconds of audio submitted (X)
      transcript_cursor = start + duration from each interim result (Y)
      streaming_latency = X - Y

    flux-general-en (v2 API):
      Different protocol: TurnInfo messages with Update/EndOfTurn events.
      No start+duration fields, so streaming_latency can't be computed the
      same way. Instead measures:
        - Update interval: wall-clock gap between consecutive Update events
        - EOT latency: time from last audio chunk to EndOfTurn event
          (the relevant metric for voice assistant pipeline latency)

Ref: https://developers.deepgram.com/docs/measuring-streaming-latency

Usage:
    DEEPGRAM_API_KEY=your_key python tests/test_deepgram_latency.py
    DEEPGRAM_API_KEY=your_key python tests/test_deepgram_latency.py --models nova-2,nova-3,flux-general-en
    DEEPGRAM_API_KEY=your_key python tests/test_deepgram_latency.py --file path/to/audio.wav
"""

import os
import sys
import time
import json
import queue
import shutil
import asyncio
import tempfile
import threading
import statistics
import subprocess
import argparse
from pathlib import Path

import soundfile as sf
import numpy as np
from deepgram import DeepgramClient, LiveTranscriptionEvents, LiveOptions

SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2  # int16 / linear16
SECONDS_PER_BYTE = 1.0 / (SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE)

CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * CHUNK_MS / 1000) * BYTES_PER_SAMPLE

# Silence appended after speech so Flux can detect end-of-turn
SILENCE_PAD_S = 2.0

TEST_PHRASE = (
    "The quick brown fox jumps over the lazy dog. "
    "She sells seashells by the seashore. "
    "How much wood would a woodchuck chuck if a woodchuck could chuck wood. "
    "Peter Piper picked a peck of pickled peppers. "
    "To be or not to be, that is the question. "
    "All that glitters is not gold."
)


# ---------------------------------------------------------------------------
# Phase 1 — connection latency
# ---------------------------------------------------------------------------

def measure_connection_latency(api_key: str, samples: int = 5) -> float:
    import websocket
    url = "wss://api.deepgram.com/v1/listen"
    headers = [f"Authorization: Token {api_key}"]
    times = []

    print(f"Phase 1 — connection latency ({samples} probes)")
    for i in range(samples):
        t0 = time.perf_counter()
        ws = websocket.create_connection(url, header=headers, timeout=10)
        ws.close()
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
        print(f"  probe {i + 1}: {elapsed * 1000:.0f}ms")

    median = statistics.median(times)
    print(f"  median: {median * 1000:.0f}ms  min: {min(times) * 1000:.0f}ms  max: {max(times) * 1000:.0f}ms")
    return median


# ---------------------------------------------------------------------------
# Audio preparation
# ---------------------------------------------------------------------------

def generate_test_audio(phrase: str) -> Path:
    if not shutil.which("say"):
        raise RuntimeError("`say` not found (macOS only)")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("`ffmpeg` not found")

    tmp_dir = Path(tempfile.mkdtemp())
    aiff_path = tmp_dir / "test.aiff"
    wav_path = tmp_dir / "test.wav"

    print(f"\nGenerating test audio via `say`...")
    subprocess.run(["say", "-v", "Alex", "-o", str(aiff_path), phrase], check=True, capture_output=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff_path),
         "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-sample_fmt", "s16", str(wav_path)],
        check=True, capture_output=True,
    )
    print(f"  {wav_path}")
    return wav_path


def load_pcm(path: Path) -> bytes:
    data, sr = sf.read(str(path), dtype="int16", always_2d=False)
    if sr != SAMPLE_RATE:
        raise ValueError(f"File is {sr}Hz; need {SAMPLE_RATE}Hz")
    if data.ndim > 1:
        data = data[:, 0]
    return data.tobytes()


def make_silence(seconds: float) -> bytes:
    return b"\x00" * int(SAMPLE_RATE * seconds) * BYTES_PER_SAMPLE


# ---------------------------------------------------------------------------
# nova-2 / nova-3 test  (v1 API, interim_results with start+duration)
# ---------------------------------------------------------------------------

def run_nova_test(api_key: str, model: str, speech_pcm: bytes, conn_latency: float | None) -> dict:
    pcm = speech_pcm + make_silence(SILENCE_PAD_S)

    latency_samples: list[float] = []
    bytes_sent = 0
    transcript_cursor = 0.0
    lock = threading.Lock()

    dg = DeepgramClient(api_key)
    conn = dg.listen.websocket.v("1")

    def on_open(self, *a, **kw):
        print(f"  [deepgram] connected")

    def on_transcript(self, result, **kw):
        nonlocal transcript_cursor
        alt = result.channel.alternatives[0] if result.channel.alternatives else None
        if not alt or not alt.transcript.strip():
            return
        cursor = result.start + result.duration
        with lock:
            if cursor > transcript_cursor:
                transcript_cursor = cursor
            ac = bytes_sent * SECONDS_PER_BYTE
            lag = ac - transcript_cursor
            if lag >= 0:
                latency_samples.append(lag)
        label = "[final]  " if result.is_final else "[interim]"
        print(f"  {label}  {alt.transcript!r:45s}  ac={ac:.2f}s  tc={transcript_cursor:.2f}s  lag={lag*1000:.0f}ms")

    def on_error(self, error, **kw):
        print(f"  [error] {error}")

    def on_close(self, *a, **kw):
        print(f"  [deepgram] closed")

    conn.on(LiveTranscriptionEvents.Open, on_open)
    conn.on(LiveTranscriptionEvents.Transcript, on_transcript)
    conn.on(LiveTranscriptionEvents.Error, on_error)
    conn.on(LiveTranscriptionEvents.Close, on_close)

    conn.start(LiveOptions(
        model=model, language="en", encoding="linear16",
        sample_rate=SAMPLE_RATE, channels=CHANNELS,
        interim_results=True, smart_format=True, punctuate=True,
    ))

    stop = threading.Event()

    def sender():
        nonlocal bytes_sent
        offset = 0
        while offset < len(pcm) and not stop.is_set():
            chunk = pcm[offset: offset + CHUNK_BYTES]
            if not chunk:
                break
            conn.send(chunk)
            with lock:
                bytes_sent += len(chunk)
            offset += CHUNK_BYTES
            time.sleep(CHUNK_MS / 1000)

    t = threading.Thread(target=sender, daemon=True)
    t.start()
    t.join()
    time.sleep(2.0)
    conn.finish()

    speech_duration = len(speech_pcm) * SECONDS_PER_BYTE
    s = sorted(latency_samples) if latency_samples else []
    return {
        "model": model,
        "method": "audio_cursor - transcript_cursor",
        "speech_duration_s": round(speech_duration, 1),
        "samples": len(s),
        "min_ms": round(min(s) * 1000) if s else None,
        "median_ms": round(statistics.median(s) * 1000) if s else None,
        "mean_ms": round(statistics.mean(s) * 1000) if s else None,
        "p95_ms": round(s[max(0, int(len(s) * 0.95) - 1)] * 1000) if s else None,
        "max_ms": round(max(s) * 1000) if s else None,
        "conn_latency_ms": round(conn_latency * 1000) if conn_latency else None,
        "transcription_only_ms": round(max(0, statistics.median(s) - conn_latency) * 1000) if (s and conn_latency) else None,
    }


# ---------------------------------------------------------------------------
# flux-general-en test  (v2 API, TurnInfo messages)
# ---------------------------------------------------------------------------

async def _flux_test_async(api_key: str, model: str, speech_pcm: bytes) -> dict:
    import websockets

    pcm = speech_pcm + make_silence(SILENCE_PAD_S)
    speech_duration = len(speech_pcm) * SECONDS_PER_BYTE

    params = f"model={model}&sample_rate={SAMPLE_RATE}&encoding=linear16"
    url = f"wss://api.deepgram.com/v2/listen?{params}"
    headers = {"Authorization": f"Token {api_key}"}

    update_times: list[float] = []   # wall-clock time of each Update
    update_texts: list[str] = []
    eot_latency_ms: float | None = None
    last_audio_sent_at: float | None = None

    print(f"  [deepgram] connecting to v2 ({model})")

    async with websockets.connect(url, additional_headers=headers) as ws:
        print(f"  [deepgram] connected")

        # Receive loop (background task)
        async def receiver():
            nonlocal eot_latency_ms
            async for raw in ws:
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)
                t_recv = time.perf_counter()
                msg_type = msg.get("type")
                event = msg.get("event")
                transcript = msg.get("transcript", "")

                if msg_type == "Connected":
                    print(f"  [flux] Connected")

                elif msg_type == "TurnInfo":
                    if event == "StartOfTurn":
                        print(f"  [flux] StartOfTurn — {transcript!r}")

                    elif event == "Update":
                        update_times.append(t_recv)
                        update_texts.append(transcript)
                        interval = ""
                        if len(update_times) > 1:
                            interval = f"  interval={( update_times[-1] - update_times[-2])*1000:.0f}ms"
                        print(f"  [Update]  {transcript!r:55s}{interval}")

                    elif event in ("EndOfTurn", "EagerEndOfTurn"):
                        if last_audio_sent_at is not None:
                            eot_latency_ms = (t_recv - last_audio_sent_at) * 1000
                        print(f"  [{event}]  {transcript!r}  eot_latency={eot_latency_ms:.0f}ms" if eot_latency_ms else f"  [{event}]  {transcript!r}")
                        return  # done

                elif msg_type == "Error":
                    print(f"  [flux] Error: {msg}")
                    return

        recv_task = asyncio.create_task(receiver())

        # Send audio at real-time pace, track last send time
        t_start = time.perf_counter()
        offset = 0
        while offset < len(pcm):
            chunk = pcm[offset: offset + CHUNK_BYTES]
            if not chunk:
                break
            await ws.send(chunk)
            last_audio_sent_at = time.perf_counter()
            offset += CHUNK_BYTES
            await asyncio.sleep(CHUNK_MS / 1000)

        # Wait for EOT (up to 5s after last audio)
        try:
            await asyncio.wait_for(recv_task, timeout=5.0)
        except asyncio.TimeoutError:
            print("  [flux] timeout waiting for EndOfTurn")
            recv_task.cancel()

    # Update interval stats
    intervals = []
    if len(update_times) > 1:
        intervals = [(update_times[i] - update_times[i-1]) * 1000 for i in range(1, len(update_times))]

    return {
        "model": model,
        "method": "EOT latency + Update interval",
        "speech_duration_s": round(speech_duration, 1),
        "update_count": len(update_times),
        "update_interval_median_ms": round(statistics.median(intervals)) if intervals else None,
        "update_interval_min_ms": round(min(intervals)) if intervals else None,
        "update_interval_max_ms": round(max(intervals)) if intervals else None,
        "eot_latency_ms": round(eot_latency_ms) if eot_latency_ms else None,
        "silence_pad_s": SILENCE_PAD_S,
    }


def run_flux_test(api_key: str, model: str, speech_pcm: bytes) -> dict:
    return asyncio.run(_flux_test_async(api_key, model, speech_pcm))


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------

def print_summary(results: list[dict], conn_latency: float | None):
    print("\n" + "=" * 65)
    print("RESULTS SUMMARY")
    print("=" * 65)

    if conn_latency is not None:
        print(f"Connection overhead (network + TLS): {conn_latency * 1000:.0f}ms\n")

    for r in results:
        print(f"Model: {r['model']}  ({r.get('method', '')})")
        print(f"  Audio: {r['speech_duration_s']}s speech")

        if "median_ms" in r:
            # nova-2 / nova-3
            print(f"  Streaming latency (audio_cursor - transcript_cursor):")
            print(f"    min={r['min_ms']}ms  median={r['median_ms']}ms  mean={r['mean_ms']}ms  p95={r['p95_ms']}ms  max={r['max_ms']}ms")
            if r.get("transcription_only_ms") is not None:
                print(f"    transcription-only (est): {r['transcription_only_ms']}ms")
        else:
            # flux
            print(f"  Updates received: {r['update_count']}")
            if r.get("update_interval_median_ms") is not None:
                print(f"  Update interval: median={r['update_interval_median_ms']}ms  min={r['update_interval_min_ms']}ms  max={r['update_interval_max_ms']}ms")
            eot = r.get('eot_latency_ms')
            pad = r.get('silence_pad_s')
            print(f"  EOT latency after last audio: {eot}ms  (includes {pad}s silence pad)")
        print()

    print("=" * 65)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Deepgram STT latency comparison (no microphone)")
    parser.add_argument("--models", default="nova-2,nova-3,flux-general-en",
                        help="Comma-separated list of models to test (default: nova-2,nova-3,flux-general-en)")
    parser.add_argument("--file", help="Path to WAV file (16kHz mono). Omit to auto-generate via `say`.")
    parser.add_argument("--conn-probes", type=int, default=5)
    parser.add_argument("--skip-conn", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        env_path = Path(__file__).parent.parent / ".env.local"
        if not env_path.exists():
            env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DEEPGRAM_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break

    if not api_key:
        print("Error: DEEPGRAM_API_KEY not set.")
        sys.exit(1)

    models = [m.strip() for m in args.models.split(",") if m.strip()]

    # Phase 1
    conn_latency = None
    if not args.skip_conn:
        try:
            conn_latency = measure_connection_latency(api_key, samples=args.conn_probes)
        except Exception as e:
            print(f"Connection test failed: {e}")

    # Prepare audio
    if args.file:
        audio_path = Path(args.file)
        if not audio_path.exists():
            print(f"Error: {audio_path} not found")
            sys.exit(1)
    else:
        audio_path = generate_test_audio(TEST_PHRASE)

    speech_pcm = load_pcm(audio_path)

    # Phase 2 — run each model
    results = []
    for model in models:
        print(f"\n{'='*65}")
        print(f"Testing: {model}")
        print("=" * 65)
        try:
            if "flux" in model.lower():
                r = run_flux_test(api_key=api_key, model=model, speech_pcm=speech_pcm)
            else:
                r = run_nova_test(api_key=api_key, model=model, speech_pcm=speech_pcm, conn_latency=conn_latency)
            results.append(r)
        except Exception as e:
            print(f"  FAILED: {e}")

    print_summary(results, conn_latency)


if __name__ == "__main__":
    main()
