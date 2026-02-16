"""Shared state for metrics and transcriptions between Pipecat pipeline and Gradio UI."""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import deque
import threading
import time


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
    metrics: deque = field(default_factory=lambda: deque(maxlen=100))
    service_info: Optional[Dict] = None
    transcriptions: deque = field(default_factory=lambda: deque(maxlen=50))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add_metric(self, metric: dict):
        """Add a new metric entry."""
        with self.lock:
            self.metrics.append(MetricEntry(**metric))

    def get_metrics(self) -> List[MetricEntry]:
        """Get all stored metrics."""
        with self.lock:
            return list(self.metrics)

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
            self.metrics.clear()


# Global instance
metrics_store = MetricsStore()
