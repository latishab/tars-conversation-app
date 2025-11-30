"""Audio capture and playback utilities for the TARS Robot Body."""

from __future__ import annotations

import asyncio
import fractions
import os
import threading
import time
from typing import Optional

import numpy as np
from loguru import logger

try:
    import sounddevice as sd
    from aiortc.mediastreams import MediaStreamTrack
    from av import AudioFrame
    from av.audio.resampler import AudioResampler
except ImportError as exc:  # pragma: no cover - surfaced during startup
    raise ImportError(
        "Audio dependencies missing. Install with `pip install aiortc sounddevice av`."
    ) from exc

# === Configuration ===
MIC_SAMPLE_RATE = int(os.getenv("MIC_SAMPLE_RATE", "48000"))
MIC_CHANNELS = int(os.getenv("MIC_CHANNELS", "1"))
MIC_BLOCKSIZE = int(os.getenv("MIC_BLOCKSIZE", "960"))
MIC_DEVICE_INDEX = os.getenv("MIC_DEVICE_INDEX", "0")

SPEAKER_SAMPLE_RATE = int(os.getenv("SPEAKER_SAMPLE_RATE", "48000"))
SPEAKER_BLOCKSIZE = int(os.getenv("SPEAKER_BLOCKSIZE", "960"))
SPEAKER_DEVICE_INDEX = os.getenv("SPEAKER_DEVICE_INDEX", None)

SPEAKER_ECHO_HOLDOFF_SEC = float(os.getenv("SPEAKER_ECHO_HOLDOFF_MS", "80")) / 1000.0
MIC_ECHO_SUPPRESS_GAIN = max(
    0.0, min(1.0, float(os.getenv("MIC_ECHO_SUPPRESS_GAIN", "0.3")))
)


class AudioActivityMonitor:
    """Tracks when the speaker is active to help suppress acoustic echo."""

    def __init__(self):
        self._lock = threading.Lock()
        self._speaker_active_until = 0.0
        self._force_active = False

    def mark_speaker_activity(self, duration_sec: float):
        with self._lock:
            hold = max(duration_sec, 0.0) + SPEAKER_ECHO_HOLDOFF_SEC
            deadline = time.monotonic() + hold
            if deadline > self._speaker_active_until:
                self._speaker_active_until = deadline

    def set_forced_state(self, active: bool):
        with self._lock:
            self._force_active = active
            if not active:
                self._speaker_active_until = time.monotonic()

    def speaker_active(self) -> bool:
        with self._lock:
            return self._force_active or time.monotonic() < self._speaker_active_until
    
    def is_forced_active(self) -> bool:
        """Check if speaker is forced active (TTS is speaking)."""
        with self._lock:
            return self._force_active


audio_activity_monitor = AudioActivityMonitor()


class MicrophoneStream(MediaStreamTrack):
    """Audio source backed by sounddevice InputStream."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self.rate = MIC_SAMPLE_RATE
        self.channels = MIC_CHANNELS
        device_index = int(MIC_DEVICE_INDEX) if MIC_DEVICE_INDEX else None
        self.stream = sd.InputStream(
            samplerate=self.rate,
            channels=self.channels,
            dtype="int16",
            blocksize=MIC_BLOCKSIZE,
            device=device_index,
        )
        self.stream.start()
        self.start_time = time.time()
        logger.info(
            f"MicrophoneStream initialized @ {self.rate}Hz (device={device_index})"
        )

    async def recv(self):
        loop = asyncio.get_running_loop()
        data, overflow = await loop.run_in_executor(
            None, lambda: self.stream.read(MIC_BLOCKSIZE)
        )
        if overflow:
            logger.warning("⚠️ Audio Overflow on microphone input")

        if audio_activity_monitor.speaker_active():
            # When TTS is active, suppress echo more aggressively
            # Use higher suppression when forced (TTS state), moderate when just speaker activity
            if audio_activity_monitor.is_forced_active():
                # TTS is actively speaking - suppress 95% to prevent echo
                effective_suppression = 0.95
            elif MIC_ECHO_SUPPRESS_GAIN > 0:
                # Just speaker activity (echo holdoff) - use configured suppression
                effective_suppression = min(MIC_ECHO_SUPPRESS_GAIN, 0.9)
            else:
                effective_suppression = 0.0
            
            if effective_suppression > 0:
                # Never completely mute - always allow some audio through for STT
                # Cap suppression at 0.95 (95% reduction) to ensure STT still receives audio
                effective_suppression = min(effective_suppression, 0.95)
                data = (data * (1.0 - effective_suppression)).astype("int16", copy=False)

        layout = "mono" if self.channels == 1 else "stereo"
        frame = AudioFrame.from_ndarray(
            data.T.reshape(self.channels, -1),
            format="s16",
            layout=layout,
        )
        frame.sample_rate = self.rate
        frame.pts = int((time.time() - self.start_time) * self.rate)
        frame.time_base = fractions.Fraction(1, self.rate)
        return frame

    def stop(self):
        if hasattr(self, "stream") and self.stream:
            self.stream.stop()
            self.stream.close()


class SpeakerStream:
    """Buffered audio playback with resampling and jitter smoothing."""

    def __init__(self, volume: float = 1.0):
        self.volume = max(0.0, min(1.0, volume))
        self.stream: Optional[sd.RawOutputStream] = None
        self.running = True
        self.target_sample_rate = SPEAKER_SAMPLE_RATE
        self._buffer = bytearray()
        self._buffer_lock = threading.Lock()
        self._callback_count = 0
        self.resampler = AudioResampler(
            format="s16", layout="mono", rate=self.target_sample_rate
        )

    def _callback(self, outdata, frames, time_info, status):
        if status:
            logger.warning(f"SpeakerStream status: {status}")

        # Track callback invocations for debugging
        self._callback_count += 1
        if self._callback_count <= 5 or self._callback_count % 100 == 0:
            with self._buffer_lock:
                buffer_size = len(self._buffer)
            logger.debug(f"🔊 Callback #{self._callback_count}: frames={frames}, buffer={buffer_size} bytes")

        # For RawOutputStream with dtype="int16", outdata is a memoryview of int16 values
        # We need frames * 2 bytes (int16 = 2 bytes per sample, mono = 1 channel)
        required_bytes = frames * 2
        required_samples = frames

        with self._buffer_lock:
            available = len(self._buffer)
            if available >= required_bytes:
                # Get audio data and apply volume
                audio_data = bytes(self._buffer[:required_bytes])
                # Convert to numpy array to apply volume
                audio_array = np.frombuffer(audio_data, dtype=np.int16).copy()
                if self.volume != 1.0:
                    audio_array = (audio_array * self.volume).astype(np.int16)
                # Write int16 values directly to outdata (memoryview)
                # outdata is a memoryview that can be assigned numpy array values
                outdata[:] = audio_array
                del self._buffer[:required_bytes]
            elif available > 0:
                # Get partial audio data and apply volume
                audio_data = bytes(self._buffer[:available])
                audio_array = np.frombuffer(audio_data, dtype=np.int16).copy()
                if self.volume != 1.0:
                    audio_array = (audio_array * self.volume).astype(np.int16)
                # Write partial data
                samples_written = len(audio_array)
                outdata[:samples_written] = audio_array
                # Fill rest with silence (zeros)
                outdata[samples_written:] = 0
                del self._buffer[:available]
            else:
                # No data available - fill with silence
                outdata[:] = 0

    async def play_track(self, track):
        logger.info("🔊 Speaker loop started (Buffered)")
        try:
            if self.stream is None:
                device_index = int(SPEAKER_DEVICE_INDEX) if SPEAKER_DEVICE_INDEX else None
                logger.info(f"🔊 Output Stream: {self.target_sample_rate}Hz (device={device_index})")
                try:
                    self.stream = sd.RawOutputStream(
                        samplerate=self.target_sample_rate,
                        channels=1,
                        dtype="int16",
                        device=device_index,
                        blocksize=SPEAKER_BLOCKSIZE,
                        callback=self._callback,
                    )
                    self.stream.start()
                    logger.info(f"✓ Speaker stream started @ {self.target_sample_rate}Hz, device={device_index}")
                    # Log available audio devices for debugging
                    try:
                        devices = sd.query_devices()
                        logger.debug(f"Available audio devices: {len(devices)}")
                        if device_index is not None and device_index < len(devices):
                            logger.debug(f"Using device: {devices[device_index]['name']}")
                    except:
                        pass
                except Exception as e:
                    logger.error(f"Failed to start speaker stream: {e}")
                    raise

            logger.info("Waiting for audio frames from track...")
            frame_count = 0
            while self.running:
                try:
                    frame = await track.recv()
                except Exception as e:
                    logger.warning(f"Track recv() error: {e} (track may have ended)")
                    break

                try:
                    resampled = self.resampler.resample(frame)
                    if not resampled:
                        continue
                    frame = resampled[0]
                except Exception as err:
                    logger.error(f"Resample error: {err}")
                    continue

                data = frame.to_ndarray()
                if frame.layout.name == "stereo":
                    data = data[0] if len(data.shape) > 1 else data.reshape(2, -1)[0]
                if len(data.shape) > 1:
                    data = data.reshape(-1)

                pcm_bytes = data.tobytes()
                with self._buffer_lock:
                    self._buffer.extend(pcm_bytes)
                    buffer_size = len(self._buffer)

                frame_duration = (
                    len(data) / self.target_sample_rate if self.target_sample_rate else 0.0
                )
                audio_activity_monitor.mark_speaker_activity(frame_duration)
                
                # Debug: log first few frames to confirm audio is flowing
                frame_count += 1
                if frame_count <= 3:
                    logger.info(f"🔊 Speaker: received frame {frame_count}, buffer={buffer_size} bytes")

        except Exception as exc:
            logger.error(f"Speaker error: {exc}")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        with self._buffer_lock:
            self._buffer.clear()


__all__ = [
    "MicrophoneStream",
    "SpeakerStream",
    "audio_activity_monitor",
    "AudioActivityMonitor",
]