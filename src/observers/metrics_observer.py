"""Non-intrusive metrics observer for latency tracking."""

import time
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.frames.frames import MetricsFrame, TranscriptionFrame
from pipecat.metrics.metrics import TTFBMetricsData
from loguru import logger
from shared_state import metrics_store


class MetricsObserver(BaseObserver):
    """
    Watches pipeline frames to collect per-turn latency metrics.

    All TTFB values come from pipecat's built-in TTFBMetricsData in MetricsFrame.

    Frame ID deduplication (per MetricsLogObserver pattern) ensures each MetricsFrame
    is processed exactly once regardless of how many pipeline hops it passes through.

    STT TTFB arrives before TranscriptionFrame, so it's buffered in
    _pending_stt_ttfb and applied when TranscriptionFrame confirms the new turn.

    Pipecat intentionally emits value=0.0 init frames at startup via
    _initial_metrics_frame(); these are skipped via the value == 0.0 check.
    """

    def __init__(self, **kwargs):
        super().__init__()
        self._current_turn = 0
        self._current_metrics = {}
        self._pending_stt_ttfb = None
        self._seen_frame_ids: set = set()

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame

        # TranscriptionFrame marks a new user turn; apply any buffered STT TTFB
        if isinstance(frame, TranscriptionFrame) and frame.text.strip():
            self._current_turn += 1
            self._current_metrics = {}
            if self._pending_stt_ttfb is not None:
                self._current_metrics['stt_ttfb_ms'] = self._pending_stt_ttfb
                self._pending_stt_ttfb = None
                self._flush()

        # Capture pipecat's built-in TTFB metrics (STT, LLM, TTS)
        elif isinstance(frame, MetricsFrame):
            # Deduplicate: MetricsFrame propagates through every pipeline hop,
            # triggering on_push_frame N times. Process each frame only once.
            if frame.id in self._seen_frame_ids:
                return
            self._seen_frame_ids.add(frame.id)

            try:
                changed = False
                for metric_data in frame.data:
                    if not isinstance(metric_data, TTFBMetricsData):
                        continue
                    # Skip pipecat's intentional 0.0 init frames (_initial_metrics_frame)
                    if metric_data.value == 0.0:
                        continue
                    processor = metric_data.processor.lower()
                    value_ms = metric_data.value * 1000
                    logger.debug(f"[MetricsObserver] MetricsFrame: {metric_data.processor} = {value_ms:.0f}ms")

                    if any(s in processor for s in ('deepgram', 'speechmatics', 'sttservice')):
                        # STT TTFB arrives before TranscriptionFrame; buffer it
                        if self._pending_stt_ttfb is None and 'stt_ttfb_ms' not in self._current_metrics:
                            self._pending_stt_ttfb = value_ms
                            logger.debug(f"[MetricsObserver] Buffered STT TTFB: {value_ms:.0f}ms")
                    elif any(s in processor for s in ('openai', 'llmservice', 'deepinfra', 'cerebras')):
                        if 'llm_ttfb_ms' not in self._current_metrics:
                            self._current_metrics['llm_ttfb_ms'] = value_ms
                            changed = True
                    elif any(s in processor for s in ('elevenlabs', 'ttsservice', 'qwen')):
                        if 'tts_ttfb_ms' not in self._current_metrics:
                            self._current_metrics['tts_ttfb_ms'] = value_ms
                            changed = True

                if changed:
                    self._flush()

            except Exception as e:
                logger.error(f"[MetricsObserver] MetricsFrame error: {e}", exc_info=True)

    def _flush(self):
        """Upsert current metrics into the store."""
        if not self._current_metrics or self._current_turn == 0:
            return

        total = sum(
            self._current_metrics.get(k, 0) or 0
            for k in ('stt_ttfb_ms', 'memory_latency_ms', 'llm_ttfb_ms', 'tts_ttfb_ms')
        )

        metrics_store.add_metric({
            "turn_number": self._current_turn,
            "timestamp": int(time.time() * 1000),
            "stt_ttfb_ms": self._current_metrics.get('stt_ttfb_ms'),
            "memory_latency_ms": self._current_metrics.get('memory_latency_ms'),
            "llm_ttfb_ms": self._current_metrics.get('llm_ttfb_ms'),
            "tts_ttfb_ms": self._current_metrics.get('tts_ttfb_ms'),
            "vision_latency_ms": self._current_metrics.get('vision_latency_ms'),
            "total_ms": total if total > 0 else None,
        })
