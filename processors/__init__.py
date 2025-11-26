"""Frame processors for the Pipecat pipeline."""

from .transcription_logger import SimpleTranscriptionLogger
from .filters import SilenceFilter, InputAudioFilter

__all__ = ["SimpleTranscriptionLogger", "SilenceFilter", "InputAudioFilter"]

