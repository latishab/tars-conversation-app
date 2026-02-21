"""
State observer for WebRTC DataChannel synchronization.

Observes Pipecat pipeline events and sends state updates to RPi via DataChannel:
- Transcription events → eye state (listening)
- LLM events → eye state (thinking)
- TTS events → eye state (speaking)
- Transcripts → text display
"""

import asyncio
from typing import Optional
from loguru import logger

from pipecat.observers.base_observer import BaseObserver
from pipecat.frames.frames import (
    TranscriptionFrame,
    LLMFullResponseStartFrame,
    LLMFullResponseEndFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)

from transport.state_sync import StateSync


class StateObserver(BaseObserver):
    """
    Observes pipeline events and sends state to RPi via DataChannel.

    Automatically manages eye states based on conversation flow:
    - User speaking → listening
    - LLM processing → thinking
    - TTS output → speaking
    - Idle → default
    """

    def __init__(self, state_sync: Optional[StateSync] = None):
        """
        Initialize state observer.

        Args:
            state_sync: StateSync instance for sending messages
        """
        super().__init__()
        self.state_sync = state_sync
        self._current_state = "idle"
        self._idle_delay = 0.5
        self._idle_task = None

        # Set initial status in shared state
        try:
            from shared_state import metrics_store
            metrics_store.set_pipeline_status("idle")
        except Exception as e:
            logger.error(f"Failed to set initial pipeline status: {e}")

    def set_state_sync(self, state_sync: StateSync):
        """Set StateSync instance."""
        self.state_sync = state_sync

    async def on_transcription(self, *args, **kwargs):
        """Handle transcription events (user speaking)."""
        try:
            # Cancel pending idle timer
            self.cancel_idle_timer()

            # Extract frame from args
            frame = args[0] if args else None

            if isinstance(frame, TranscriptionFrame):
                text = frame.text
                user_id = getattr(frame, "user_id", "user")

                # Send transcript to RPi
                if self.state_sync:
                    self.state_sync.send_transcript("user", text)
                    # Set eye state to listening when user speaks
                    if text.strip():
                        self._update_state("listening")

                logger.debug(f"📝 Transcription: {text}")

        except Exception as e:
            logger.error(f"❌ Error in transcription observer: {e}")

    async def on_llm_full_response_start(self, *args, **kwargs):
        """Handle LLM response start (thinking)."""
        try:
            # Cancel pending idle timer
            self.cancel_idle_timer()

            if self.state_sync:
                self._update_state("thinking")
            logger.debug("🧠 LLM thinking started")
        except Exception as e:
            logger.error(f"❌ Error in LLM start observer: {e}")

    async def on_llm_full_response_end(self, *args, **kwargs):
        """Handle LLM response end."""
        try:
            # State will be updated by TTS start or return to idle
            logger.debug("🧠 LLM thinking ended")
        except Exception as e:
            logger.error(f"❌ Error in LLM end observer: {e}")

    async def on_tts_started(self, *args, **kwargs):
        """Handle TTS start (speaking)."""
        try:
            if self.state_sync:
                self._update_state("speaking")
                self.state_sync.send_tts_state(True)
            logger.debug("🔊 TTS started")
        except Exception as e:
            logger.error(f"❌ Error in TTS start observer: {e}")

    async def on_tts_stopped(self, *args, **kwargs):
        """Handle TTS stop (return to idle after delay)."""
        try:
            if self.state_sync:
                self.state_sync.send_tts_state(False)

                # Cancel existing idle timer
                if self._idle_task and not self._idle_task.done():
                    self._idle_task.cancel()

                # Set idle after delay
                async def delayed_idle():
                    await asyncio.sleep(self._idle_delay)
                    self._update_state("idle")

                self._idle_task = asyncio.create_task(delayed_idle())
                logger.debug("TTS stopped, idle in 0.5s")
        except Exception as e:
            logger.error(f"Error in TTS stop observer: {e}")

    async def on_user_transcript(self, *args, **kwargs):
        """Handle complete user transcript."""
        try:
            # Extract text from args
            text = args[1] if len(args) > 1 else ""
            if text and self.state_sync:
                self.state_sync.send_transcript("user", text)
        except Exception as e:
            logger.error(f"❌ Error in user transcript observer: {e}")

    async def on_bot_transcript(self, *args, **kwargs):
        """Handle complete bot transcript."""
        try:
            # Extract text from args
            text = args[1] if len(args) > 1 else ""
            if text and self.state_sync:
                self.state_sync.send_transcript("assistant", text)
        except Exception as e:
            logger.error(f"❌ Error in bot transcript observer: {e}")

    def cancel_idle_timer(self):
        """Cancel pending idle timer."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    def _update_state(self, new_state: str):
        """
        Update eye state if changed.

        Args:
            new_state: New state to set
        """
        if new_state != self._current_state:
            logger.debug(f"State transition: {self._current_state} → {new_state}")
            self._current_state = new_state

            # Update shared state for UI
            try:
                from shared_state import metrics_store
                metrics_store.set_pipeline_status(new_state)
            except Exception as e:
                logger.error(f"Failed to update pipeline status: {e}")

            # Update robot display via DataChannel
            if self.state_sync:
                self.state_sync.send_eye_state(new_state)
