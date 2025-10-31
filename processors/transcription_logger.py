"""Processor for logging transcriptions and sending them to the frontend."""

from loguru import logger
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
            logger.info(f"🎤 Transcription: {frame.text}")
            # Send transcription to frontend via WebRTC data channel
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "transcription",
                            "text": frame.text
                        })
                        logger.debug(f"Sent transcription to frontend: {frame.text}")
                    else:
                        logger.warning("WebRTC connection not ready, skipping transcription send")
                except Exception as e:
                    logger.error(f"Error sending transcription: {e}", exc_info=True)
        elif isinstance(frame, InterimTranscriptionFrame):
            logger.info(f"🎤 Partial: {frame.text}")
            # Send partial transcription to frontend
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "partial",
                            "text": frame.text
                        })
                        logger.debug(f"Sent partial transcription to frontend: {frame.text}")
                    else:
                        logger.warning("WebRTC connection not ready, skipping partial transcription send")
                except Exception as e:
                    logger.error(f"Error sending partial transcription: {e}", exc_info=True)

        # Push all frames through
        await self.push_frame(frame, direction)

