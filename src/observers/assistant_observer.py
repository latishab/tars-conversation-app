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
    """Logs TARS assistant responses and forwards them to the frontend.

    Captures LLMTextFrame from the LLM service source (earliest, pre-filter
    version) and emits sentences eagerly as they stream in. SilenceFilter's
    _REASONING_LEAK_RE ensures reasoning leaks never reach TTS, so they are
    safe to log here (the mismatch between logged text and spoken text is
    minor and useful for debugging).

    TTSStoppedFrame flushes any trailing content that didn't end with
    sentence-ending punctuation.
    """

    SENTENCE_REGEX = re.compile(r"(.+?[\.!\?\n])")

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection
        self._buffer = ""
        self._max_buffer_chars = 320
        self._last_sentence = None
        self._last_sentence_time = 0
        self._pending_sentence: str | None = None

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame

        # Reset buffer at the start of each LLM response.
        # Only reset on the original LLM push — ReactiveGate re-pushes the same
        # StartFrame when passing through, which would otherwise wipe _pending_sentence
        # before TTSStoppedFrame has a chance to flush it.
        _src_name = type(getattr(data, "source", None)).__name__
        if isinstance(frame, LLMFullResponseStartFrame):
            if "LLM" in _src_name:
                self._buffer = ""
                self._pending_sentence = None
            return

        # Capture from LLM service source only (one occurrence per token,
        # before ExpressTagFilter/SilenceFilter/ReactiveGate re-push it).
        # CerebrasLLMService and OpenAILLMService both contain "LLM".
        if isinstance(frame, LLMTextFrame) and "LLM" in _src_name:
            text = getattr(frame, "text", "") or ""
            if text:
                self._buffer += text
                self._emit_complete_sentences()
                if len(self._buffer) > self._max_buffer_chars:
                    self._flush_buffer()
            return

        # Flush trailing content when TTS finishes playing.
        if isinstance(frame, TTSStoppedFrame):
            self._flush_at_end()

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
        pending = self._buffer.strip()
        self._buffer = ""
        if pending:
            self._commit_pending()
            self._pending_sentence = pending

    def _flush_at_end(self):
        trailing = self._buffer.strip()
        self._buffer = ""
        if trailing and self._pending_sentence is not None:
            self._pending_sentence = f"{self._pending_sentence} {trailing}"
        elif trailing:
            self._pending_sentence = trailing
        self._commit_pending()

    def _commit_pending(self):
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

        # Strip express tags and markdown before logging/display
        clean = _EXPRESS_TAG_RE.sub("", sentence).strip()
        clean = re.sub(r'\*+|_{1,2}|`+', "", clean).strip()
        if not clean:
            return

        logger.info(f"🗣️ TARS: {clean}")
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
