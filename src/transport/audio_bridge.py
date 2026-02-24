"""
Audio bridge between aiortc WebRTC and Pipecat pipeline.

Audio format notes:
- Opus/WebRTC always decodes to 48kHz regardless of capture rate. Pi captures at
  16kHz, so incoming frames are 48kHz and decimated 3:1 back to 16kHz here.
- aiortc delivers s16 interleaved stereo: to_ndarray() returns shape (1, samples*2).
  Must reshape to (samples, 2) before mixing to mono — NOT mean(axis=0).
- Deepgram Flux expects linear16 at the sample rate set in PipelineParams
  (default 16000). Mismatch → silent transcription with no error.

Noise gate:
- Frames below noise_gate_rms threshold are replaced with silence.
- A hold counter keeps the gate open for ~160ms after speech ends so word
  tails aren't clipped (avoids click/pop artifacts at speech boundaries).
"""

import asyncio
import numpy as np
from typing import Optional, AsyncIterator
from loguru import logger

from aiortc import MediaStreamTrack
from av import AudioFrame as AVAudioFrame

from pipecat.frames.frames import AudioRawFrame, Frame
from pipecat.processors.frame_processor import FrameProcessor


class RPiAudioInputTrack:
    """Wraps aiortc audio track from RPi mic and yields Pipecat AudioRawFrame objects."""

    def __init__(
        self,
        aiortc_track: MediaStreamTrack,
        sample_rate: int = 16000,
        noise_gate_rms: float = 0.02,
    ):
        """
        Args:
            aiortc_track: Audio track received from RPi via WebRTC.
            sample_rate: Target sample rate for Pipecat/STT (default 16kHz).
            noise_gate_rms: RMS threshold below which frames are silenced.
                            Suppresses fan/ambient noise. Set to 0.0 to disable.
        """
        self.aiortc_track = aiortc_track
        self.sample_rate = sample_rate
        self.noise_gate_rms = noise_gate_rms
        self._running = False
        self._gate_hold_frames = 8  # ~160ms at 20ms/frame
        self._gate_hold_counter = 0

    async def start(self) -> AsyncIterator[AudioRawFrame]:
        """
        Receive audio frames from the RPi mic track and yield Pipecat AudioRawFrames.
        Handles format conversion, downsampling, and noise gating.
        """
        self._running = True
        logger.info(f"Started receiving audio from RPi at {self.sample_rate}Hz")

        try:
            while self._running:
                try:
                    frame: AVAudioFrame = await self.aiortc_track.recv()
                except Exception as e:
                    if "MediaStreamError" in str(type(e)):
                        break
                    logger.error(f"Audio receive error: {e}")
                    await asyncio.sleep(0.1)
                    continue

                incoming_rate = frame.sample_rate or 48000
                audio_array = frame.to_ndarray()
                fmt = frame.format.name
                channels = len(frame.layout.channels)
                is_float = fmt.startswith("flt") or fmt.startswith("dbl")

                # Mix to mono — handle interleaved (s16) and planar (s16p) formats
                if channels > 1:
                    if fmt.endswith("p"):
                        mono = audio_array.mean(axis=0)
                    else:
                        mono = audio_array.reshape(-1, channels).mean(axis=1)
                else:
                    mono = audio_array.flatten()

                if is_float:
                    audio_int16 = (mono * 32767).astype(np.int16)
                else:
                    audio_int16 = mono.astype(np.int16)

                # Decimate to target sample rate (e.g. 48kHz → 16kHz, ratio=3)
                if incoming_rate != self.sample_rate and self.sample_rate > 0:
                    ratio = incoming_rate // self.sample_rate
                    if ratio > 1:
                        audio_int16 = audio_int16[::ratio]

                # Noise gate with hold
                if self.noise_gate_rms > 0:
                    rms = np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2)) / 32767.0
                    if rms >= self.noise_gate_rms:
                        self._gate_hold_counter = self._gate_hold_frames
                    elif self._gate_hold_counter > 0:
                        self._gate_hold_counter -= 1
                    else:
                        audio_int16 = np.zeros_like(audio_int16)

                yield AudioRawFrame(
                    audio=audio_int16.tobytes(),
                    sample_rate=self.sample_rate,
                    num_channels=1,
                )

        finally:
            self._running = False
            logger.info("Stopped receiving audio from RPi")

    def stop(self):
        self._running = False


class RPiAudioOutputTrack(MediaStreamTrack):
    """aiortc MediaStreamTrack that streams TTS audio to the RPi speaker."""

    kind = "audio"

    def __init__(self, sample_rate: int = 24000):
        """
        Args:
            sample_rate: Sample rate of TTS audio being sent to RPi (default 24kHz).
                         Must be created and added to the WebRTC peer connection
                         before connect() is called so it's included in the SDP offer.
        """
        super().__init__()
        self.sample_rate = sample_rate
        self._queue: asyncio.Queue = asyncio.Queue()
        self._timestamp = 0
        self._running = True

    async def recv(self) -> AVAudioFrame:
        """Called by aiortc to pull the next frame to encode and send to RPi."""
        audio_bytes = await self._queue.get()

        if audio_bytes is None:
            self.stop()
            raise Exception("Track stopped")

        audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        samples = len(audio_int16)

        frame = AVAudioFrame(format="s16", layout="mono", samples=samples)
        frame.sample_rate = self.sample_rate
        frame.planes[0].update(audio_int16.tobytes())
        self._timestamp += samples

        return frame

    async def add_audio(self, audio_bytes: bytes):
        """Enqueue PCM audio bytes (int16) to be sent to the RPi speaker."""
        if self._running:
            await self._queue.put(audio_bytes)

    def stop(self):
        self._running = False
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass


class AudioBridge(FrameProcessor):
    """
    Pipecat FrameProcessor that intercepts TTS AudioRawFrames and forwards
    them to the RPi speaker via WebRTC.
    """

    def __init__(
        self,
        rpi_input_track: Optional[RPiAudioInputTrack] = None,
        rpi_output_track: Optional[RPiAudioOutputTrack] = None,
    ):
        """
        Args:
            rpi_input_track: Track receiving audio from the RPi mic (used externally
                             to feed frames into the pipeline via feed_rpi_audio).
            rpi_output_track: Track sending TTS audio to the RPi speaker.
        """
        super().__init__()
        self.rpi_input_track = rpi_input_track
        self.rpi_output_track = rpi_output_track

    async def process_frame(self, frame: Frame, direction):
        """Intercept TTS AudioRawFrames and forward audio to the RPi speaker."""
        await super().process_frame(frame, direction)

        if isinstance(frame, AudioRawFrame) and self.rpi_output_track:
            await self.rpi_output_track.add_audio(frame.audio)

        await self.push_frame(frame, direction)

    def set_input_track(self, track: RPiAudioInputTrack):
        self.rpi_input_track = track

    def set_output_track(self, track: RPiAudioOutputTrack):
        self.rpi_output_track = track
