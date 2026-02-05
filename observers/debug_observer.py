"""Observer for general purpose debug logging."""

from loguru import logger
from pipecat.observers.base_observer import BaseObserver, FramePushed


class DebugObserver(BaseObserver):
    """General purpose debug logger for non-media frames."""

    def __init__(self, label="Debug"):
        super().__init__()
        self.label = label

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        frame_type = type(frame).__name__
        if "Audio" not in frame_type and "Video" not in frame_type and "Image" not in frame_type:
            # Log the User ID so we can verify they match
            uid = getattr(frame, 'user_id', 'None')
            logger.info(f"🔍 [{self.label}] {frame_type} | User: '{uid}' | Content: {str(frame)[:100]}")
