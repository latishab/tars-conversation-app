"""Frame processors for the Pipecat pipeline.

This module contains processors that transform, filter, or process data.
For logging/monitoring processors, see loggers.py module.
"""

from .filters import SilenceFilter, InputAudioFilter
from .gating import InterventionGating
from .visual_observer import VisualObserver
from .emotional_monitor import EmotionalStateMonitor

__all__ = [
    "SilenceFilter",
    "InputAudioFilter",
    "InterventionGating",
    "VisualObserver",
    "EmotionalStateMonitor",
]
