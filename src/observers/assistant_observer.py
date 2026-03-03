"""Observer for logging TARS assistant responses and forwarding to frontend."""

import re
import time
from loguru import logger
from pipecat.frames.frames import LLMTextFrame, LLMFullResponseStartFrame, TTSStoppedFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed
from shared_state import metrics_store

# Matches [express(emotion, intensity)] tags for stripping before Gradio display
_EXPRESS_TAG_RE = re.compile(r'\[express\([^)]*\)\]', re.IGNORECASE)

class AssistantResponseObserver(BaseObserver):
    """Logs TARS assistant responses and forwards them to the frontend."""

    SENTENCE_REGEX = re.compile(r"(.+?[\.!\?\n])")

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._buffer = ""
        self._max_buffer_chars = 320
        self._last_sentence = None
        self._last_sentence_time = 0
        # Holds the last sentence text+tag waiting to see if a trailing
        # express tag arrives before TTSStoppedFrame flushes it.
        self._pending_sentence: str | None = None

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame

        # Reset buffer at the start of each LLM response so stale content from
        # a previous silence probe doesn't bleed into the next real response.
        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer = ""
            self._pending_sentence = None
            return

        # Capture raw LLM output so express tags are visible in the log.
        # The observer fires at every pipeline hop; filter to LLM source only
        # to avoid processing the same text 4-5x as it passes through filters.
        if isinstance(frame, LLMTextFrame) and "LLM" in type(getattr(data, "source", None)).__name__:
            text = getattr(frame, "text", "") or ""
            self._ingest_text(text)

        # Flush when TTS finishes: attach any trailing express tag in the buffer
        # to the pending sentence before committing it to metrics/frontend.
        elif isinstance(frame, TTSStoppedFrame):
            self._flush_at_end()

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
                self._commit_pending()
                self._pending_sentence = sentence

    def _flush_buffer(self):
        """Force-emit the buffer when it exceeds the size cap."""
        pending = self._buffer.strip()
        self._buffer = ""
        if pending:
            self._commit_pending()
            self._pending_sentence = pending

    def _flush_at_end(self):
        """Called at TTSStoppedFrame — attach trailing buffer content to pending sentence."""
        trailing = self._buffer.strip()
        self._buffer = ""

        if trailing and self._pending_sentence is not None:
            # Trailing content (e.g. express tag) appended to the last sentence
            self._pending_sentence = f"{self._pending_sentence} {trailing}"
        elif trailing:
            # Standalone trailing content with no preceding sentence
            self._pending_sentence = trailing

        self._commit_pending()

    def _commit_pending(self):
        """Store and forward whatever is in _pending_sentence, then clear it."""
        if self._pending_sentence is None:
            return
        sentence = self._pending_sentence
        self._pending_sentence = None
        self._log_sentence(sentence)

    def _log_sentence(self, sentence: str):
        current_time = time.time()
        time_diff = current_time - self._last_sentence_time
        if self._last_sentence == sentence and time_diff < 2.0:
            return

        self._last_sentence = sentence
        self._last_sentence_time = current_time

        # Log with express tags intact so they're visible for debugging
        logger.info(f"🗣️ TARS: {sentence}")

        # If the sentence is only an express tag with no actual text, skip it
        clean = _EXPRESS_TAG_RE.sub("", sentence).strip()
        if not clean:
            return

        # Store with tags intact for conversation history display
        metrics_store.add_transcription("assistant", sentence)
        self._send_to_frontend(clean)

    def _send_to_frontend(self, text: str):
        if not self.webrtc_connection:
            return
        try:
            if self.webrtc_connection.is_connected():
                self.webrtc_connection.send_app_message({"type": "assistant", "text": text})
        except Exception as exc:
            logger.error(f"❌ [AssistantObserver] Failed to send assistant text: {exc}")
