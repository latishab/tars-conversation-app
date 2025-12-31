"""Processor for logging transcriptions and sending them to the frontend."""

from loguru import logger
from config import MEM0_API_KEY
from memory import Mem0Wrapper 

if not MEM0_API_KEY:
    raise RuntimeError("MEM0_API_KEY is required but not set.")

_mem0 = Mem0Wrapper(api_key=MEM0_API_KEY)

from pipecat.frames.frames import Frame, InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class SimpleTranscriptionLogger(FrameProcessor):
    """Simple processor to log transcriptions, save to Mem0, and send to frontend."""

    def __init__(self, webrtc_connection=None, client_state=None):
        super().__init__()  # CRITICAL: Initialize internal queues
        self.webrtc_connection = webrtc_connection
        self.client_state = client_state or {}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # 1. MODIFY & PROCESS (Before sending downstream)
        if isinstance(frame, TranscriptionFrame):
            # FIX: Overwrite "S1" with session guest ID so LLM responds
            if getattr(frame, 'user_id', None) == "S1":
                 frame.user_id = self.client_state.get("client_id", "guest")
            
            # Ensure we use a valid string for ID
            speaker_id = getattr(frame, 'user_id', "guest")

            # Log
            logger.info(f"🎤 Transcription [{speaker_id}]: {frame.text}")

            # Save to Mem0
            try:
                if _mem0 and _mem0.enabled and frame.text:
                    _mem0.save_user_message(user_id=str(speaker_id), text=frame.text)
            except Exception as e:
                logger.debug(f"Skipping Mem0 save due to error: {e}")
            
            # Send to Frontend
            if self.webrtc_connection:
                await self._send_to_frontend("transcription", frame.text, speaker_id)

        elif isinstance(frame, InterimTranscriptionFrame):
            # Fix display for partials too
            if getattr(frame, 'user_id', None) == "S1":
                 frame.user_id = self.client_state.get("client_id", "guest")
            
            speaker_id = getattr(frame, 'user_id', "guest")
            logger.info(f"🎤 Partial [{speaker_id}]: {frame.text}")
            
            if self.webrtc_connection:
                await self._send_to_frontend("partial", frame.text, speaker_id)

        # 2. STANDARD PIPECAT FLOW (CRITICAL)
        # We call super() to handle StartFrame/EndFrame and push the (now modified) frame.
        # We DO NOT call self.push_frame() manually to avoid double-pushing.
        await super().process_frame(frame, direction)

    async def _send_to_frontend(self, type_str, text, speaker_id):
        try:
            if self.webrtc_connection and self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message({
                    "type": type_str,
                    "text": text,
                    "speaker_id": speaker_id
                })
        except Exception as e:
            logger.error(f"Error sending {type_str}: {e}")