"""Processor for logging transcriptions and sending them to the frontend."""

import asyncio
from loguru import logger
from config import MEM0_API_KEY
from memory import Mem0Wrapper 

from pipecat.frames.frames import Frame, InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

if not MEM0_API_KEY:
    raise RuntimeError("MEM0_API_KEY is required but not set.")

_mem0 = Mem0Wrapper(api_key=MEM0_API_KEY)


class TranscriptionLogger(FrameProcessor):
    """Pprocessor to log transcriptions, save to Mem0, and send to frontend."""

    def __init__(self, webrtc_connection=None, client_state=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self.client_state = client_state or {}

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames as they pass through the pipeline."""
        
        await super().process_frame(frame, direction)

        # --- (Logging & Memory Logic) ---
        if isinstance(frame, TranscriptionFrame):
            raw_id = getattr(frame, 'user_id', None)
            display_id = raw_id if (raw_id and raw_id != "S1") else self.client_state.get("client_id", "guest")

            logger.info(f"🎤 Transcription [{display_id}]: {frame.text}")

            # Fire-and-forget Memory Save
            try:
                if _mem0 and _mem0.enabled and frame.text:
                    asyncio.create_task(
                        asyncio.to_thread(
                            _mem0.save_user_message, 
                            user_id=str(display_id), 
                            text=frame.text
                        )
                    )
            except Exception as e:
                logger.debug(f"Skipping Mem0 save due to error: {e}")
            
            # Update Frontend
            if self.webrtc_connection:
                self._send_to_frontend("transcription", frame.text, display_id)

        elif isinstance(frame, InterimTranscriptionFrame):
            raw_id = getattr(frame, 'user_id', None)
            display_id = raw_id if (raw_id and raw_id != "S1") else self.client_state.get("client_id", "guest")
                
            logger.info(f"🎤 Partial [{display_id}]: {frame.text}")
            
            # Update Frontend
            if self.webrtc_connection:
                self._send_to_frontend("partial", frame.text, display_id)

        await self.push_frame(frame, direction)

    def _send_to_frontend(self, type_str, text, speaker_id):
        """Helper to send messages to frontend via WebRTC data channel."""
        try:
            if self.webrtc_connection and self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message({
                    "type": type_str,
                    "text": text,
                    "speaker_id": speaker_id
                })
        except Exception as e:
            logger.error(f"Error sending {type_str}: {e}")