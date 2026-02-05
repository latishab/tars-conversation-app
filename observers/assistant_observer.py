"""Observer for logging TARS assistant responses and forwarding to frontend."""

import re
from loguru import logger
from pipecat.frames.frames import LLMTextFrame, TTSTextFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed


class AssistantResponseObserver(BaseObserver):
    """Logs TARS assistant responses and forwards them to the frontend."""

    SENTENCE_REGEX = re.compile(r"(.+?[\.!\?\n])")

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._buffer = ""
        self._max_buffer_chars = 320

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        # Debug: Log all frame types to see what's coming through
        frame_type = type(frame).__name__
        if "Audio" not in frame_type and "Video" not in frame_type and "Image" not in frame_type:
            logger.debug(f"🔍 [AssistantObserver] Received {frame_type}")

        if isinstance(frame, (LLMTextFrame, TTSTextFrame)):
            text = getattr(frame, "text", "") or ""
            logger.debug(f"📝 [AssistantObserver] Text frame detected: '{text[:50]}'")
            self._ingest_text(text)

    def _ingest_text(self, text: str):
        if not text.strip():
            return
        self._buffer += text
        self._emit_complete_sentences()

        if len(self._buffer) > self._max_buffer_chars:
            self._flush_buffer()

    def _emit_complete_sentences(self):
        while True:
            match = self.SENTENCE_REGEX.match(self._buffer)
            if not match:
                break
            sentence = match.group(0).replace("\n", " ").strip()
            self._buffer = self._buffer[match.end():].lstrip()
            if sentence:
                self._log_sentence(sentence)

    def _flush_buffer(self):
        pending = self._buffer.strip()
        if pending:
            self._log_sentence(pending)
        self._buffer = ""

    def _log_sentence(self, sentence: str):
        logger.info(f"🗣️ TARS: {sentence}")
        self._send_to_frontend(sentence)

    def _send_to_frontend(self, text: str):
        if not self.webrtc_connection:
            logger.warning("⚠️ [AssistantObserver] No WebRTC connection available")
            return

        try:
            if self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message(
                    {
                        "type": "assistant",
                        "text": text,
                    }
                )
            else:
                logger.warning("⚠️ [AssistantObserver] WebRTC connection not connected")
        except Exception as exc:
            logger.error(f"❌ [AssistantObserver] Failed to send assistant text to frontend: {exc}")
