from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    LLMFullResponseEndFrame, 
    LLMTextFrame, 
    LLMFullResponseStartFrame, 
    Frame, 
    InputAudioRawFrame, 
    StartFrame, 
    EndFrame,
    CancelFrame
)
from loguru import logger
import json


class InputAudioFilter(FrameProcessor):
    """
    Dedicated filter to block InputAudioRawFrame from reaching TTS service.
    These frames should only go upstream (to STT), never downstream (to TTS).
    """
    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)
        
        # 1. The Logic: Block Audio going Downstream
        if isinstance(frame, InputAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            return
        
        # 2. THE FIX: We MUST push every other frame (StartFrame, Text, etc.)
        await self.push_frame(frame, direction)

class SilenceFilter(FrameProcessor):
    """
    Intercepts LLM responses. If response is {"action": "silence"}, drops it.
    """
    def __init__(self):
        super().__init__()
        self.current_response_text = ""
        self.is_collecting = False
    
    async def process_frame(self, frame: Frame, direction):
        await super().process_frame(frame, direction)
        
        # THE FIX: Explicitly handle StartFrame/EndFrame/CancelFrame 
        # so they don't get trapped here.
        if isinstance(frame, (StartFrame, EndFrame, CancelFrame)):
            self.current_response_text = ""
            self.is_collecting = False
            await self.push_frame(frame, direction)
            return
        
        # --- Normal Logic Below ---
        
        # Start collecting text
        if isinstance(frame, LLMFullResponseStartFrame):
            self.current_response_text = ""
            self.is_collecting = True
            await self.push_frame(frame, direction)
            
        # Accumulate text
        elif isinstance(frame, LLMTextFrame) and self.is_collecting:
            self.current_response_text += frame.text
            await self.push_frame(frame, direction)
            
        # Check the full response
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self.is_collecting:
                text = self.current_response_text.strip()
                try:
                    # Check for silence JSON
                    if "action" in text and "silence" in text:
                        clean_json = text.replace("```json", "").replace("```", "").strip()
                        data = json.loads(clean_json)
                        if data.get("action") == "silence":
                            logger.info("SilenceFilter: Suppressing silent response.")
                            self.is_collecting = False
                            return # Drop the EndFrame (silence the turn)
                except:
                    pass
                self.is_collecting = False
            await self.push_frame(frame, direction)
            
        # Pass everything else (like Audio or System messages)
        else:
            await self.push_frame(frame, direction)

