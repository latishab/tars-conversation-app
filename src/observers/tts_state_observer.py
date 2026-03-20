"""Observer for broadcasting TTS state changes to frontend."""

import asyncio

from loguru import logger
from pipecat.frames.frames import TTSStartedFrame, TTSStoppedFrame, TTSAudioRawFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed

_STOP_DEBOUNCE_S = 0.5  # coalesce multi-segment TTS into one started/stopped pair


class TTSStateObserver(BaseObserver):
    """Emits `tts_state` messages whenever the assistant starts or stops speaking."""

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._speaking = False
        self._has_received_audio = False
        self._stop_task: asyncio.Task | None = None

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        if isinstance(frame, TTSStartedFrame):
            # Cancel any pending debounced stop — new segment started
            if self._stop_task and not self._stop_task.done():
                self._stop_task.cancel()
                self._stop_task = None
            self._set_state(True)
        elif isinstance(frame, TTSStoppedFrame):
            self._has_received_audio = False
            # Debounce: wait before emitting stopped in case another segment follows
            if self._stop_task and not self._stop_task.done():
                self._stop_task.cancel()
            self._stop_task = asyncio.create_task(self._emit_stopped_after_delay())
        elif isinstance(frame, TTSAudioRawFrame):
            if not self._speaking and not self._has_received_audio:
                logger.debug("Detected TTS start via first TTSAudioRawFrame")
                self._set_state(True)
            self._has_received_audio = True

    async def _emit_stopped_after_delay(self):
        try:
            await asyncio.sleep(_STOP_DEBOUNCE_S)
            self._set_state(False)
        except asyncio.CancelledError:
            pass  # new segment arrived — don't emit stopped

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
