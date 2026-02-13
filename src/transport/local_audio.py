"""
Local audio transport for on-Pi mode.

Provides direct sounddevice access without WebRTC for lower latency.
Uses same interface as audio_bridge.py for easy swapping.
"""

import asyncio
import numpy as np
from typing import Optional, AsyncIterator
from loguru import logger

from pipecat.frames.frames import AudioRawFrame

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    logger.warning("sounddevice not available - local audio disabled")


class LocalAudioSource:
    """
    Captures audio from local microphone and yields Pipecat frames.

    Direct sounddevice access without WebRTC.
    """

    def __init__(
        self,
        device: Optional[int] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 480,
    ):
        """
        Initialize local audio source.

        Args:
            device: Sounddevice device index or name. None for default.
            sample_rate: Audio sample rate in Hz. Default 16000.
            channels: Number of channels. Default 1 (mono).
            chunk_size: Samples per chunk. Default 480 (30ms at 16kHz).
        """
        if not SOUNDDEVICE_AVAILABLE:
            raise RuntimeError("sounddevice not available")

        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size

        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._stream: Optional[sd.InputStream] = None
        self._running = False

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback from sounddevice when audio is captured."""
        if status:
            logger.warning(f"Audio capture status: {status}")

        # Copy audio data (sounddevice reuses buffer)
        audio_data = indata.copy()

        # Put in queue (non-blocking)
        try:
            self._queue.put_nowait(audio_data)
        except asyncio.QueueFull:
            pass  # Drop frame if queue is full

    async def start(self) -> AsyncIterator[AudioRawFrame]:
        """
        Start capturing audio and yield Pipecat frames.

        Yields:
            AudioRawFrame objects with PCM audio data
        """
        if self._running:
            logger.warning("Audio source already running")
            return

        self._running = True

        # Start sounddevice stream
        self._stream = sd.InputStream(
            device=self.device,
            channels=self.channels,
            samplerate=self.sample_rate,
            dtype=np.float32,
            blocksize=self.chunk_size,
            callback=self._audio_callback,
        )
        self._stream.start()

        logger.info(
            f"Started local audio capture: {self.sample_rate}Hz, "
            f"{self.channels}ch, device={self._stream.device}"
        )

        try:
            while self._running:
                try:
                    # Get audio data from queue
                    audio_data = await asyncio.wait_for(
                        self._queue.get(), timeout=1.0
                    )

                    # Convert float32 [-1, 1] to int16 PCM
                    audio_int16 = (audio_data * 32767).astype(np.int16)

                    # If stereo, convert to mono by averaging channels
                    if audio_int16.ndim > 1 and audio_int16.shape[1] > 1:
                        audio_int16 = np.mean(audio_int16, axis=1).astype(np.int16)

                    # Flatten to 1D array
                    audio_int16 = audio_int16.flatten()

                    # Convert to bytes
                    audio_bytes = audio_int16.tobytes()

                    # Create Pipecat frame
                    frame = AudioRawFrame(
                        audio=audio_bytes,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                    )

                    yield frame

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in audio capture: {e}")
                    await asyncio.sleep(0.1)

        finally:
            self.stop()
            logger.info("Stopped local audio capture")

    def stop(self):
        """Stop capturing audio."""
        self._running = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None


class LocalAudioSink:
    """
    Plays audio to local speaker.

    Direct sounddevice access without WebRTC.
    """

    def __init__(
        self,
        device: Optional[int] = None,
        sample_rate: int = 24000,
        channels: int = 1,
    ):
        """
        Initialize local audio sink.

        Args:
            device: Sounddevice device index or name. None for default.
            sample_rate: Audio sample rate in Hz. Default 24000.
            channels: Number of channels. Default 1 (mono).
        """
        if not SOUNDDEVICE_AVAILABLE:
            raise RuntimeError("sounddevice not available")

        self.device = device
        self.sample_rate = sample_rate
        self.channels = channels

        self._queue: asyncio.Queue = asyncio.Queue()
        self._stream: Optional[sd.OutputStream] = None
        self._running = False
        self._play_task: Optional[asyncio.Task] = None

    def _audio_callback(self, outdata, frames, time_info, status):
        """Callback from sounddevice when audio needs to be played."""
        if status:
            logger.warning(f"Audio playback status: {status}")

        # Try to get audio from queue
        try:
            audio_data = self._queue.get_nowait()
            outdata[:] = audio_data[:frames]

            # If we didn't fill the buffer, pad with silence
            if len(audio_data) < frames:
                outdata[len(audio_data):] = 0

        except asyncio.QueueEmpty:
            # No audio available, output silence
            outdata[:] = 0

    async def start(self):
        """Start audio playback."""
        if self._running:
            logger.warning("Audio sink already running")
            return

        self._running = True

        # Start sounddevice stream
        self._stream = sd.OutputStream(
            device=self.device,
            channels=self.channels,
            samplerate=self.sample_rate,
            dtype=np.float32,
            callback=self._audio_callback,
        )
        self._stream.start()

        logger.info(
            f"Started local audio playback: {self.sample_rate}Hz, "
            f"{self.channels}ch, device={self._stream.device}"
        )

    async def play(self, frame: AudioRawFrame):
        """
        Play an audio frame.

        Args:
            frame: Pipecat AudioRawFrame to play
        """
        if not self._running:
            logger.warning("Audio sink not started")
            return

        # Convert bytes to numpy array
        audio_int16 = np.frombuffer(frame.audio, dtype=np.int16)

        # Convert int16 to float32 [-1, 1]
        audio_float = audio_int16.astype(np.float32) / 32767.0

        # Reshape for channels if needed
        if self.channels > 1 and audio_float.ndim == 1:
            audio_float = audio_float.reshape(-1, self.channels)

        # Add to queue
        await self._queue.put(audio_float)

    async def stop(self):
        """Stop audio playback."""
        self._running = False

        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        logger.info("Stopped local audio playback")


class LocalAudioBridge:
    """
    Bridge for local audio I/O.

    Provides same interface as AudioBridge but uses direct sounddevice access.
    """

    def __init__(
        self,
        input_device: Optional[int] = None,
        output_device: Optional[int] = None,
        input_sample_rate: int = 16000,
        output_sample_rate: int = 24000,
    ):
        """
        Initialize local audio bridge.

        Args:
            input_device: Microphone device. None for default.
            output_device: Speaker device. None for default.
            input_sample_rate: Mic sample rate. Default 16000.
            output_sample_rate: Speaker sample rate. Default 24000.
        """
        self.source = LocalAudioSource(
            device=input_device,
            sample_rate=input_sample_rate,
        )
        self.sink = LocalAudioSink(
            device=output_device,
            sample_rate=output_sample_rate,
        )

    async def start_input(self) -> AsyncIterator[AudioRawFrame]:
        """
        Start capturing audio from microphone.

        Yields:
            AudioRawFrame objects
        """
        async for frame in self.source.start():
            yield frame

    async def start_output(self):
        """Start audio playback to speaker."""
        await self.sink.start()

    async def play(self, frame: AudioRawFrame):
        """Play an audio frame to speaker."""
        await self.sink.play(frame)

    def stop(self):
        """Stop audio I/O."""
        self.source.stop()
        asyncio.create_task(self.sink.stop())
