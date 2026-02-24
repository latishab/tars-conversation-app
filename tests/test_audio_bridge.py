"""
Audio bridge loopback test.

Connects to the Pi via WebRTC, receives mic audio, optionally applies noise gate,
then plays back on Mac speakers, Pi speaker, or saves to WAV.

Usage:
    python test_audio_bridge.py                          # record + play on Mac
    python test_audio_bridge.py --play pi                # play on Pi speaker
    python test_audio_bridge.py --play mac               # play on Mac (default)
    python test_audio_bridge.py --play none              # no playback
    python test_audio_bridge.py --save /tmp/out.wav      # save to WAV
    python test_audio_bridge.py --noise-gate 0           # disable noise gate
    python test_audio_bridge.py --duration 10 --save /tmp/test.wav --play mac
"""

import asyncio
import argparse
import subprocess
import tempfile
import wave
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import sounddevice as sd
from loguru import logger

from transport.aiortc_client import AiortcRPiClient
from transport.audio_bridge import RPiAudioInputTrack


def save_wav(path: str, audio: np.ndarray, sample_rate: int):
    """Save float32 audio array to WAV file."""
    audio_int16 = (audio * 32767).astype(np.int16)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    logger.info(f"Saved to {path}")


def play_on_pi(rpi_host: str, wav_path: str):
    """Play a WAV file on the Pi speaker via SSH."""
    logger.info(f"Sending WAV to Pi ({rpi_host}) for playback...")
    # Copy wav to Pi then play with aplay
    subprocess.run(["scp", wav_path, f"{rpi_host}:/tmp/test_playback.wav"], check=True)
    subprocess.run(["ssh", rpi_host, "aplay /tmp/test_playback.wav"], check=True)
    logger.info("Pi playback complete")


async def run_loopback(
    rpi_url: str,
    rpi_host: str,
    duration: int,
    noise_gate: float,
    play: str,
    save: str | None,
):
    logger.info(f"Connecting to Pi at {rpi_url}...")

    client = AiortcRPiClient(rpi_url=rpi_url, auto_reconnect=False)

    audio_track_event = asyncio.Event()
    audio_track_ref = {}

    @client.on_audio_track
    async def on_track(track):
        logger.info(f"Got audio track from Pi: {track.kind}")
        audio_track_ref["track"] = track
        audio_track_event.set()

    connected = await client.connect()
    if not connected:
        logger.error("Failed to connect to Pi")
        return

    logger.info("Waiting for audio track...")
    try:
        await asyncio.wait_for(audio_track_event.wait(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.error("Timed out waiting for audio track from Pi")
        await client.disconnect()
        return

    track = audio_track_ref["track"]
    rpi_input = RPiAudioInputTrack(
        aiortc_track=track,
        sample_rate=16000,
        noise_gate_rms=noise_gate,
    )
    logger.info(f"Noise gate: {'disabled' if noise_gate == 0 else f'RMS threshold={noise_gate}'}")

    sample_rate = 16000
    collected = []
    logger.info(f"Recording for {duration}s — speak into the Pi mic now...")

    async def collect():
        async for frame in rpi_input.start():
            audio = np.frombuffer(frame.audio, dtype=np.int16).astype(np.float32) / 32767.0
            collected.append(audio)
            total_samples = sum(len(a) for a in collected)
            if total_samples >= sample_rate * duration:
                rpi_input.stop()
                break

    try:
        await asyncio.wait_for(collect(), timeout=duration + 10)
    except asyncio.TimeoutError:
        logger.warning("Collection timed out")

    await client.disconnect()

    if not collected:
        logger.error("No audio collected")
        return

    audio_data = np.concatenate(collected)
    rms = np.sqrt(np.mean(audio_data ** 2))
    peak = np.max(np.abs(audio_data))
    logger.info(f"Collected {len(audio_data)} samples ({len(audio_data)/sample_rate:.1f}s)")
    logger.info(f"Audio level — RMS: {rms:.4f}, Peak: {peak:.4f}")

    if peak < 0.001:
        logger.warning("Audio is nearly silent — mic may not be working")

    # Save to WAV if requested
    wav_path = save
    if wav_path:
        save_wav(wav_path, audio_data, sample_rate)
    elif play == "pi":
        # Need a temp file to send to Pi
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name
        save_wav(wav_path, audio_data, sample_rate)

    # Playback
    if play == "mac":
        logger.info("Playing back on Mac speakers...")
        sd.play(audio_data, samplerate=sample_rate)
        sd.wait()
        logger.info("Playback complete")
    elif play == "pi":
        play_on_pi(rpi_host, wav_path)
    elif play == "none":
        logger.info("No playback requested")


def main():
    parser = argparse.ArgumentParser(description="Audio bridge loopback test")
    parser.add_argument("--url", default="http://tars:8000", help="Pi WebRTC server URL")
    parser.add_argument("--host", default="tars-pi", help="Pi SSH host (for --play pi)")
    parser.add_argument("--duration", type=int, default=8, help="Recording duration in seconds")
    parser.add_argument("--noise-gate", type=float, default=0.02, help="Noise gate RMS threshold (0 to disable)")
    parser.add_argument("--play", choices=["mac", "pi", "none"], default="mac",
                        help="Where to play back the recorded audio")
    parser.add_argument("--save", default=None, metavar="FILE.wav",
                        help="Save recorded audio to WAV file (e.g. tests/mic_test.wav)")
    args = parser.parse_args()

    asyncio.run(run_loopback(
        rpi_url=args.url,
        rpi_host=args.host,
        duration=args.duration,
        noise_gate=args.noise_gate,
        play=args.play,
        save=args.save,
    ))


if __name__ == "__main__":
    main()
