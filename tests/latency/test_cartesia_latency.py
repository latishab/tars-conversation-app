"""
Cartesia STT Streaming Latency Test

Cartesia live STT does not stream interim results. It emits final transcripts
at natural sentence boundaries, then flushes remaining audio on "finalize".

Latency is measured as TTFS (time to final segment):
  ttfs = T_recv - (T_stream_start + last_word_end_seconds)

where `last_word_end_seconds` comes from the word-level timestamps in each
response. This tells us: how long after the last word was spoken did the
transcript arrive?

Two metrics collected:
  - Per-segment TTFS: latency at each sentence boundary during streaming
  - Post-finalize TTFS: latency of the flush after "finalize" is sent
    (most relevant for VAD-based pipeline: user stops → finalize → LLM)

Also measures connection latency for comparison.

Ref: https://docs.cartesia.ai/api-reference/stt/live

Usage:
    python tests/test_cartesia_latency.py
    python tests/test_cartesia_latency.py --conn-probes 3
"""

import os
import sys
import json
import time
import shutil
import asyncio
import tempfile
import statistics
import subprocess
import argparse
from pathlib import Path

import soundfile as sf
import websockets

SAMPLE_RATE = 16000
CHANNELS = 1
BYTES_PER_SAMPLE = 2
SECONDS_PER_BYTE = 1.0 / (SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE)

CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * CHUNK_MS / 1000) * BYTES_PER_SAMPLE

SILENCE_PAD_S = 1.5

BASE_URL = "api.cartesia.ai"
CARTESIA_VERSION = "2025-04-16"

TEST_PHRASE = (
    "The quick brown fox jumps over the lazy dog. "
    "She sells seashells by the seashore. "
    "How much wood would a woodchuck chuck if a woodchuck could chuck wood. "
    "Peter Piper picked a peck of pickled peppers. "
    "To be or not to be, that is the question. "
    "All that glitters is not gold."
)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def generate_test_audio(phrase: str) -> Path:
    if not shutil.which("say"):
        raise RuntimeError("`say` not found (macOS only)")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("`ffmpeg` not found")
    tmp = Path(tempfile.mkdtemp())
    aiff = tmp / "test.aiff"
    wav = tmp / "test.wav"
    print("Generating test audio via `say`...")
    subprocess.run(["say", "-v", "Alex", "-o", str(aiff), phrase], check=True, capture_output=True)
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff),
         "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-sample_fmt", "s16", str(wav)],
        check=True, capture_output=True,
    )
    print(f"  {wav}")
    return wav


def load_pcm(path: Path) -> bytes:
    data, sr = sf.read(str(path), dtype="int16", always_2d=False)
    if sr != SAMPLE_RATE:
        raise ValueError(f"File is {sr}Hz; need {SAMPLE_RATE}Hz")
    if data.ndim > 1:
        data = data[:, 0]
    return data.tobytes()


def make_silence(seconds: float) -> bytes:
    return b"\x00" * int(SAMPLE_RATE * seconds * BYTES_PER_SAMPLE)


# ---------------------------------------------------------------------------
# Phase 1 — connection latency
# ---------------------------------------------------------------------------

def measure_connection_latency(api_key: str, samples: int = 5) -> float:
    ws_url = f"wss://{BASE_URL}/stt/websocket?model=ink-whisper&language=en&encoding=pcm_s16le&sample_rate={SAMPLE_RATE}"
    headers = {"Cartesia-Version": CARTESIA_VERSION, "X-API-Key": api_key}

    async def run():
        times = []
        for i in range(samples):
            t0 = time.perf_counter()
            async with websockets.connect(ws_url, additional_headers=headers):
                pass
            t = time.perf_counter() - t0
            times.append(t)
            print(f"  probe {i + 1}: {t * 1000:.0f}ms")
        return times

    print(f"\nPhase 1 — connection latency ({samples} probes)")
    times = asyncio.run(run())
    median = statistics.median(times)
    print(f"  median: {median * 1000:.0f}ms  min: {min(times) * 1000:.0f}ms  max: {max(times) * 1000:.0f}ms")
    return median


# ---------------------------------------------------------------------------
# Phase 2 — transcription latency
# ---------------------------------------------------------------------------

async def _run_test_async(api_key: str, speech_pcm: bytes) -> dict:
    pcm = speech_pcm + make_silence(SILENCE_PAD_S)
    speech_duration_s = len(speech_pcm) * SECONDS_PER_BYTE

    ws_url = (
        f"wss://{BASE_URL}/stt/websocket"
        f"?model=ink-whisper&language=en&encoding=pcm_s16le&sample_rate={SAMPLE_RATE}"
    )
    headers = {"Cartesia-Version": CARTESIA_VERSION, "X-API-Key": api_key}

    segment_ttfs: list[float] = []   # TTFS at natural sentence boundaries
    post_finalize_ttfs: float | None = None
    T_start: float = 0.0
    T_finalize: float | None = None

    print(f"\n  [cartesia] connecting to {BASE_URL}...")

    async with websockets.connect(ws_url, additional_headers=headers) as ws:
        print(f"  [cartesia] connected\n")

        async def receiver():
            nonlocal post_finalize_ttfs
            async for raw in ws:
                T_recv = time.perf_counter()
                msg = json.loads(raw)

                if msg.get("type") == "transcript" and msg.get("is_final"):
                    text = msg.get("text", "").strip()
                    words = msg.get("words", [])
                    duration = msg.get("duration")

                    # transcript_cursor = end time of last word in this segment
                    if words:
                        last_word_end = words[-1]["end"]
                    elif duration:
                        last_word_end = duration
                    else:
                        continue

                    # TTFS = time transcript arrived - time that audio position was streamed
                    T_audio_position = T_start + last_word_end
                    ttfs = (T_recv - T_audio_position) * 1000

                    # Post-finalize: segment that arrives after finalize was sent
                    if T_finalize is not None and T_recv > T_finalize:
                        post_finalize_ttfs = (T_recv - T_finalize) * 1000
                        print(
                            f"  [post-finalize]  {text!r:50s}  "
                            f"ttfs_after_finalize={post_finalize_ttfs:.0f}ms"
                        )
                    else:
                        segment_ttfs.append(ttfs)
                        print(
                            f"  [segment]        {text!r:50s}  "
                            f"last_word_end={last_word_end:.2f}s  ttfs={ttfs:.0f}ms"
                        )

                elif msg.get("type") == "flush_done":
                    print(f"  [flush_done]")

                elif msg.get("type") == "error":
                    print(f"  [error] {msg}")
                    return

        recv_task = asyncio.create_task(receiver())

        # Stream at real-time pace
        T_start = time.perf_counter()
        offset = 0
        while offset < len(pcm):
            chunk = pcm[offset: offset + CHUNK_BYTES]
            if not chunk:
                break
            await ws.send(chunk)
            offset += CHUNK_BYTES
            await asyncio.sleep(CHUNK_MS / 1000)

        # Send finalize to flush remaining buffered audio
        T_finalize = time.perf_counter()
        print(f"\n  >>> finalize sent at +{(T_finalize - T_start) * 1000:.0f}ms")
        await ws.send("finalize")

        try:
            await asyncio.wait_for(recv_task, timeout=8.0)
        except asyncio.TimeoutError:
            print("  [cartesia] timeout waiting for response")
            recv_task.cancel()

    return {
        "speech_duration_s": round(speech_duration_s, 1),
        "segment_ttfs": segment_ttfs,
        "post_finalize_ttfs_ms": round(post_finalize_ttfs) if post_finalize_ttfs else None,
    }


def run_test(api_key: str, speech_pcm: bytes) -> dict:
    return asyncio.run(_run_test_async(api_key, speech_pcm))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(result: dict, conn_latency: float | None):
    s = sorted(result["segment_ttfs"]) if result["segment_ttfs"] else []
    pf = result["post_finalize_ttfs_ms"]

    print("\n" + "=" * 65)
    print("RESULTS SUMMARY  —  Cartesia ink-whisper")
    print("=" * 65)
    print(f"Speech duration:  {result['speech_duration_s']}s")
    if conn_latency:
        print(f"Connection overhead: {conn_latency * 1000:.0f}ms")
    print()

    if s:
        print("Per-segment TTFS (sentence boundary → transcript):")
        print(f"  samples: {len(s)}")
        print(f"  min:     {min(s):.0f}ms")
        print(f"  median:  {statistics.median(s):.0f}ms")
        print(f"  mean:    {statistics.mean(s):.0f}ms")
        print(f"  max:     {max(s):.0f}ms")

    print()
    if pf is not None:
        print(f"Post-finalize TTFS (VAD fires → transcript): {pf}ms")
        print(f"  (user stops speaking → pipeline receives final transcript)")

    print()
    print("Context for comparison (from Deepgram nova-3 test):")
    print("  nova-3 streaming lag:    ~300ms median (continuous, during speech)")
    print("  nova-3 p95 lag:          ~400ms")
    print()
    print("Note: Cartesia buffers per sentence — no interim results during")
    print("speech. Post-finalize TTFS is the comparable pipeline metric.")
    print("=" * 65)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Cartesia STT latency test")
    parser.add_argument("--file", help="Path to 16kHz mono WAV. Omit to auto-generate via `say`.")
    parser.add_argument("--conn-probes", type=int, default=5)
    parser.add_argument("--skip-conn", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("CARTESIA_API_KEY")
    if not api_key:
        for fname in (".env.local", ".env"):
            env_path = Path(__file__).parent.parent / fname
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("CARTESIA_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
            if api_key:
                break

    if not api_key:
        print("Error: CARTESIA_API_KEY not set.")
        sys.exit(1)

    if args.file:
        audio_path = Path(args.file)
        if not audio_path.exists():
            print(f"Error: {audio_path} not found")
            sys.exit(1)
    else:
        audio_path = generate_test_audio(TEST_PHRASE)

    speech_pcm = load_pcm(audio_path)

    conn_latency = None
    if not args.skip_conn:
        try:
            conn_latency = measure_connection_latency(api_key, samples=args.conn_probes)
        except Exception as e:
            print(f"Connection test failed: {e}")

    print(f"\n{'='*65}")
    print("Phase 2 — transcription latency (Cartesia ink-whisper)")
    print("=" * 65)
    result = run_test(api_key=api_key, speech_pcm=speech_pcm)
    print_summary(result, conn_latency)


if __name__ == "__main__":
    main()
