"""
Parakeet TDT v3 STT Latency Benchmark

Tests nvidia/parakeet-tdt-0.6b-v3 via mlx-community/parakeet-tdt-0.6b-v3
(Apple MLX, Metal acceleration) using parakeet-mlx.

Four phases:
  Phase 1 — Model load + warm-up
  Phase 2 — Batch inference at short/medium/long audio lengths
  Phase 3 — Streaming inference (100ms chunks, draft tokens per chunk)
  Phase 4 — Results summary with comparison note vs Deepgram

Latency model:
  Batch:     effective post-VAD latency = full inference time (no overlap with speech)
  Streaming: effective post-VAD latency ≈ finalization after last chunk

Usage:
    python tests/test_parakeet_latency.py
    python tests/test_parakeet_latency.py --file path/to/audio.wav
    python tests/test_parakeet_latency.py --runs 3 --skip-batch
"""

import argparse
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import mlx.core as mx
import numpy as np
import soundfile as sf

MODEL_NAME = "mlx-community/parakeet-tdt-0.6b-v3"
SAMPLE_RATE = 16000
CHUNK_MS = 1500
CHUNK_SAMPLES = int(SAMPLE_RATE * 1.5)  # 1.5s chunks, matching parakeet-mlx streaming demo

TEST_PHRASE = (
    "The quick brown fox jumps over the lazy dog. "
    "She sells seashells by the seashore. "
    "How much wood would a woodchuck chuck if a woodchuck could chuck wood. "
    "Peter Piper picked a peck of pickled peppers. "
    "To be or not to be, that is the question. "
    "All that glitters is not gold."
)

SHORT_PHRASE = "The quick brown fox jumps over the lazy dog."
MEDIUM_PHRASE = (
    "The quick brown fox jumps over the lazy dog. "
    "She sells seashells by the seashore. "
    "How much wood would a woodchuck could chuck wood."
)


# ---------------------------------------------------------------------------
# Audio preparation
# ---------------------------------------------------------------------------

def generate_wav(phrase: str, label: str) -> Path:
    if not shutil.which("say"):
        raise RuntimeError("`say` not found (macOS only)")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("`ffmpeg` not found")

    tmp_dir = Path(tempfile.mkdtemp())
    aiff_path = tmp_dir / f"{label}.aiff"
    wav_path = tmp_dir / f"{label}.wav"

    subprocess.run(
        ["say", "-v", "Alex", "-o", str(aiff_path), phrase],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff_path),
         "-ar", str(SAMPLE_RATE), "-ac", "1", "-sample_fmt", "s16", str(wav_path)],
        check=True, capture_output=True,
    )
    return wav_path


def load_float32(path: Path) -> np.ndarray:
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if sr != SAMPLE_RATE:
        raise ValueError(f"File is {sr}Hz; need {SAMPLE_RATE}Hz")
    if data.ndim > 1:
        data = data[:, 0]
    return data


def _write_temp_wav(audio: np.ndarray, label: str) -> Path:
    import wave
    tmp = Path(tempfile.mkdtemp()) / f"{label}.wav"
    pcm = (audio * 32767).astype(np.int16)
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return tmp


# ---------------------------------------------------------------------------
# Phase 1 — Model load + warm-up
# ---------------------------------------------------------------------------

def load_model():
    from parakeet_mlx import from_pretrained

    print(f"\nPhase 1 — Model load + warm-up")
    print(f"  Loading: {MODEL_NAME}")
    t0 = time.perf_counter()
    model = from_pretrained(MODEL_NAME)
    load_time = time.perf_counter() - t0
    print(f"  Load time: {load_time * 1000:.0f}ms")

    # Warm-up: 1 short inference to trigger JIT compilation
    print("  Warm-up inference (JIT compile)...")
    warmup_audio = np.zeros(SAMPLE_RATE, dtype=np.float32)  # 1s silence
    warmup_path = _write_temp_wav(warmup_audio, "warmup")
    t0 = time.perf_counter()
    model.transcribe(warmup_path)
    warmup_time = time.perf_counter() - t0
    print(f"  Warm-up time: {warmup_time * 1000:.0f}ms")

    return model, load_time


# ---------------------------------------------------------------------------
# Phase 2 — Batch inference
# ---------------------------------------------------------------------------

def run_batch_phase(model, audio_clips: list[tuple[str, np.ndarray]], runs: int) -> list[dict]:
    print(f"\nPhase 2 — Batch inference (N={runs} per clip)")

    results = []
    for label, audio in audio_clips:
        duration = len(audio) / SAMPLE_RATE
        wav_path = _write_temp_wav(audio, label)
        times = []
        transcript = ""
        for i in range(runs):
            t0 = time.perf_counter()
            result = model.transcribe(wav_path)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)
            if i == 0:
                transcript = result.text.strip()

        med = statistics.median(times)
        rtf = med / duration
        print(f"  [{label}] duration={duration:.1f}s  "
              f"median={med * 1000:.0f}ms  rtf={rtf:.3f}  "
              f"transcript={transcript!r:.50s}")
        results.append({
            "label": label,
            "duration_s": round(duration, 1),
            "inference_median_ms": round(med * 1000),
            "inference_min_ms": round(min(times) * 1000),
            "inference_max_ms": round(max(times) * 1000),
            "rtf": round(rtf, 3),
            "transcript": transcript,
        })

    return results


# ---------------------------------------------------------------------------
# Phase 3 — Streaming inference
# ---------------------------------------------------------------------------

def run_streaming_phase(model, audio: np.ndarray, runs: int, realtime: bool = True) -> dict:
    """
    realtime=True:  sleep between chunks to simulate mic input — processing overlaps
                    with speech, so only the last chunk's latency matters post-VAD.
    realtime=False: feed chunks as fast as possible (pessimistic / back-to-back mode).
    """
    chunk_duration = CHUNK_SAMPLES / SAMPLE_RATE
    duration = len(audio) / SAMPLE_RATE
    mode = "real-time simulated" if realtime else "back-to-back"
    print(f"\nPhase 3 — Streaming inference (1.5s chunks, no context_size, {mode}, N={runs})")
    print(f"  Audio duration: {duration:.1f}s  chunk_duration: {chunk_duration:.1f}s")

    all_last_chunk_times = []
    last_transcript = ""

    for run_idx in range(runs):
        chunk_log = []   # (chunk_idx, add_latency_ms, draft)
        t_last_chunk_start = None

        with model.transcribe_stream() as transcriber:
            offset = 0
            chunk_idx = 0
            while offset < len(audio):
                chunk = audio[offset: offset + CHUNK_SAMPLES]
                if len(chunk) == 0:
                    break

                t_chunk_start = time.perf_counter()
                transcriber.add_audio(mx.array(chunk))
                t_after_add = time.perf_counter()

                add_latency_ms = (t_after_add - t_chunk_start) * 1000
                draft = transcriber.result.text.strip()
                chunk_log.append((chunk_idx, add_latency_ms, draft))

                is_last = (offset + CHUNK_SAMPLES) >= len(audio)
                if is_last:
                    t_last_chunk_start = t_chunk_start

                offset += CHUNK_SAMPLES
                chunk_idx += 1

                # Simulate real-time: sleep for remaining chunk duration so the
                # next chunk arrives ~when it would from a live microphone.
                if realtime and not is_last:
                    elapsed = time.perf_counter() - t_chunk_start
                    gap = chunk_duration - elapsed
                    if gap > 0:
                        time.sleep(gap)

            final = transcriber.result.text.strip()

        # Post-VAD latency = time from when the last chunk started being processed
        # until result is ready. In real pipeline this is what happens after VAD fires.
        t_done = time.perf_counter()
        last_chunk_ms = (t_done - t_last_chunk_start) * 1000 if t_last_chunk_start else None
        all_last_chunk_times.append(last_chunk_ms)
        last_transcript = final

        if run_idx == 0:
            print(f"  Per-chunk log (first run):")
            for idx, lat, draft in chunk_log:
                overtime = lat - chunk_duration * 1000
                flag = f"  [+{overtime:.0f}ms over budget]" if overtime > 50 else ""
                print(f"    chunk {idx}: add_latency={lat:.0f}ms  draft={draft!r:.40s}{flag}")
            print(f"  Last-chunk post-VAD latency: {last_chunk_ms:.0f}ms")
            print(f"  Final transcript: {final!r:.60s}")

    valid = [t for t in all_last_chunk_times if t is not None]
    med = statistics.median(valid) if valid else None
    chunk_lats = [lat for _, lat, _ in chunk_log]
    chunk_median = statistics.median(chunk_lats) if chunk_lats else None

    if runs > 1:
        print(f"  Last-chunk latency across {runs} runs: "
              f"median={med:.0f}ms  min={min(valid):.0f}ms  max={max(valid):.0f}ms")

    return {
        "duration_s": round(duration, 1),
        "last_chunk_median_ms": round(med) if med else None,
        "last_chunk_min_ms": round(min(valid)) if valid else None,
        "last_chunk_max_ms": round(max(valid)) if valid else None,
        "chunk_add_median_ms": round(chunk_median) if chunk_median else None,
        "realtime": realtime,
        "transcript": last_transcript,
    }


# ---------------------------------------------------------------------------
# Phase 4 — Summary
# ---------------------------------------------------------------------------

def print_summary(load_time: float, batch_results: list[dict], stream_result: dict | None):
    print("\n" + "=" * 65)
    print("RESULTS SUMMARY")
    print("=" * 65)
    print(f"Model load time: {load_time * 1000:.0f}ms\n")

    if batch_results:
        print("Batch inference:")
        print(f"  {'Duration':>8}  {'Inference':>10}  {'RTF':>6}  Est. post-VAD latency")
        for r in batch_results:
            print(f"  {r['duration_s']:>7.1f}s  "
                  f"{r['inference_median_ms']:>9}ms  "
                  f"{r['rtf']:>6.3f}  "
                  f"{r['inference_median_ms']}ms")
        print()

    if stream_result:
        last = stream_result.get("last_chunk_median_ms")
        chunk = stream_result.get("chunk_add_median_ms")
        mode = "real-time simulated" if stream_result.get("realtime") else "back-to-back"
        # Post-VAD latency = last chunk processing time (processing of prior chunks
        # overlaps with speech in real-time mode, so only the last chunk matters)
        print(f"Streaming inference (1.5s chunks, {mode}):")
        print(f"  {'Duration':>8}  {'add_audio median/chunk':>22}  post-VAD (last chunk)")
        print(f"  {stream_result['duration_s']:>7.1f}s  "
              f"{'~' + str(chunk) + 'ms':>22}  ~{last}ms")
        print()

    print("Note: Deepgram nova-3 streaming post-VAD latency ~200-300ms")
    print("      (run test_deepgram_latency.py for exact baseline)")
    print("=" * 65)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Parakeet TDT v3 STT latency benchmark")
    parser.add_argument("--file", help="Path to WAV file (16kHz mono). Omit to auto-generate via `say`.")
    parser.add_argument("--runs", type=int, default=3, help="Timed runs per test (default: 3)")
    parser.add_argument("--skip-batch", action="store_true", help="Skip batch inference phase")
    parser.add_argument("--skip-streaming", action="store_true", help="Skip streaming inference phase")
    args = parser.parse_args()

    # Load model
    try:
        model, load_time = load_model()
    except ImportError:
        print("Error: parakeet-mlx not installed. Run: pip install parakeet-mlx")
        sys.exit(1)

    # Prepare audio clips
    if args.file:
        long_path = Path(args.file)
        if not long_path.exists():
            print(f"Error: {long_path} not found")
            sys.exit(1)
        long_audio = load_float32(long_path)
        short_audio = long_audio[:int(SAMPLE_RATE * 2.5)]   # first ~2.5s
        medium_audio = long_audio[:int(SAMPLE_RATE * 5.0)]  # first ~5.0s
        print(f"  Using provided file: {long_path} ({len(long_audio)/SAMPLE_RATE:.1f}s)")
    else:
        print("\nGenerating test audio via `say`...")
        short_path = generate_wav(SHORT_PHRASE, "short")
        medium_path = generate_wav(MEDIUM_PHRASE, "medium")
        long_path = generate_wav(TEST_PHRASE, "long")
        short_audio = load_float32(short_path)
        medium_audio = load_float32(medium_path)
        long_audio = load_float32(long_path)
        print(f"  short:  {len(short_audio)/SAMPLE_RATE:.1f}s")
        print(f"  medium: {len(medium_audio)/SAMPLE_RATE:.1f}s")
        print(f"  long:   {len(long_audio)/SAMPLE_RATE:.1f}s")

    clips = [
        ("short", short_audio),
        ("medium", medium_audio),
        ("long", long_audio),
    ]

    # Phase 2 — batch
    batch_results = []
    if not args.skip_batch:
        batch_results = run_batch_phase(model, clips, runs=args.runs)

    # Phase 3 — streaming (use long audio)
    stream_result = None
    if not args.skip_streaming:
        stream_result = run_streaming_phase(model, long_audio, runs=args.runs)

    # Phase 4 — summary
    print_summary(load_time, batch_results, stream_result)


if __name__ == "__main__":
    main()
