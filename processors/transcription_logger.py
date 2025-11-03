"""Processor for logging transcriptions and sending them to the frontend."""

from loguru import logger
from config import MEM0_API_KEY
from memory import Mem0Wrapper  # required

# Initialize Mem0 once per process (required)
if not MEM0_API_KEY:
    raise RuntimeError("MEM0_API_KEY is required but not set.")

_mem0 = Mem0Wrapper(api_key=MEM0_API_KEY)
from pipecat.frames.frames import Frame, InterimTranscriptionFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class SimpleTranscriptionLogger(FrameProcessor):
    """Simple processor to log transcriptions and send to frontend"""

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            # Extract speaker ID if available (from speaker diarization)
            speaker_id = getattr(frame, 'user_id', None)
            if speaker_id:
                logger.info(f"🎤 Transcription [{speaker_id}]: {frame.text}")
            else:
                logger.info(f"🎤 Transcription: {frame.text}")

            # Persist to Mem0 (best-effort, non-blocking)
            try:
                if _mem0 and _mem0.enabled and frame.text:
                    user_identifier = speaker_id or "user_1"
                    _mem0.save_user_message(user_id=str(user_identifier), text=frame.text)
            except Exception as e:  # pragma: no cover
                logger.debug(f"Skipping Mem0 save due to error: {e}")
            
            # Send transcription to frontend via WebRTC data channel
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "transcription",
                            "text": frame.text,
                            "speaker_id": speaker_id  # Include speaker ID if available
                        })
                        logger.debug(f"Sent transcription to frontend: {frame.text} (speaker: {speaker_id})")
                    else:
                        logger.warning("WebRTC connection not ready, skipping transcription send")
                except Exception as e:
                    logger.error(f"Error sending transcription: {e}", exc_info=True)
        elif isinstance(frame, InterimTranscriptionFrame):
            # Extract speaker ID if available (from speaker diarization)
            speaker_id = getattr(frame, 'user_id', None)
            if speaker_id:
                logger.info(f"🎤 Partial [{speaker_id}]: {frame.text}")
            else:
                logger.info(f"🎤 Partial: {frame.text}")
            
            # Send partial transcription to frontend
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "partial",
                            "text": frame.text,
                            "speaker_id": speaker_id  # Include speaker ID if available
                        })
                        logger.debug(f"Sent partial transcription to frontend: {frame.text} (speaker: {speaker_id})")
                    else:
                        logger.warning("WebRTC connection not ready, skipping partial transcription send")
                except Exception as e:
                    logger.error(f"Error sending partial transcription: {e}", exc_info=True)

        # Push all frames through
        await self.push_frame(frame, direction)

