"""Observer for logging TARS assistant responses and forwarding to frontend."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import re
import time
from loguru import logger
from pipecat.frames.frames import LLMTextFrame, TTSTextFrame, TTSStoppedFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from src.shared_state import metrics_store


class AssistantResponseObserver(BaseObserver):
    """Logs TARS assistant responses and forwards them to the frontend."""

    SENTENCE_REGEX = re.compile(r"(.+?[\.!\?\n])")

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._buffer = ""
        self._max_buffer_chars = 320
        self._last_sentence = None  # Track last sentence to avoid duplicates
        self._last_sentence_time = 0  # Timestamp of last sentence
        self._last_text_chunk = ""  # Track last chunk to detect overlaps

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        # Debug: Log all frame types to see what's coming through
        frame_type = type(frame).__name__
        if "Audio" not in frame_type and "Video" not in frame_type and "Image" not in frame_type:
            logger.debug(f"🔍 [AssistantObserver] Received {frame_type}")

        # Only listen to LLMTextFrame to avoid duplicates (same text goes to TTSTextFrame after)
        if isinstance(frame, LLMTextFrame):
            text = getattr(frame, "text", "") or ""
            logger.debug(f"📝 [AssistantObserver] LLMTextFrame: '{text}' | Buffer before: '{self._buffer[:50]}'")
            self._ingest_text(text)
            logger.debug(f"📝 [AssistantObserver] Buffer after: '{self._buffer[:50]}'")

        # Clear buffer when TTS stops (end of assistant response)
        elif isinstance(frame, TTSStoppedFrame):
            if self._buffer.strip():
                logger.debug(f"🧹 Flushing remaining buffer on TTS stop: '{self._buffer}'")
                self._flush_buffer()
            else:
                self._buffer = ""  # Clear empty buffer

    def _ingest_text(self, text: str):
        if not text.strip():
            return

        # Check for overlapping text (LLM sometimes resends previous tokens)
        # If the new text starts with content already in our buffer, skip the overlapping part
        if self._buffer and text.startswith(self._buffer):
            # New text contains the entire buffer - extract only new part
            new_part = text[len(self._buffer):]
            if new_part:
                logger.debug(f"📝 Detected overlap, adding only new part: '{new_part}'")
                self._buffer += new_part
        elif self._buffer:
            # Check if buffer ends with start of new text (partial overlap)
            max_overlap = min(len(self._buffer), len(text))
            overlap_found = False
            for i in range(max_overlap, 0, -1):
                if self._buffer[-i:] == text[:i]:
                    # Found overlap - skip the overlapping part
                    new_part = text[i:]
                    if new_part:
                        logger.debug(f"📝 Detected partial overlap ({i} chars), adding only new part: '{new_part}'")
                        self._buffer += new_part
                    overlap_found = True
                    break
            if not overlap_found:
                # No overlap - add entire text
                self._buffer += text
        else:
            # Empty buffer - just add the text
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
        current_time = time.time()

        # Deduplicate: Skip if this is the same sentence we just logged within 2 seconds
        # This prevents duplicate sentences from LLM streaming issues
        time_diff = current_time - self._last_sentence_time
        if self._last_sentence == sentence and time_diff < 2.0:
            logger.debug(f"🔇 Skipping duplicate sentence: '{sentence[:50]}...' (last seen {time_diff*1000:.0f}ms ago)")
            return

        self._last_sentence = sentence
        self._last_sentence_time = current_time

        logger.info(f"🗣️ TARS: {sentence}")

        # Store in shared state for Gradio UI
        metrics_store.add_transcription("assistant", sentence)

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
