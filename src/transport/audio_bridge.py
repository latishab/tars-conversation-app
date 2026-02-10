"""
Audio bridge between aiortc and Pipecat.

Converts:
- aiortc AudioFrame → Pipecat AudioRawFrame (input from RPi mic)
- Pipecat TTS output → aiortc AudioFrame (output to RPi speaker)
"""

import asyncio
import numpy as np
from typing import Optional, AsyncIterator
from loguru import logger

from aiortc import MediaStreamTrack
from aiortc.mediastreams import AudioFrame as AiortcAudioFrame
from av import AudioFrame as AVAudioFrame

from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    StartFrame,
    EndFrame,
)
from pipecat.processors.frame_processor import FrameProcessor


class RPiAudioInputTrack:
    """
    Wraps aiortc audio track from RPi and converts to Pipecat frames.

    Receives audio from RPi microphone via WebRTC and yields AudioRawFrame objects
    that Pipecat can process.
    """

    def __init__(self, aiortc_track: MediaStreamTrack, sample_rate: int = 16000):
        """
        Initialize audio input track.

        Args:
            aiortc_track: aiortc MediaStreamTrack from RPi
            sample_rate: Expected sample rate (16kHz from RPi mic)
        """
        self.aiortc_track = aiortc_track
        self.sample_rate = sample_rate
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> AsyncIterator[AudioRawFrame]:
        """
        Start receiving audio from RPi and yield Pipecat frames.

        Yields:
            AudioRawFrame objects with PCM audio data
        """
        self._running = True
        logger.info(f"🎤 Started receiving audio from RPi at {self.sample_rate}Hz")

        try:
            while self._running:
                try:
                    # Receive audio frame from aiortc track
                    frame: AVAudioFrame = await self.aiortc_track.recv()

                    # Convert to numpy array
                    # aiortc uses planar audio format, we need interleaved
                    audio_array = frame.to_ndarray()

                    # If stereo, convert to mono by averaging channels
                    if len(audio_array.shape) > 1:
                        audio_array = np.mean(audio_array, axis=0)

                    # Convert to int16 PCM (Pipecat expects bytes)
                    audio_int16 = (audio_array * 32767).astype(np.int16)
                    audio_bytes = audio_int16.tobytes()

                    # Create Pipecat AudioRawFrame
                    pipecat_frame = AudioRawFrame(
                        audio=audio_bytes,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                    )

                    yield pipecat_frame

                except Exception as e:
                    if "MediaStreamError" in str(type(e)):
                        logger.warning("📻 Audio stream ended from RPi")
                        break
                    else:
                        logger.error(f"❌ Audio receive error: {e}")
                        await asyncio.sleep(0.1)

        finally:
            self._running = False
            logger.info("🎤 Stopped receiving audio from RPi")

    def stop(self):
        """Stop receiving audio."""
        self._running = False


class RPiAudioOutputTrack(MediaStreamTrack):
    """
    aiortc MediaStreamTrack that sends TTS audio to RPi.

    Receives audio from Pipecat pipeline and sends via WebRTC to RPi speaker.
    """

    kind = "audio"

    def __init__(self, sample_rate: int = 24000):
        """
        Initialize audio output track.

        Args:
            sample_rate: Output sample rate (24kHz for TTS)
        """
        super().__init__()
        self.sample_rate = sample_rate
        self._queue: asyncio.Queue = asyncio.Queue()
        self._timestamp = 0
        self._running = True

        logger.info(f"🔊 Created audio output track for RPi at {self.sample_rate}Hz")

    async def recv(self) -> AVAudioFrame:
        """
        Receive next audio frame for aiortc to send to RPi.

        Returns:
            AVAudioFrame with audio data
        """
        # Get audio bytes from queue
        audio_bytes = await self._queue.get()

        if audio_bytes is None:
            # Stop signal
            self.stop()
            raise Exception("Track stopped")

        # Convert bytes to numpy array
        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32767.0

        # Create AVAudioFrame
        samples = len(audio_float)
        frame = AVAudioFrame(format="s16", layout="mono", samples=samples)
        frame.sample_rate = self.sample_rate

        # Set audio data
        frame.planes[0].update(audio_int16.tobytes())

        # Update timestamp
        self._timestamp += samples

        return frame

    async def add_audio(self, audio_bytes: bytes):
        """
        Add audio data to be sent to RPi.

        Args:
            audio_bytes: PCM audio bytes (int16)
        """
        if self._running:
            await self._queue.put(audio_bytes)

    def stop(self):
        """Stop the track."""
        self._running = False
        # Send stop signal
        try:
            self._queue.put_nowait(None)
        except:
            pass


class AudioBridge(FrameProcessor):
    """
    Bridges audio between Pipecat pipeline and aiortc WebRTC connection.

    - Receives audio from RPi mic → feeds into Pipecat STT
    - Receives TTS audio from Pipecat → sends to RPi speaker
    """

    def __init__(
        self,
        rpi_input_track: Optional[RPiAudioInputTrack] = None,
        rpi_output_track: Optional[RPiAudioOutputTrack] = None,
    ):
        """
        Initialize audio bridge.

        Args:
            rpi_input_track: Input track from RPi mic
            rpi_output_track: Output track to RPi speaker
        """
        super().__init__()
        self.rpi_input_track = rpi_input_track
        self.rpi_output_track = rpi_output_track

    async def process_frame(self, frame: Frame, direction):
        """
        Process frames from Pipecat pipeline.

        Intercepts AudioRawFrame from TTS and sends to RPi.
        """
        await super().process_frame(frame, direction)

        # If this is TTS audio output, send to RPi
        if isinstance(frame, AudioRawFrame) and self.rpi_output_track:
            await self.rpi_output_track.add_audio(frame.audio)

        # Pass frame downstream
        await self.push_frame(frame, direction)

    def set_input_track(self, track: RPiAudioInputTrack):
        """Set RPi input track."""
        self.rpi_input_track = track

    def set_output_track(self, track: RPiAudioOutputTrack):
        """Set RPi output track."""
        self.rpi_output_track = track
