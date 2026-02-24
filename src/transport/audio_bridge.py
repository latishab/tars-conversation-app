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

    def __init__(
        self,
        aiortc_track: MediaStreamTrack,
        sample_rate: int = 16000,
        noise_gate_rms: float = 0.02,
    ):
        """
        Initialize audio input track.

        Args:
            aiortc_track: aiortc MediaStreamTrack from RPi
            sample_rate: Expected sample rate (16kHz from RPi mic)
            noise_gate_rms: RMS threshold below which audio is replaced with silence.
                            Set to 0.0 to disable. Default 0.02 suppresses fan/ambient noise.
        """
        self.aiortc_track = aiortc_track
        self.sample_rate = sample_rate
        self.noise_gate_rms = noise_gate_rms
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Noise gate hold: keep gate open for N frames after speech ends to avoid clipping
        self._gate_hold_frames = 8  # ~160ms at 20ms/frame
        self._gate_hold_counter = 0

    async def start(self) -> AsyncIterator[AudioRawFrame]:
        """
        Start receiving audio from RPi and yield Pipecat frames.

        Yields:
            AudioRawFrame objects with PCM audio data
        """
        self._running = True
        logger.info(f"🎤 Started receiving audio from RPi at {self.sample_rate}Hz")
        _frame_count = 0

        try:
            while self._running:
                try:
                    # Receive audio frame from aiortc track
                    try:
                        frame: AVAudioFrame = await asyncio.wait_for(
                            self.aiortc_track.recv(), timeout=5.0
                        )
                    except asyncio.TimeoutError:
                        logger.warning("[AudioBridge] recv() timed out — no audio from Pi (ICE/network issue?)")
                        continue
                    _frame_count += 1
                    if _frame_count <= 3 or _frame_count % 500 == 0:
                        logger.debug(f"[AudioBridge] frame #{_frame_count}: fmt={frame.format.name}, rate={frame.sample_rate}, samples={frame.samples}, layout={frame.layout.name}")

                    # Opus WebRTC decodes at 48kHz regardless of capture rate.
                    # Downsample to target_sample_rate (16kHz) via decimation.
                    # Pi captures at 16kHz, so 48kHz→16kHz is lossless here (ratio=3).
                    incoming_rate = frame.sample_rate or 48000

                    # Convert to numpy array.
                    # s16 interleaved stereo → to_ndarray() returns (1, samples*channels)
                    # s16p planar stereo     → to_ndarray() returns (channels, samples)
                    audio_array = frame.to_ndarray()
                    fmt = frame.format.name  # e.g. "s16", "s16p", "fltp"
                    channels = len(frame.layout.channels)
                    is_float = fmt.startswith("flt") or fmt.startswith("dbl")

                    if channels > 1:
                        if fmt.endswith("p"):
                            # Planar: (channels, samples) — mean across channel axis
                            mono = audio_array.mean(axis=0)
                        else:
                            # Interleaved: (1, samples*channels) — reshape then mean
                            mono = audio_array.reshape(-1, channels).mean(axis=1)
                    else:
                        mono = audio_array.flatten()

                    # Convert to int16 PCM based on original dtype
                    if is_float:
                        audio_int16 = (mono * 32767).astype(np.int16)
                    else:
                        audio_int16 = mono.astype(np.int16)

                    # Downsample if incoming rate differs from target (e.g. 48kHz → 16kHz)
                    if incoming_rate != self.sample_rate and self.sample_rate > 0:
                        ratio = incoming_rate // self.sample_rate
                        if ratio > 1:
                            audio_int16 = audio_int16[::ratio]

                    # Noise gate with hold: suppress frames below RMS threshold.
                    # Hold counter keeps gate open briefly after speech ends to avoid
                    # clipping the tail of words (prevents click/pop artifacts).
                    if self.noise_gate_rms > 0:
                        rms = np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2)) / 32767.0
                        if rms >= self.noise_gate_rms:
                            self._gate_hold_counter = self._gate_hold_frames
                        elif self._gate_hold_counter > 0:
                            self._gate_hold_counter -= 1
                        else:
                            audio_int16 = np.zeros_like(audio_int16)

                    audio_bytes = audio_int16.tobytes()

                    # Create Pipecat AudioRawFrame at the target sample rate
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
