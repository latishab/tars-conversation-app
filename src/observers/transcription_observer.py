"""Observer for logging transcriptions and sending to frontend."""

import time
from loguru import logger
from pipecat.frames.frames import TranscriptionFrame, InterimTranscriptionFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed


class TranscriptionObserver(BaseObserver):
    """Logs transcriptions and sends to frontend."""

    def __init__(self, webrtc_connection=None, client_state=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self.client_state = client_state or {}
        self._last_transcription = None  # Track last transcription to avoid duplicates
        self._last_transcription_time = 0  # Timestamp of last transcription

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame
        current_time = time.time()

        # --- (Logging Logic) ---
        if isinstance(frame, TranscriptionFrame):
            # Deduplicate: Skip if same text within 200ms (different user_ids)
            time_diff = current_time - self._last_transcription_time
            if self._last_transcription == frame.text and time_diff < 0.2:
                logger.debug(f"🔇 Skipping duplicate transcription: '{frame.text}' (last seen {time_diff*1000:.0f}ms ago)")
                return

            self._last_transcription = frame.text
            self._last_transcription_time = current_time

            raw_id = getattr(frame, 'user_id', None)
            display_id = raw_id if (raw_id and raw_id != "S1") else self.client_state.get("client_id", "guest")

            logger.info(f"🎤 Transcription [{display_id}]: {frame.text}")

            # Update Frontend
            if self.webrtc_connection:
                self._send_to_frontend("transcription", frame.text, display_id)

        elif isinstance(frame, InterimTranscriptionFrame):
            raw_id = getattr(frame, 'user_id', None)
            display_id = raw_id if (raw_id and raw_id != "S1") else self.client_state.get("client_id", "guest")

            # Update Frontend (don't deduplicate partials as they change frequently)
            if self.webrtc_connection:
                self._send_to_frontend("partial", frame.text, display_id)

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
