from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import LLMFullResponseEndFrame, LLMTextFrame, LLMFullResponseStartFrame, Frame
from loguru import logger
import json

class SilenceFilter(FrameProcessor):
    """
    This processor intercepts LLM responses and checks if the full text
    is the exact JSON string {"action": "silence"}. If so, it drops
    the response frames, preventing them from going to TTS.
    Otherwise, it passes all frames through.
    """
    def __init__(self):
        super().__init__()
        self.current_response_text = ""
        self.is_collecting = False
    
    async def process_frame(self, frame: Frame, direction):
        # Always call super().process_frame first to let base class handle StartFrame
        # This ensures the processor is properly initialized
        await super().process_frame(frame, direction)
        
        # Initialize state when pipeline starts
        from pipecat.frames.frames import StartFrame
        if isinstance(frame, StartFrame):
            self.current_response_text = ""
            self.is_collecting = False
            return  # StartFrame already pushed by super()
        
        # Start collecting text when we see a response start
        if isinstance(frame, LLMFullResponseStartFrame):
            self.current_response_text = ""
            self.is_collecting = True
            await self.push_frame(frame)
        # Accumulate text from LLMTextFrame
        elif isinstance(frame, LLMTextFrame) and self.is_collecting:
            self.current_response_text += frame.text
            await self.push_frame(frame)
        # Check the full response when we see the end frame
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self.is_collecting:
                text = self.current_response_text.strip()
                try:
                    # Check if the entire response is the silence JSON
                    data = json.loads(text)
                    if data.get("action") == "silence":
                        logger.info("SilenceFilter: Suppressing silent response.")
                        # Drop the end frame by not pushing it
                        self.is_collecting = False
                        self.current_response_text = ""
                        return
                except (json.JSONDecodeError, TypeError):
                    # It's not the silence JSON, so it's a real message.
                    pass
                self.is_collecting = False
                self.current_response_text = ""
            await self.push_frame(frame)
        else:
            # Pass all other frames through (StartFrame, SpeechControlParamsFrame, etc.)
            # Note: StartFrame is already handled above, but other control frames pass through
            await self.push_frame(frame)

