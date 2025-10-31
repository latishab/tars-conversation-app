"""Frame processors for the Pipecat pipeline."""

from .transcription_logger import SimpleTranscriptionLogger
from .video_passthrough import VideoPassThrough

__all__ = ["SimpleTranscriptionLogger", "VideoPassThrough"]

