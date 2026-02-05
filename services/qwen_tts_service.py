"""
Custom Pipecat TTS Service for Qwen3-TTS with voice cloning
Optimized for Apple Silicon (MPS) with low latency
"""

import asyncio
import io
import time
import torch
import numpy as np
from typing import AsyncGenerator

from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    ErrorFrame,
)
from pipecat.services.tts_service import TTSService
from loguru import logger

try:
    from qwen_tts import Qwen3TTSModel
except ImportError:
    logger.error("qwen-tts package not installed. Run: pip install qwen-tts")
    raise


class Qwen3TTSService(TTSService):
    """
    Pipecat TTS Service using Qwen3-TTS for local voice cloning on Apple Silicon
    """

    def __init__(
        self,
        *,
        model_name: str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        device: str = "mps",
        dtype=None,
        ref_audio_path: str = None,
        ref_text: str = None,
        x_vector_only_mode: bool = True,
        sample_rate: int = 24000,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._model_name = model_name
        self._device = device
        self._ref_audio_path = ref_audio_path
        self._ref_text = ref_text
        self._x_vector_only_mode = x_vector_only_mode
        self._sample_rate = sample_rate

        # Auto-detect dtype based on device
        if dtype is None:
            if device == "mps":
                # Use float32 for MPS voice cloning (required for stability)
                dtype = torch.float32
            else:
                dtype = torch.float16

        self._dtype = dtype

        # Model will be loaded lazily
        self._model = None
        self._voice_clone_prompt = None
        self._model_lock = asyncio.Lock()

        logger.info(f"Qwen3TTS Service initialized")
        logger.info(f"  Model: {model_name}")
        logger.info(f"  Device: {device}")
        logger.info(f"  Dtype: {dtype}")
        logger.info(f"  Reference audio: {ref_audio_path}")

    async def _load_model(self):
        """Load model lazily on first use"""
        if self._model is not None:
            return

        async with self._model_lock:
            # Double-check after acquiring lock
            if self._model is not None:
                return

            logger.info("Loading Qwen3-TTS model...")
            start_time = time.time()

            # Load model in executor to avoid blocking
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(
                None,
                lambda: Qwen3TTSModel.from_pretrained(
                    self._model_name,
                    device_map=self._device,
                    dtype=self._dtype,
                ),
            )

            load_time = time.time() - start_time
            logger.info(f"✓ Model loaded in {load_time:.2f}s")

            # Pre-create voice clone prompt if reference audio provided
            if self._ref_audio_path:
                logger.info("Creating voice clone prompt...")
                start_time = time.time()

                prompt = await loop.run_in_executor(
                    None,
                    lambda: self._model.create_voice_clone_prompt(
                        ref_audio=self._ref_audio_path,
                        ref_text=self._ref_text or "",
                        x_vector_only_mode=self._x_vector_only_mode,
                    ),
                )

                self._voice_clone_prompt = prompt
                prompt_time = time.time() - start_time
                logger.info(f"✓ Voice clone prompt created in {prompt_time:.2f}s")

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        """Generate TTS audio frames from text"""
        logger.debug(f"Generating TTS for text: {text[:50]}...")

        try:
            # Ensure model is loaded (includes voice clone prompt if ref audio provided)
            await self._load_model()

            # CRITICAL: If voice clone prompt is still not ready, skip this TTS request
            # This prevents crashes when TTS is called before voice cloning is initialized
            if self._voice_clone_prompt is None:
                logger.warning(f"Voice clone prompt not ready yet, skipping TTS for: {text[:30]}...")
                yield TTSStartedFrame()
                yield TTSStoppedFrame()
                return

            # Start TTFB metrics tracking BEFORE any work begins
            await self.start_ttfb_metrics()

            yield TTSStartedFrame()

            start_time = time.time()

            # Run TTS in executor to avoid blocking
            loop = asyncio.get_event_loop()

            # Use voice clone prompt (guaranteed to be ready at this point)
            wavs, sr = await loop.run_in_executor(
                None,
                lambda: self._model.generate_voice_clone(
                    text=text,
                    language="English",
                    voice_clone_prompt=self._voice_clone_prompt,
                ),
            )

            generation_time = time.time() - start_time

            # Stop TTFB metrics tracking (first audio ready)
            await self.stop_ttfb_metrics()

            # Convert to the expected format
            audio_data = wavs[0]

            # Convert to int16 for Pipecat
            if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
                # Normalize to [-1, 1] range
                audio_data = np.clip(audio_data, -1.0, 1.0)
                # Convert to int16
                audio_data = (audio_data * 32767).astype(np.int16)
            elif audio_data.dtype != np.int16:
                audio_data = audio_data.astype(np.int16)

            # Convert to bytes
            audio_bytes = audio_data.tobytes()

            duration = len(audio_data) / sr
            logger.debug(
                f"Generated {duration:.2f}s of audio in {generation_time:.2f}s "
                f"(RTF: {generation_time/duration:.2f}x)"
            )

            # Yield audio frame
            yield TTSAudioRawFrame(
                audio=audio_bytes,
                sample_rate=sr,
                num_channels=1,
            )

            yield TTSStoppedFrame()

            # Clear MPS cache to free memory
            if self._device == "mps":
                torch.mps.empty_cache()

        except Exception as e:
            logger.error(f"TTS generation error: {e}", exc_info=True)
            await self.stop_ttfb_metrics()  # Ensure metrics are stopped on error
            yield ErrorFrame(f"TTS Error: {str(e)}")
            yield TTSStoppedFrame()

    async def close(self):
        """Cleanup resources"""
        logger.info("Closing Qwen3TTS service...")
        self._model = None
        self._voice_clone_prompt = None
        if self._device == "mps":
            torch.mps.empty_cache()
