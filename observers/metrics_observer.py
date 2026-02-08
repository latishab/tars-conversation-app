"""Non-intrusive metrics observer for latency tracking."""

import time
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.frames.frames import MetricsFrame, UserAudioRawFrame, TranscriptionFrame, UserStartedSpeakingFrame
from pipecat.metrics.metrics import TTFBMetricsData
from loguru import logger


class MetricsObserver(BaseObserver):
    """
    Observer that monitors pipeline frames for metrics collection.
    Does not interrupt the pipeline flow - purely watches frames as they pass.

    STT Latency Measurement:
    - Measures from turn start → first transcription received
    - Works for services with internal turn detection (Speechmatics, Deepgram, etc.)
    - For Deepgram, this captures endpointing + transcription time

    Other services (Memory, LLM, TTS) emit MetricsFrame which we capture directly.
    """

    def __init__(self, webrtc_connection=None, stt_service=None, **kwargs):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self.stt_service = stt_service


        # Shared state for metrics tracking
        self._current_turn = 0
        self._current_metrics = {}
        self._tts_text_time = None
        self._last_sent_metrics = {}
        self._last_logged_turn = -1
        self._vision_request_time = None

        # Manual timing for STT services
        self._stt_start_time = None
        self._stt_measured_this_turn = False
        self._mem0_start_time = None
        self._mem0_measured_this_turn = False


    def start_turn(self, turn_number: int):
        """Called by TurnTrackingObserver when a new turn starts."""
        self._current_turn = turn_number
        self._current_metrics = {}
        self._last_sent_metrics = {}
        self._last_logged_turn = -1
        self._stt_measured_this_turn = False
        self._mem0_measured_this_turn = False

        # Use turn start time as STT baseline
        self._stt_start_time = time.time()
        logger.info(f"🔄 [MetricsObserver] Turn #{self._current_turn} started, STT timer initialized")

        self._mem0_start_time = None

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        # STT timing: Measure from turn start to first transcription
        if isinstance(frame, TranscriptionFrame) and not self._stt_measured_this_turn:
            if self._stt_start_time is not None:
                stt_latency_ms = (time.time() - self._stt_start_time) * 1000
                self._current_metrics['stt_ttfb_ms'] = stt_latency_ms
                self._stt_measured_this_turn = True
                logger.info(f"✅ [MetricsObserver] STT latency: {stt_latency_ms:.0f}ms (turn start → transcription)")
                self._send_to_frontend()

        # Capture MetricsFrame data from Pipecat's built-in metrics
        if isinstance(frame, MetricsFrame):
            try:
                for metric_data in frame.data:
                    if isinstance(metric_data, TTFBMetricsData):
                        processor = metric_data.processor
                        value_ms = metric_data.value * 1000  # Convert seconds to milliseconds
                        processor_lower = processor.lower()

                        # Log all processors to help debug
                        logger.debug(f"📊 [MetricsObserver] MetricsFrame: {processor} = {value_ms:.0f}ms")

                        # Check STT (Deepgram, Speechmatics, etc.)
                        if 'sttservice' in processor_lower or 'deepgram' in processor_lower or 'speechmatics' in processor_lower:
                            if 'stt_ttfb_ms' not in self._current_metrics:  # Only log once per turn
                                self._current_metrics['stt_ttfb_ms'] = value_ms
                                logger.info(f"✅ [MetricsObserver] STT latency: {value_ms:.0f}ms (from {processor})")
                        # Check TTS (contains "tts" in name)
                        elif 'ttsservice' in processor_lower or 'elevenlabs' in processor_lower or 'qwen' in processor_lower:
                            if 'tts_ttfb_ms' not in self._current_metrics:  # Only log once per turn
                                self._current_metrics['tts_ttfb_ms'] = value_ms
                                logger.info(f"✅ [MetricsObserver] TTS latency: {value_ms:.0f}ms")
                        # Check LLM
                        elif 'llmservice' in processor_lower or 'openai' in processor_lower or 'deepinfra' in processor_lower:
                            if 'llm_ttfb_ms' not in self._current_metrics:  # Only log once per turn
                                self._current_metrics['llm_ttfb_ms'] = value_ms
                                logger.info(f"✅ [MetricsObserver] LLM latency: {value_ms:.0f}ms")
                        # Check Memory (HybridMemory, ChromaDB)
                        elif 'memory' in processor_lower or 'chromadb' in processor_lower or 'hybrid' in processor_lower:
                            if 'memory_latency_ms' not in self._current_metrics:  # Only log once per turn
                                self._current_metrics['memory_latency_ms'] = value_ms
                                logger.info(f"✅ [MetricsObserver] Memory latency: {value_ms:.0f}ms")
                        else:
                            logger.debug(f"🔍 [MetricsObserver] Unknown processor: {processor} ({value_ms:.0f}ms)")

                # Calculate total latency and send if we have any metrics
                if self._current_metrics:
                    total = sum([
                        self._current_metrics.get('stt_ttfb_ms', 0),
                        self._current_metrics.get('memory_latency_ms', 0),
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
            self._current_metrics.get('memory_latency_ms'),
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
                        return f"{val:.0f}ms" if isinstance(val, (int, float)) else "N/A"

                    # Build metrics summary
                    metrics_parts = []
                    if 'stt_ttfb_ms' in self._current_metrics:
                        metrics_parts.append(f"STT={fmt(self._current_metrics.get('stt_ttfb_ms'))}")
                    if 'memory_latency_ms' in self._current_metrics:
                        metrics_parts.append(f"Memory={fmt(self._current_metrics.get('memory_latency_ms'))}")
                    if 'llm_ttfb_ms' in self._current_metrics:
                        metrics_parts.append(f"LLM={fmt(self._current_metrics.get('llm_ttfb_ms'))}")
                    if 'tts_ttfb_ms' in self._current_metrics:
                        metrics_parts.append(f"TTS={fmt(self._current_metrics.get('tts_ttfb_ms'))}")
                    if 'vision_latency_ms' in self._current_metrics:
                        metrics_parts.append(f"Vision={fmt(self._current_metrics.get('vision_latency_ms'))}")

                    if metrics_parts:
                        logger.info(f"📊 Turn #{self._current_turn}: " + " | ".join(metrics_parts))
                    self._last_logged_turn = self._current_turn

                self._last_sent_metrics = current_metrics_key

        except Exception as exc:
            logger.error(f"❌ [MetricsObserver] Failed to send metrics: {exc}")
