"""
ElevenLabs Realtime STT Latency Test (scribe_v2_realtime)

ElevenLabs streams partial_transcript messages during speech (no timestamps),
then emits committed_transcript_with_timestamps after a commit signal.

Metrics collected:
  - Partial interval: wall-clock gap between consecutive partial transcripts
    (streaming responsiveness during speech)
  - Post-commit TTFS: time from commit sent to committed transcript received
    (comparable to Cartesia post-finalize and Deepgram streaming lag at VAD fire)
  - Word-timestamp TTFS: T_recv - (T_stream_start + last_word.end)
    (accurate latency using word timestamps from committed response)

Endpoint: wss://api.elevenlabs.io/v1/speech-to-text/realtime
Auth:      xi-api-key header
Audio:     base64-encoded PCM sent as JSON input_audio_chunk messages
Commit:    empty audio_base_64 with commit=true (simulates VAD UserStoppedSpeaking)

Ref: https://elevenlabs.io/docs/api-reference/speech-to-text/v-1-speech-to-text-realtime

Usage:
    python tests/test_elevenlabs_latency.py
    ELEVENLABS_API_KEY=your_key python tests/test_elevenlabs_latency.py
    python tests/test_elevenlabs_latency.py --skip-conn
"""

import os
import sys
import json
import time
import base64
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

BASE_URL = "api.elevenlabs.io"
MODEL = "scribe_v2_realtime"
AUDIO_FORMAT = "pcm_16000"

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


def encode_chunk(pcm_bytes: bytes) -> str:
    return base64.b64encode(pcm_bytes).decode("utf-8")


# ---------------------------------------------------------------------------
# Phase 1 — connection latency
# ---------------------------------------------------------------------------

def measure_connection_latency(api_key: str, samples: int = 5) -> float:
    ws_url = (
        f"wss://{BASE_URL}/v1/speech-to-text/realtime"
        f"?model_id={MODEL}&audio_format={AUDIO_FORMAT}&commit_strategy=manual"
    )
    headers = {"xi-api-key": api_key}

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
        f"wss://{BASE_URL}/v1/speech-to-text/realtime"
        f"?model_id={MODEL}&audio_format={AUDIO_FORMAT}"
        f"&commit_strategy=manual&include_timestamps=true"
    )
    headers = {"xi-api-key": api_key}

    partial_times: list[float] = []     # wall-clock time of each partial
    partial_texts: list[str] = []
    post_commit_ttfs_ms: float | None = None
    word_timestamp_ttfs_ms: float | None = None
    T_start: float = 0.0
    T_commit: float | None = None

    print(f"\n  [elevenlabs] connecting...")

    async with websockets.connect(ws_url, additional_headers=headers) as ws:
        print(f"  [elevenlabs] connected\n")

        async def receiver():
            nonlocal post_commit_ttfs_ms, word_timestamp_ttfs_ms
            async for raw in ws:
                T_recv = time.perf_counter()
                msg = json.loads(raw)
                mtype = msg.get("message_type", "")

                if mtype == "session_started":
                    cfg = msg.get("session_configuration", {})
                    print(f"  [session_started]  model={cfg.get('model_id')}  format={cfg.get('audio_format')}")

                elif mtype == "partial_transcript":
                    text = msg.get("text", "").strip()
                    if not text:
                        continue
                    partial_times.append(T_recv)
                    partial_texts.append(text)
                    interval = ""
                    if len(partial_times) > 1:
                        interval = f"  interval={(partial_times[-1] - partial_times[-2]) * 1000:.0f}ms"
                    print(f"  [partial]   {text!r:55s}{interval}")

                elif mtype == "committed_transcript_with_timestamps":
                    text = msg.get("text", "").strip()
                    words = msg.get("words", [])

                    if T_commit is not None:
                        post_commit_ttfs_ms = (T_recv - T_commit) * 1000

                    # Word-timestamp TTFS: how long after last word was spoken did transcript arrive
                    if words:
                        last_word_end = words[-1].get("end", 0)
                        word_timestamp_ttfs_ms = (T_recv - (T_start + last_word_end)) * 1000

                    print(
                        f"\n  [committed]  {text!r:55s}  "
                        f"post_commit={post_commit_ttfs_ms:.0f}ms  "
                        f"word_ttfs={word_timestamp_ttfs_ms:.0f}ms"
                        if (post_commit_ttfs_ms and word_timestamp_ttfs_ms) else
                        f"\n  [committed]  {text!r}"
                    )
                    if words:
                        print(f"               last_word='{words[-1].get('word','').strip()}'  end={words[-1].get('end',0):.2f}s")
                    return

                elif mtype in ("committed_transcript",):
                    # Skipped when include_timestamps=true (replaced by _with_timestamps)
                    pass

                elif mtype and "error" in mtype.lower():
                    print(f"  [error] {mtype}: {msg.get('error', msg)}")
                    return

        recv_task = asyncio.create_task(receiver())

        # Stream at real-time pace
        T_start = time.perf_counter()
        offset = 0
        while offset < len(pcm):
            chunk = pcm[offset: offset + CHUNK_BYTES]
            if not chunk:
                break
            await ws.send(json.dumps({
                "message_type": "input_audio_chunk",
                "audio_base_64": encode_chunk(chunk),
                "commit": False,
                "sample_rate": SAMPLE_RATE,
            }))
            offset += CHUNK_BYTES
            await asyncio.sleep(CHUNK_MS / 1000)

        # Send commit (simulates VAD UserStoppedSpeaking)
        T_commit = time.perf_counter()
        print(f"\n  >>> commit sent at +{(T_commit - T_start) * 1000:.0f}ms")
        await ws.send(json.dumps({
            "message_type": "input_audio_chunk",
            "audio_base_64": "",
            "commit": True,
            "sample_rate": SAMPLE_RATE,
        }))

        try:
            await asyncio.wait_for(recv_task, timeout=10.0)
        except asyncio.TimeoutError:
            print("  [elevenlabs] timeout waiting for committed transcript")
            recv_task.cancel()

    # Partial interval stats
    intervals = []
    if len(partial_times) > 1:
        intervals = [(partial_times[i] - partial_times[i - 1]) * 1000
                     for i in range(1, len(partial_times))]

    return {
        "speech_duration_s": round(speech_duration_s, 1),
        "partial_count": len(partial_times),
        "partial_interval_median_ms": round(statistics.median(intervals)) if intervals else None,
        "partial_interval_min_ms": round(min(intervals)) if intervals else None,
        "partial_interval_max_ms": round(max(intervals)) if intervals else None,
        "post_commit_ttfs_ms": round(post_commit_ttfs_ms) if post_commit_ttfs_ms else None,
        "word_timestamp_ttfs_ms": round(word_timestamp_ttfs_ms) if word_timestamp_ttfs_ms else None,
    }


def run_test(api_key: str, speech_pcm: bytes) -> dict:
    return asyncio.run(_run_test_async(api_key, speech_pcm))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(result: dict, conn_latency: float | None):
    print("\n" + "=" * 65)
    print("RESULTS SUMMARY  —  ElevenLabs scribe_v2_realtime")
    print("=" * 65)
    print(f"Speech duration:     {result['speech_duration_s']}s")
    if conn_latency:
        print(f"Connection overhead: {conn_latency * 1000:.0f}ms")
    print()
    print(f"Partial transcripts: {result['partial_count']}")
    if result["partial_interval_median_ms"] is not None:
        print(f"Partial interval:    median={result['partial_interval_median_ms']}ms  "
              f"min={result['partial_interval_min_ms']}ms  "
              f"max={result['partial_interval_max_ms']}ms")
    print()
    if result["post_commit_ttfs_ms"] is not None:
        print(f"Post-commit TTFS:    {result['post_commit_ttfs_ms']}ms  (VAD fires → transcript)")
    if result["word_timestamp_ttfs_ms"] is not None:
        print(f"Word-timestamp TTFS: {result['word_timestamp_ttfs_ms']}ms  (last word end → transcript)")
    print()
    print("Comparison:")
    print("  Deepgram nova-3:       300ms streaming lag (continuous, during speech)")
    print("  Cartesia ink-whisper:  357ms post-finalize / 463ms per-segment")
    print("=" * 65)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="ElevenLabs realtime STT latency test")
    parser.add_argument("--file", help="Path to 16kHz mono WAV. Omit to auto-generate via `say`.")
    parser.add_argument("--conn-probes", type=int, default=5)
    parser.add_argument("--skip-conn", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        for fname in (".env.local", ".env"):
            env_path = Path(__file__).parent.parent / fname
            if env_path.exists():
                for line in env_path.read_text().splitlines():
                    if line.startswith("ELEVENLABS_API_KEY="):
                        api_key = line.split("=", 1)[1].strip()
                        break
            if api_key:
                break

    if not api_key:
        print("Error: ELEVENLABS_API_KEY not set.")
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
    print("Phase 2 — transcription latency (ElevenLabs scribe_v2_realtime)")
    print("=" * 65)
    result = run_test(api_key=api_key, speech_pcm=speech_pcm)
    print_summary(result, conn_latency)


if __name__ == "__main__":
    main()
