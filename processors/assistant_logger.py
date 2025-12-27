"""Processor for logging assistant responses and sending them to the frontend."""

from __future__ import annotations

import re

from loguru import logger

from pipecat.frames.frames import Frame, LLMTextFrame, TTSTextFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

SENTENCE_REGEX = re.compile(r"(.+?[\.!\?\n])")

class AssistantResponseLogger(FrameProcessor):
    """Logs TARS assistant responses and forwards them to the frontend."""

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._buffer = ""
        self._max_buffer_chars = 320

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (LLMTextFrame, TTSTextFrame)):
            text = getattr(frame, "text", "") or ""
            self._ingest_text(text)

        await self.push_frame(frame, direction)

    def _ingest_text(self, text: str):
        if not text.strip():
            return
        self._buffer += text
        self._emit_complete_sentences()

        if len(self._buffer) > self._max_buffer_chars:
            self._flush_buffer()

    def _emit_complete_sentences(self):
        while True:
            match = SENTENCE_REGEX.match(self._buffer)
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
            return

        try:
            if self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message(
                    {
                        "type": "assistant",
                        "text": text,
                    }
                )
        except Exception as exc:  # pragma: no cover
            logger.error(f"Failed to send assistant text to frontend: {exc}")

