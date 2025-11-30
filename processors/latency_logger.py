"""Processor for tracking latency from STT to TTS."""

import time
from loguru import logger

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    TTSStartedFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class LatencyLogger(FrameProcessor):
    """Tracks latency from STT transcription to TTS start."""
    
    # Class-level shared state (all instances share this)
    _shared_state = {
        "_last_transcription_time": None,
        "_last_transcription_text": None,
        "_llm_response_time": None,
        "_conversation_turn": 0
    }

    def __init__(self):
        super().__init__()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        current_time = time.time()
        
        # Use shared state (all instances share the same tracking data)
        state = LatencyLogger._shared_state
        
        # Track when transcription is received (STT complete) - can be UPSTREAM or DOWNSTREAM
        if isinstance(frame, TranscriptionFrame):
            state["_last_transcription_time"] = current_time
            state["_last_transcription_text"] = getattr(frame, 'text', None) or ""
            state["_llm_response_time"] = None  # Reset LLM response time for new turn
            state["_conversation_turn"] += 1
            text_preview = state["_last_transcription_text"][:50] + "..." if len(state["_last_transcription_text"]) > 50 else state["_last_transcription_text"]

        # Track when LLM generates response - DOWNSTREAM
        elif isinstance(frame, LLMTextFrame):
            # Only track the first LLM response time (multiple LLMTextFrames per response)
            if state["_last_transcription_time"] is not None and state["_llm_response_time"] is None:
                state["_llm_response_time"] = current_time

        # Track when TTS starts (calculate total latency) - DOWNSTREAM
        elif isinstance(frame, TTSStartedFrame):
            if state["_last_transcription_time"] is not None:
                total_latency = current_time - state["_last_transcription_time"]
                
                # Safely get transcription text for logging
                transcription_text = state["_last_transcription_text"] or "(no text)"
                text_preview = transcription_text[:60] + "..." if len(transcription_text) > 60 else transcription_text
                
                # Calculate breakdown if we have LLM response time
                if state["_llm_response_time"] is not None:
                    stt_to_llm = state["_llm_response_time"] - state["_last_transcription_time"]
                    llm_to_tts = current_time - state["_llm_response_time"]
                    
                    logger.info(
                        f"⏱️  Latency (turn #{state['_conversation_turn']}): "
                        f"Total={total_latency:.3f}s "
                        f"(STT→LLM={stt_to_llm:.3f}s, LLM→TTS={llm_to_tts:.3f}s) | "
                        f"User: \"{text_preview}\""
                    )
                else:
                    logger.info(
                        f"⏱️  Latency (turn #{state['_conversation_turn']}): "
                        f"Total={total_latency:.3f}s (STT→TTS) | "
                        f"User: \"{text_preview}\""
                    )
                
                # Reset for next turn
                state["_last_transcription_time"] = None
                state["_last_transcription_text"] = None
                state["_llm_response_time"] = None

        await self.push_frame(frame, direction)

