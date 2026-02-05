"""Observer for broadcasting TTS state changes to frontend."""

from loguru import logger
from pipecat.frames.frames import TTSStartedFrame, TTSStoppedFrame, TTSAudioRawFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed


class TTSStateObserver(BaseObserver):
    """Emits `tts_state` messages whenever the assistant starts or stops speaking."""

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._speaking = False
        self._has_received_audio = False

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        # Priority 1: Explicit start/stop frames (most reliable)
        if isinstance(frame, TTSStartedFrame):
            self._set_state(True)
        elif isinstance(frame, TTSStoppedFrame):
            self._set_state(False)
            self._has_received_audio = False
        elif isinstance(frame, TTSAudioRawFrame):
            # Priority 2: Use first audio frame to detect start (fallback)
            # Only set to started if we haven't already and this is the first audio frame
            if not self._speaking and not self._has_received_audio:
                logger.debug("Detected TTS start via first TTSAudioRawFrame")
                self._set_state(True)
            self._has_received_audio = True
            # Note: We rely on TTSStoppedFrame to detect stop, not audio frame absence

    def _set_state(self, active: bool):
        if self._speaking == active:
            return

        self._speaking = active
        state = "started" if active else "stopped"

        if not self.webrtc_connection:
            return

        try:
            if self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message(
                    {
                        "type": "tts_state",
                        "state": state,
                    }
                )
                logger.debug(f"Sent TTS state message: {state}")
        except Exception as exc:
            logger.error(f"Failed to send TTS state: {exc}")
