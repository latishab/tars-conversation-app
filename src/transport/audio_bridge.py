"""
Audio bridge between aiortc WebRTC and Pipecat pipeline.

Audio chain (Mac → Pi):
  ElevenLabs 24kHz PCM → AudioBridge resamples to 48kHz (resample_poly) →
  RPiAudioOutputTrack serves 960-sample frames (20ms @ 48kHz) → aiortc Opus →
  Pi decodes to s16 stereo 48kHz → reshape(-1,2).mean(axis=1) → SpeakerOutput

Key pitfalls:
- aiortc Opus always decodes to s16 interleaved stereo. to_ndarray() returns
  (1, samples*channels). Must reshape(-1, channels).mean(axis=1), not mean(axis=0).
- Each recv() must return exactly one Opus frame (960 samples @ 48kHz = 20ms).
  Large chunks produce multiple packets sharing one RTP timestamp; Pi jitter
  buffer drops them as duplicates.
- aiortc's internal resampler is linear — causes robotic artifacts. Resample
  TTS audio on the Mac side with resample_poly before handing to aiortc.
- Deepgram Flux expects linear16 at PipelineParams.audio_in_sample_rate (16kHz).

Noise suppression (opt-in, denoise=True):
- Captures ~0.5s noise profile then applies per-frame spectral subtraction.
- Noise gate (noise_gate_rms > 0) is a lighter alternative when denoise=False.
"""

import asyncio
import fractions
import numpy as np
from typing import Optional, AsyncIterator
from loguru import logger
from scipy import signal
from scipy.signal import resample_poly
from math import gcd

from aiortc import MediaStreamTrack
from av import AudioFrame as AVAudioFrame

from pipecat.frames.frames import AudioRawFrame, InputAudioRawFrame, OutputAudioRawFrame, Frame
from pipecat.processors.frame_processor import FrameProcessor


class RPiAudioInputTrack:
    """Wraps aiortc audio track from RPi mic and yields Pipecat AudioRawFrame objects."""

    # Spectral subtraction constants
    _N_FFT = 512        # 32ms window at 16kHz
    _HOP = 256          # 50% overlap (used only for noise profile estimation)
    _ALPHA = 1.5        # subtraction strength
    _BETA = 0.02        # spectral floor (prevents musical noise)
    _NOISE_FRAMES = 25  # frames to capture for noise profile (~0.5s at 20ms/frame)

    def __init__(
        self,
        aiortc_track: MediaStreamTrack,
        sample_rate: int = 16000,
        noise_gate_rms: float = 0.0,
        denoise: bool = False,
    ):
        """
        Args:
            aiortc_track: Audio track received from RPi via WebRTC.
            sample_rate: Target sample rate for Pipecat/STT (default 16kHz).
            noise_gate_rms: RMS threshold below which frames are silenced (default 0 = off).
                            Only applies when denoise=False. Use for noisy environments
                            without the overhead of spectral subtraction.
            denoise: Apply spectral subtraction noise suppression (default False).
                     Captures a noise profile from the first ~0.5s then subtracts it
                     per-frame. Enable for environments with loud fans or ambient noise.
        """
        self.aiortc_track = aiortc_track
        self.sample_rate = sample_rate
        self.noise_gate_rms = noise_gate_rms
        self.denoise = denoise
        self._running = False
        self.is_mic_muted = False

        self._gate_hold_frames = 8   # ~160ms at 20ms/frame
        self._gate_hold_counter = 0

        if denoise:
            self._noise_spec: Optional[np.ndarray] = None
            self._noise_buf: list[np.ndarray] = []
            self._noise_frames_captured = 0

    async def start(self) -> AsyncIterator[AudioRawFrame]:
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

                if incoming_rate != self.sample_rate and self.sample_rate > 0:
                    ratio = incoming_rate // self.sample_rate
                    if ratio > 1:
                        audio_int16 = audio_int16[::ratio]

                if self.denoise:
                    audio_float = audio_int16.astype(np.float32) / 32767.0
                    if self._noise_spec is None:
                        self._noise_buf.append(audio_float)
                        self._noise_frames_captured += 1
                        if self._noise_frames_captured >= self._NOISE_FRAMES:
                            self._capture_noise_profile()
                    else:
                        audio_int16 = self._apply_spectral_subtraction(audio_int16)

                elif self.noise_gate_rms > 0:
                    rms = np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2)) / 32767.0
                    if rms >= self.noise_gate_rms:
                        self._gate_hold_counter = self._gate_hold_frames
                    elif self._gate_hold_counter > 0:
                        self._gate_hold_counter -= 1
                    else:
                        audio_int16 = np.zeros_like(audio_int16)

                if self.is_mic_muted:
                    audio_int16 = np.zeros_like(audio_int16)

                yield InputAudioRawFrame(
                    audio=audio_int16.tobytes(),
                    sample_rate=self.sample_rate,
                    num_channels=1,
                )

        finally:
            self._running = False
            logger.info("Stopped receiving audio from RPi")

    def _capture_noise_profile(self):
        noise = np.concatenate(self._noise_buf).astype(np.float32)
        _, _, Zxx = signal.stft(
            noise,
            nperseg=self._N_FFT,
            noverlap=self._N_FFT - self._HOP,
            window="hann",
        )
        self._noise_spec = np.mean(np.abs(Zxx), axis=-1).astype(np.float32)
        rms = np.sqrt(np.mean(noise ** 2))
        logger.info(
            f"Noise profile captured: RMS={rms:.4f} ({20*np.log10(rms+1e-9):.1f} dBFS), "
            f"bins={len(self._noise_spec)}"
        )
        self._noise_buf.clear()

    def _apply_spectral_subtraction(self, audio_int16: np.ndarray) -> np.ndarray:
        n = len(audio_int16)
        x = audio_int16.astype(np.float32) / 32767.0

        padded = np.zeros(self._N_FFT, dtype=np.float32)
        padded[:n] = x

        spec = np.fft.rfft(padded)
        mag = np.abs(spec)
        phase = np.angle(spec)

        mag_clean = np.maximum(
            mag - self._ALPHA * self._noise_spec,
            self._BETA * self._noise_spec,
        )

        denoised = np.fft.irfft(mag_clean * np.exp(1j * phase)).real
        return np.clip(denoised[:n] * 32767, -32767, 32767).astype(np.int16)

    def set_mic_mute(self, muted: bool):
        self.is_mic_muted = muted

    def stop(self):
        self._running = False


class RPiAudioOutputTrack(MediaStreamTrack):
    """aiortc MediaStreamTrack that streams TTS audio to the RPi speaker.

    Buffers incoming audio and serves exactly FRAME_SAMPLES samples per recv()
    call so every Opus packet gets a unique, incrementing RTP timestamp.
    Sends silence between utterances to keep the WebRTC stream alive.
    """

    kind = "audio"

    def __init__(self, sample_rate: int = 48000):
        super().__init__()
        self.sample_rate = sample_rate
        self.FRAME_SAMPLES = int(sample_rate * 0.02)  # 20ms at sample_rate
        self._queue: asyncio.Queue = asyncio.Queue()
        self._buf = np.array([], dtype=np.int16)
        self._timestamp = 0
        self._running = True
        self._time_base = fractions.Fraction(1, sample_rate)

    async def recv(self) -> AVAudioFrame:
        while len(self._buf) < self.FRAME_SAMPLES and self._running:
            try:
                audio_bytes = await asyncio.wait_for(self._queue.get(), timeout=0.02)
            except asyncio.TimeoutError:
                silence = np.zeros(self.FRAME_SAMPLES - len(self._buf), dtype=np.int16)
                self._buf = np.concatenate([self._buf, silence])
                break

            if audio_bytes is None:
                self._running = False
                break

            chunk = np.frombuffer(audio_bytes, dtype=np.int16)
            self._buf = np.concatenate([self._buf, chunk])

        n = min(self.FRAME_SAMPLES, len(self._buf))
        samples = np.zeros(self.FRAME_SAMPLES, dtype=np.int16)
        samples[:n] = self._buf[:n]
        self._buf = self._buf[n:]

        frame = AVAudioFrame(format="s16", layout="mono", samples=self.FRAME_SAMPLES)
        frame.sample_rate = self.sample_rate
        frame.pts = self._timestamp
        frame.time_base = self._time_base
        frame.planes[0].update(samples.tobytes())
        self._timestamp += self.FRAME_SAMPLES

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
        super().__init__()
        self.rpi_input_track = rpi_input_track
        self.rpi_output_track = rpi_output_track
        self._diag_tts_active = False

    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, OutputAudioRawFrame) and self.rpi_output_track:
            if not self._diag_tts_active:
                self._diag_tts_active = True
                logger.debug(f"[AudioDiag] First TTS frame arrived at bridge")

            audio_bytes = frame.audio
            src_rate = frame.sample_rate
            dst_rate = self.rpi_output_track.sample_rate

            if src_rate and dst_rate and src_rate != dst_rate:
                pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
                g = gcd(src_rate, dst_rate)
                up, down = dst_rate // g, src_rate // g
                pcm = resample_poly(pcm, up, down)
                audio_bytes = np.clip(pcm, -32768, 32767).astype(np.int16).tobytes()

            await self.rpi_output_track.add_audio(audio_bytes)

        elif self._diag_tts_active and not isinstance(frame, OutputAudioRawFrame):
            self._diag_tts_active = False

        await self.push_frame(frame, direction)

    def set_input_track(self, track: RPiAudioInputTrack):
        self.rpi_input_track = track

    def set_output_track(self, track: RPiAudioOutputTrack):
        self.rpi_output_track = track
