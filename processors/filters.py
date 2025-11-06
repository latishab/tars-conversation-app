from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import LLMResponseEndFrame, Frame
from loguru import logger
import json

class SilenceFilter(FrameProcessor):
    """
    This processor intercepts the full text from an LLMResponseEndFrame.
    If the text is the exact JSON string {"action": "silence"},
    it drops the frame, preventing it from going to TTS.
    Otherwise, it passes all frames through.
    """
    async def process_frame(self, frame: Frame, direction):
        if isinstance(frame, LLMResponseEndFrame):
            text = frame.text.strip()
            try:
                # Check if the entire response is the silence JSON
                data = json.loads(text)
                if data.get("action") == "silence":
                    logger.info("SilenceFilter: Suppressing silent response.")
                    # Drop the frame by not pushing it.
                    return
            except (json.JSONDecodeError, TypeError):
                # It's not the silence JSON, so it's a real message.
                pass
        
        # Pass all other frames (Start, Text, and non-silence End)
        await self.push_frame(frame)

