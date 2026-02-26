"""Frame processors for the Pipecat pipeline.

This module contains processors that transform, filter, or process data.
For logging/monitoring processors, see loggers.py module.
"""

from .filters import SilenceFilter, InputAudioFilter, ReasoningLeakFilter
from .proactive_monitor import ProactiveMonitor

__all__ = [
    "SilenceFilter",
    "InputAudioFilter",
    "ReasoningLeakFilter",
    "ProactiveMonitor",
]
