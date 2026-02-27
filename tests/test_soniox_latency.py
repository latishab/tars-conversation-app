"""
Soniox STT Streaming Latency Test

Measures streaming latency using Soniox's own processing metrics:

  audio_cursor_ms   = total milliseconds of audio submitted
  transcript_cursor = total_audio_proc_ms from each response
                      (Soniox reports how much audio it has processed)
  lag               = audio_cursor_ms - total_audio_proc_ms

Compares US vs Japan region endpoints.

Endpoints:
  US:  wss://stt-rt.soniox.com/transcribe-websocket
  JP:  wss://stt-rt.jp.soniox.com/transcribe-websocket

Ref: https://soniox.com/docs/stt/api-reference/websocket-api

Usage:
    python tests/test_soniox_latency.py
    python tests/test_soniox_latency.py --regions us
    python tests/test_soniox_latency.py --regions jp,us
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
MS_PER_BYTE = 1000.0 / (SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE)

CHUNK_MS = 100
CHUNK_BYTES = int(SAMPLE_RATE * CHUNK_MS / 1000) * BYTES_PER_SAMPLE

SILENCE_PAD_S = 1.5

REGIONS = {
    "us": "wss://stt-rt.soniox.com/transcribe-websocket",
    "jp": "wss://stt-rt.jp.soniox.com/transcribe-websocket",
    "eu": "wss://stt-rt.eu.soniox.com/transcribe-websocket",
}

TEST_PHRASE = (
    "The quick brown fox jumps over the lazy dog. "
    "She sells seashells by the seashore. "
    "How much wood would a woodchuck chuck if a woodchuck could chuck wood. "
    "Peter Piper picked a peck of pickled peppers. "
    "To be or not to be, that is the question. "
    "All that glitters is not gold."
)


# ---------------------------------------------------------------------------
# Audio preparation  (shared with deepgram test)
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

async def _probe_once(url: str) -> float:
    t0 = time.perf_counter()
    async with websockets.connect(url):
        pass
    return time.perf_counter() - t0


async def _measure_connection_latency_async(url: str, samples: int) -> float:
    times = []
    for i in range(samples):
        t = await _probe_once(url)
        times.append(t)
        print(f"  probe {i+1}: {t*1000:.0f}ms")
    median = statistics.median(times)
    print(f"  median: {median*1000:.0f}ms  min: {min(times)*1000:.0f}ms  max: {max(times)*1000:.0f}ms")
    return median


def measure_connection_latency(url: str, region: str, samples: int = 5) -> float:
    print(f"\nPhase 1 — connection latency [{region}] ({samples} probes)")
    return asyncio.run(_measure_connection_latency_async(url, samples))


# ---------------------------------------------------------------------------
# Phase 2 — transcription latency
# ---------------------------------------------------------------------------

async def _run_region_async(api_key: str, region: str, url: str, speech_pcm: bytes) -> dict:
    pcm = speech_pcm + make_silence(SILENCE_PAD_S)
    speech_duration_ms = len(speech_pcm) * MS_PER_BYTE

    latency_samples: list[float] = []
    transcript_tokens: list[str] = []
    bytes_sent = 0

    config = {
        "api_key": api_key,
        "model": "stt-rt-v4",
        "audio_format": "pcm_s16le",
        "sample_rate": SAMPLE_RATE,
        "num_channels": CHANNELS,
        "include_nonfinal": True,  # get interim tokens for continuous cursor tracking
    }

    print(f"\n  [soniox/{region}] connecting...")

    async with websockets.connect(url) as ws:
        print(f"  [soniox/{region}] connected")

        # Send config
        await ws.send(json.dumps(config))

        # Receive task runs concurrently with sender
        async def receiver():
            nonlocal bytes_sent
            async for raw in ws:
                if not isinstance(raw, str):
                    continue
                msg = json.loads(raw)

                if msg.get("error_code"):
                    print(f"  [error] {msg}")
                    return

                # total_audio_proc_ms = how much audio Soniox has processed
                # This is the transcript cursor per Soniox's own metrics
                total_proc_ms = msg.get("total_audio_proc_ms", 0)
                final_proc_ms = msg.get("final_audio_proc_ms", 0)

                tokens = msg.get("tokens", [])
                # Filter out control tokens (<end>, <fin>) and empty
                words = [t["text"] for t in tokens if t["text"] not in ("<end>", "<fin>", "")]
                transcript_tokens.extend(words)

                if total_proc_ms and total_proc_ms > 0:
                    audio_cursor_ms = bytes_sent * MS_PER_BYTE
                    lag = audio_cursor_ms - total_proc_ms
                    if lag >= 0:
                        latency_samples.append(lag)

                    text_preview = " ".join(transcript_tokens[-6:])
                    is_final = final_proc_ms >= total_proc_ms
                    label = "[final]  " if is_final else "[interim]"
                    print(
                        f"  {label}  {text_preview!r:50s}  "
                        f"ac={audio_cursor_ms:.0f}ms  tc={total_proc_ms:.0f}ms  lag={lag:.0f}ms"
                    )

                if msg.get("finished"):
                    print(f"  [soniox/{region}] finished")
                    return

        recv_task = asyncio.create_task(receiver())

        # Stream audio at real-time pace
        offset = 0
        while offset < len(pcm):
            chunk = pcm[offset: offset + CHUNK_BYTES]
            if not chunk:
                break
            await ws.send(chunk)
            bytes_sent += len(chunk)
            offset += CHUNK_BYTES
            await asyncio.sleep(CHUNK_MS / 1000)

        # Send empty frame to signal end of audio
        await ws.send(b"")

        try:
            await asyncio.wait_for(recv_task, timeout=10.0)
        except asyncio.TimeoutError:
            print(f"  [soniox/{region}] timeout waiting for finished")
            recv_task.cancel()

    s = sorted(latency_samples) if latency_samples else []
    return {
        "region": region,
        "url": url,
        "speech_duration_ms": round(speech_duration_ms),
        "samples": len(s),
        "min_ms": round(min(s)) if s else None,
        "median_ms": round(statistics.median(s)) if s else None,
        "mean_ms": round(statistics.mean(s)) if s else None,
        "p95_ms": round(s[max(0, int(len(s) * 0.95) - 1)]) if s else None,
        "max_ms": round(max(s)) if s else None,
        "transcript": " ".join(transcript_tokens),
    }


def run_region(api_key: str, region: str, url: str, speech_pcm: bytes) -> dict:
    return asyncio.run(_run_region_async(api_key, region, url, speech_pcm))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: list[dict], conn_latencies: dict):
    print("\n" + "=" * 65)
    print("RESULTS SUMMARY  —  Soniox (audio_cursor_ms - total_audio_proc_ms)")
    print("=" * 65)

    for r in results:
        region = r["region"]
        conn = conn_latencies.get(region)
        print(f"\nRegion: {region.upper()}  ({r['url']})")
        print(f"  Speech: {r['speech_duration_ms']}ms  |  Samples: {r['samples']}")
        if conn:
            print(f"  Connection overhead: {conn*1000:.0f}ms")
        if r["samples"]:
            print(f"  Streaming latency:")
            print(f"    min={r['min_ms']}ms  median={r['median_ms']}ms  mean={r['mean_ms']}ms  p95={r['p95_ms']}ms  max={r['max_ms']}ms")
            if conn:
                tx_only = max(0, r["median_ms"] - conn * 1000)
                print(f"    transcription-only (est): {tx_only:.0f}ms")
        else:
            print("  No samples collected.")
        if r.get("transcript"):
            print(f"  Transcript: {r['transcript'][:120]}")

    print("\n" + "=" * 65)

    # Side-by-side comparison if multiple regions
    if len(results) > 1:
        print(f"\n{'Region':<8} {'Conn (ms)':<12} {'Median lag':<13} {'p95 lag':<10}")
        print("-" * 45)
        for r in results:
            conn_ms = f"{conn_latencies.get(r['region'], 0)*1000:.0f}" if r["region"] in conn_latencies else "n/a"
            median = str(r["median_ms"]) if r["median_ms"] is not None else "n/a"
            p95 = str(r["p95_ms"]) if r["p95_ms"] is not None else "n/a"
            print(f"{r['region'].upper():<8} {conn_ms:<12} {median:<13} {p95:<10}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Soniox STT latency test")
    parser.add_argument("--regions", default="jp,us",
                        help="Comma-separated regions to test: jp, us, eu (default: jp,us)")
    parser.add_argument("--file", help="Path to 16kHz mono WAV. Omit to auto-generate via `say`.")
    parser.add_argument("--conn-probes", type=int, default=5)
    parser.add_argument("--skip-conn", action="store_true")
    args = parser.parse_args()

    # Load all env vars from .env.local / .env into os.environ
    for fname in (".env.local", ".env"):
        env_path = Path(__file__).parent.parent / fname
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
            break

    regions = [r.strip().lower() for r in args.regions.split(",") if r.strip()]
    for r in regions:
        if r not in REGIONS:
            print(f"Unknown region '{r}'. Available: {', '.join(REGIONS)}")
            sys.exit(1)

    # Prepare audio
    if args.file:
        audio_path = Path(args.file)
        if not audio_path.exists():
            print(f"Error: {audio_path} not found")
            sys.exit(1)
    else:
        audio_path = generate_test_audio(TEST_PHRASE)

    speech_pcm = load_pcm(audio_path)

    # Phase 1 — connection latency per region
    conn_latencies = {}
    if not args.skip_conn:
        for region in regions:
            try:
                conn_latencies[region] = measure_connection_latency(REGIONS[region], region, args.conn_probes)
            except Exception as e:
                print(f"  Connection probe failed for {region}: {e}")

    # Phase 2 — transcription test per region
    results = []
    for region in regions:
        api_key = (
            os.environ.get(f"SONIOX_API_KEY_{region.upper()}")
            or os.environ.get("SONIOX_API_KEY")
        )
        if not api_key:
            print(f"Error: no API key for region '{region}'. Set SONIOX_API_KEY_{region.upper()} or SONIOX_API_KEY.")
            sys.exit(1)
        print(f"\n{'='*65}")
        print(f"Testing region: {region.upper()}")
        print("=" * 65)
        try:
            r = run_region(api_key=api_key, region=region, url=REGIONS[region], speech_pcm=speech_pcm)
            results.append(r)
        except Exception as e:
            print(f"  FAILED: {e}")

    print_summary(results, conn_latencies)


if __name__ == "__main__":
    main()
