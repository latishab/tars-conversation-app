"""Non-intrusive metrics observer for latency tracking."""

import time
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.frames.frames import (
    MetricsFrame,
    TranscriptionFrame,
    UserImageRequestFrame,
    LLMTextFrame,
    TTSTextFrame,
    TTSStartedFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from loguru import logger


class MetricsObserver(BaseObserver):
    """
    Observer that monitors pipeline frames for metrics collection.
    Does not interrupt the pipeline flow - purely watches frames as they pass.
    """

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection

        # Shared state for metrics tracking
        self._current_turn = 0
        self._current_metrics = {}
        self._tts_text_time = None
        self._last_sent_metrics = {}
        self._last_logged_turn = -1
        self._vision_request_time = None
        self._stt_start_time = None  # Track STT timing
        self._memory_start_time = None  # Track Memory timing

    def start_turn(self, turn_number: int):
        """Called by TurnTrackingObserver when a new turn starts."""
        self._current_turn = turn_number
        self._current_metrics = {}
        self._tts_text_time = None
        self._last_sent_metrics = {}
        self._last_logged_turn = -1
        self._stt_start_time = time.time()  # Start STT timing
        self._memory_start_time = None
        self._vision_request_time = None
        logger.debug(f"🔄 Turn #{self._current_turn} started, resetting metrics")

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        # Track STT latency
        if isinstance(frame, TranscriptionFrame):
            current_time = time.time()

            # Track STT latency (from audio stop to transcription)
            if self._stt_start_time is not None and 'stt_ttfb_ms' not in self._current_metrics:
                stt_latency_ms = (current_time - self._stt_start_time) * 1000
                self._current_metrics['stt_ttfb_ms'] = stt_latency_ms
                self._stt_start_time = None
                self._send_to_frontend()

            # Start memory timing after transcription
            self._memory_start_time = current_time

        # Track vision request timing
        elif isinstance(frame, UserImageRequestFrame):
            self._vision_request_time = time.time()

        # Track combined memory + LLM preprocessing latency
        # Note: This measures from transcription to first LLM response
        # It includes memory search time and time before LLM starts generating
        elif isinstance(frame, LLMTextFrame):
            # Track memory latency (if we have a start time and haven't recorded it yet)
            if self._memory_start_time is not None and 'mem0_latency_ms' not in self._current_metrics:
                # Time from transcription to first LLM text (includes memory search + LLM prep)
                memory_latency_ms = (time.time() - self._memory_start_time) * 1000
                self._current_metrics['mem0_latency_ms'] = memory_latency_ms
                self._memory_start_time = None
                self._send_to_frontend()

            # Track vision latency (from request to LLM response with vision content)
            if self._vision_request_time is not None and 'vision_latency_ms' not in self._current_metrics:
                text = getattr(frame, 'text', '').lower()
                vision_keywords = ['see', 'visible', 'camera', 'image', 'showing', 'looks like', 'wearing', 'room', 'background']
                if any(keyword in text for keyword in vision_keywords):
                    vision_latency_ms = (time.time() - self._vision_request_time) * 1000
                    self._current_metrics['vision_latency_ms'] = vision_latency_ms
                    self._vision_request_time = None
                    self._send_to_frontend()

        # Fallback: Manually track TTS TTFB if MetricsFrame isn't available
        elif isinstance(frame, TTSTextFrame):
            self._tts_text_time = time.time()

        elif isinstance(frame, TTSStartedFrame):
            if self._tts_text_time is not None and 'tts_ttfb_ms' not in self._current_metrics:
                tts_ttfb_ms = (time.time() - self._tts_text_time) * 1000
                self._current_metrics['tts_ttfb_ms'] = tts_ttfb_ms

                # Recalculate total and send update
                total = sum([
                    self._current_metrics.get('stt_ttfb_ms', 0),
                    self._current_metrics.get('llm_ttfb_ms', 0),
                    self._current_metrics.get('tts_ttfb_ms', 0)
                ])
                if total > 0:
                    self._current_metrics['total_ms'] = total
                    self._send_to_frontend()

                self._tts_text_time = None

        # Capture MetricsFrame data
        elif isinstance(frame, MetricsFrame):
            try:
                for metric_data in frame.data:
                    if isinstance(metric_data, TTFBMetricsData):
                        processor = metric_data.processor
                        value_ms = metric_data.value * 1000  # Convert seconds to milliseconds

                        processor_lower = processor.lower()

                        # Check TTS first (contains "tts" in name)
                        if 'ttsservice' in processor_lower or 'elevenlabs' in processor_lower or 'qwen' in processor_lower:
                            self._current_metrics['tts_ttfb_ms'] = value_ms
                        # Check STT (contains "stt" but NOT "tts")
                        elif 'sttservice' in processor_lower or 'speechmatics' in processor_lower:
                            self._current_metrics['stt_ttfb_ms'] = value_ms
                        # Check LLM
                        elif 'llmservice' in processor_lower or 'openai' in processor_lower or 'deepinfra' in processor_lower:
                            self._current_metrics['llm_ttfb_ms'] = value_ms
                        # Check Mem0
                        elif 'mem0' in processor_lower or 'memory' in processor_lower:
                            self._current_metrics['mem0_latency_ms'] = value_ms

                # Calculate total latency and send if we have any metrics
                if self._current_metrics:
                    total = sum([
                        self._current_metrics.get('stt_ttfb_ms', 0),
                        self._current_metrics.get('llm_ttfb_ms', 0),
                        self._current_metrics.get('tts_ttfb_ms', 0)
                    ])
                    if total > 0:
                        self._current_metrics['total_ms'] = total

                    self._send_to_frontend()

            except Exception as e:
                logger.error(f"Error processing MetricsFrame: {e}", exc_info=True)

    def _send_to_frontend(self):
        """Send metrics to frontend via WebRTC data channel."""
        if not self.webrtc_connection:
            return

        # Check if metrics have changed since last send (deduplication)
        current_metrics_key = (
            self._current_turn,
            self._current_metrics.get('stt_ttfb_ms'),
            self._current_metrics.get('mem0_latency_ms'),
            self._current_metrics.get('llm_ttfb_ms'),
            self._current_metrics.get('tts_ttfb_ms'),
            self._current_metrics.get('vision_latency_ms'),
        )

        if current_metrics_key == self._last_sent_metrics:
            return

        try:
            if self.webrtc_connection.is_connected():
                message = {
                    "type": "metrics",
                    "turn_number": self._current_turn,
                    "timestamp": int(time.time() * 1000),
                    **self._current_metrics
                }
                logger.debug(f"📤 [MetricsObserver] Sending metrics: {message}")
                self.webrtc_connection.send_app_message(message)

                # Log summary once per turn
                if self._last_logged_turn != self._current_turn:
                    def fmt(val):
                        return f"{val:.0f}" if isinstance(val, (int, float)) else "N/A"

                    logger.info(
                        f"📊 Turn #{self._current_turn}: "
                        f"STT={fmt(self._current_metrics.get('stt_ttfb_ms'))}ms | "
                        f"Memory={fmt(self._current_metrics.get('mem0_latency_ms'))}ms | "
                        f"LLM={fmt(self._current_metrics.get('llm_ttfb_ms'))}ms | "
                        f"TTS={fmt(self._current_metrics.get('tts_ttfb_ms'))}ms | "
                        f"Vision={fmt(self._current_metrics.get('vision_latency_ms'))}ms"
                    )
                    self._last_logged_turn = self._current_turn

                self._last_sent_metrics = current_metrics_key

        except Exception as exc:
            logger.error(f"❌ [MetricsObserver] Failed to send metrics: {exc}")
