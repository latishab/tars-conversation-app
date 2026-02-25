"""
State observer for pipeline status and DataChannel synchronization.

Uses Pipecat's on_push_frame hook to detect frame types as they flow through
the pipeline, then updates shared_state (Gradio UI) and sends eye/TTS state
to the RPi via DataChannel.
"""

import asyncio
from typing import Optional
from loguru import logger

from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.frames.frames import (
    TranscriptionFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.llm_service import LLMService

from transport.state_sync import StateSync


class StateObserver(BaseObserver):
    """Watches pipeline frames and updates UI status + RPi eye state."""

    def __init__(self, state_sync: Optional[StateSync] = None):
        super().__init__()
        self.state_sync = state_sync
        self._current_state = "idle"
        self._idle_task = None
        self._bot_text_buf: list[str] = []

        from shared_state import metrics_store
        metrics_store.set_pipeline_status("idle")

    def set_state_sync(self, state_sync: StateSync):
        self.state_sync = state_sync

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame

        if isinstance(frame, TranscriptionFrame):
            self._cancel_idle_timer()
            if frame.text.strip():
                self._update_state("listening")
                from shared_state import metrics_store
                metrics_store.add_transcription("user", frame.text)
                if self.state_sync:
                    self.state_sync.send_transcript("user", frame.text)

        elif isinstance(frame, LLMTextFrame):
            # Only collect on the first hop (directly from LLM); the frame
            # also propagates downstream through SilenceFilter → TTS, which
            # would cause each token to be appended multiple times.
            if isinstance(data.source, LLMService):
                self._bot_text_buf.append(frame.text)

        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._bot_text_buf:
                text = "".join(self._bot_text_buf).strip()
                self._bot_text_buf.clear()
                if text:
                    from shared_state import metrics_store
                    metrics_store.add_transcription("assistant", text)
                    if self.state_sync:
                        self.state_sync.send_transcript("assistant", text)

        elif isinstance(frame, LLMFullResponseStartFrame):
            self._cancel_idle_timer()
            self._update_state("thinking")

        elif isinstance(frame, TTSStartedFrame):
            self._cancel_idle_timer()
            self._update_state("speaking")
            if self.state_sync:
                self.state_sync.send_tts_state(True)

        elif isinstance(frame, TTSStoppedFrame):
            if self.state_sync:
                self.state_sync.send_tts_state(False)
            self._schedule_idle()

    def _update_state(self, new_state: str):
        if new_state == self._current_state:
            return
        logger.debug(f"State: {self._current_state} → {new_state}")
        self._current_state = new_state
        from shared_state import metrics_store
        metrics_store.set_pipeline_status(new_state)
        if self.state_sync:
            self.state_sync.send_eye_state(new_state)

    def _schedule_idle(self):
        self._cancel_idle_timer()

        async def _go_idle():
            await asyncio.sleep(0.5)
            self._update_state("idle")

        self._idle_task = asyncio.create_task(_go_idle())

    def _cancel_idle_timer(self):
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None
