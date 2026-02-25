"""Shared state for metrics and transcriptions between Pipecat pipeline and Gradio UI."""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import deque
import threading
import time
from loguru import logger


@dataclass
class MetricEntry:
    """Single turn metrics entry."""
    turn_number: int
    timestamp: int
    stt_ttfb_ms: Optional[float] = None
    memory_latency_ms: Optional[float] = None
    llm_ttfb_ms: Optional[float] = None
    tts_ttfb_ms: Optional[float] = None
    vision_latency_ms: Optional[float] = None
    total_ms: Optional[float] = None


@dataclass
class MetricsStore:
    """Thread-safe storage for pipeline metrics and transcriptions."""
    # Keyed by turn_number so repeated calls for the same turn update in place
    metrics: dict = field(default_factory=dict)
    service_info: Optional[Dict] = None
    transcriptions: deque = field(default_factory=lambda: deque(maxlen=50))
    lock: threading.Lock = field(default_factory=threading.Lock)

    # Pipeline status fields
    pipeline_status: str = "disconnected"
    daemon_address: str = "N/A"
    audio_mode: str = "robot"
    _status_lock: threading.Lock = field(default_factory=threading.Lock)

    def add_metric(self, metric: dict):
        """Upsert a metric entry by turn_number — updates existing entry if present."""
        import dataclasses
        with self.lock:
            turn = metric["turn_number"]
            if turn in self.metrics:
                existing = dataclasses.asdict(self.metrics[turn])
                # Only overwrite fields that are not None in the new metric
                merged = {k: metric[k] if metric.get(k) is not None else existing[k]
                          for k in existing}
                self.metrics[turn] = MetricEntry(**merged)
            else:
                self.metrics[turn] = MetricEntry(**metric)

    def get_metrics(self) -> List[MetricEntry]:
        """Get all stored metrics sorted by turn number."""
        with self.lock:
            return [self.metrics[k] for k in sorted(self.metrics)]

    def set_service_info(self, info: dict):
        """Store service configuration info."""
        with self.lock:
            self.service_info = info

    def get_service_info(self) -> Optional[Dict]:
        """Get service configuration info."""
        with self.lock:
            return self.service_info

    def add_transcription(self, role: str, text: str):
        """Add a transcription entry."""
        with self.lock:
            self.transcriptions.append({
                "role": role,
                "text": text,
                "time": time.time()
            })

    def get_transcriptions(self) -> List[dict]:
        """Get all transcriptions."""
        with self.lock:
            return list(self.transcriptions)

    def clear_metrics(self):
        """Clear all stored metrics."""
        with self.lock:
            self.metrics = {}

    def set_pipeline_status(self, status: str):
        """Set pipeline status (idle/listening/thinking/speaking/disconnected/error)."""
        with self._status_lock:
            valid_states = {"idle", "listening", "thinking", "speaking", "disconnected", "error"}
            if status in valid_states:
                self.pipeline_status = status
            else:
                logger.warning(f"Invalid pipeline status: {status}")

    def get_pipeline_status(self) -> str:
        """Get current pipeline status."""
        with self._status_lock:
            return self.pipeline_status

    def set_daemon_address(self, address: str):
        """Set daemon connection address."""
        with self.lock:
            self.daemon_address = address

    def set_audio_mode(self, mode: str):
        """Set audio mode (robot/local)."""
        with self.lock:
            self.audio_mode = mode

    def get_audio_mode(self) -> str:
        with self.lock:
            return self.audio_mode


# Global instance
metrics_store = MetricsStore()
