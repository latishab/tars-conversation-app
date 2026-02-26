"""Parakeet TDT v3 STT service for pipecat (batch mode).

Uses mlx-community/parakeet-tdt-0.6b-v3 via parakeet-mlx (Apple MLX/Metal).
Inherits SegmentedSTTService: audio is buffered during speech, then transcribed
in one batch call after VAD stop — matching the latency profile from the benchmark
(~256ms for a 2.5s utterance, RTF ~0.05-0.10).

Requires Silero VAD upstream in the pipeline.
Install: pip install parakeet-mlx
"""

import asyncio
import tempfile
import wave
from pathlib import Path
from typing import AsyncGenerator

from loguru import logger
from pipecat.frames.frames import Frame, StartFrame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

try:
    from parakeet_mlx import from_pretrained
except ModuleNotFoundError as e:
    logger.error(f"Exception: {e}")
    logger.error("In order to use Parakeet, you need to `pip install parakeet-mlx`.")
    raise


class ParakeetSTTService(SegmentedSTTService):
    """Parakeet TDT v3 STT service using Apple MLX batch inference.

    Buffers audio while the user speaks (via SegmentedSTTService), then runs
    a single model.transcribe() call after VAD stop. Benchmark results on M4:
      ~256ms for 2.5s utterance, ~500ms for 7s, ~800ms for 15s (RTF ~0.05-0.10).

    Requires Silero VAD upstream in the pipeline.
    """

    def __init__(
        self,
        *,
        model_name: str = "mlx-community/parakeet-tdt-0.6b-v3",
        sample_rate: int = 16000,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._model_name = model_name
        self._model = None

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if self._model is None:
            logger.info(f"Loading Parakeet model: {self._model_name}")
            loop = asyncio.get_event_loop()
            self._model = await loop.run_in_executor(None, from_pretrained, self._model_name)
            logger.info("Parakeet model loaded")

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        if not audio or self._model is None:
            return

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._transcribe_wav, audio)

        if result:
            logger.debug(f"Parakeet: {result!r}")
            yield TranscriptionFrame(
                text=result,
                user_id=self._user_id,
                timestamp=time_now_iso8601(),
                language=Language.EN,
            )

    def _transcribe_wav(self, wav_bytes: bytes) -> str:
        """Write WAV bytes to a temp file and run batch transcription."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = Path(f.name)
        try:
            result = self._model.transcribe(tmp_path)
            return result.text.strip()
        finally:
            tmp_path.unlink(missing_ok=True)
