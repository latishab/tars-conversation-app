"""Observer for sending pipeline events to TARS Raspberry Pi display."""

import asyncio
import time
import numpy as np
from loguru import logger
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.frames.frames import (
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TTSAudioRawFrame,
    AudioRawFrame,
)
from typing import Optional


class DisplayEventsObserver(BaseObserver):
    """
    Observes pipeline events and sends display updates to TARS Raspberry Pi.

    Handles:
    - User/bot speaking state changes
    - Audio levels for visualization
    - Emotional state changes (if available)
    """

    def __init__(self, tars_client=None):
        super().__init__()
        self.tars_client = tars_client
        self._user_speaking = False
        self._bot_speaking = False
        self._last_audio_update = 0
        self._audio_update_interval = 0.05  # Update audio levels every 50ms

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        # User started speaking
        if isinstance(frame, UserStartedSpeakingFrame):
            logger.info("👂 User started speaking - updating display")
            self._user_speaking = True
            if self.tars_client and self.tars_client.is_connected():
                asyncio.create_task(self.tars_client.set_eye_state("listening"))

        # User stopped speaking
        elif isinstance(frame, UserStoppedSpeakingFrame):
            logger.info("🤔 User stopped speaking - thinking state")
            self._user_speaking = False
            if self.tars_client and self.tars_client.is_connected():
                asyncio.create_task(self.tars_client.set_eye_state("thinking"))

        # Bot started speaking
        elif isinstance(frame, BotStartedSpeakingFrame):
            logger.info("🗣️ Bot started speaking - updating display")
            self._bot_speaking = True
            if self.tars_client and self.tars_client.is_connected():
                asyncio.create_task(self.tars_client.set_eye_state("speaking"))

        # Bot stopped speaking
        elif isinstance(frame, BotStoppedSpeakingFrame):
            logger.info("🤐 Bot stopped speaking - idle state")
            self._bot_speaking = False
            if self.tars_client and self.tars_client.is_connected():
                asyncio.create_task(self.tars_client.set_eye_state("idle"))

        # TTS audio frames - measure audio level for display visualization
        elif isinstance(frame, TTSAudioRawFrame):
            current_time = time.time()
            if current_time - self._last_audio_update > self._audio_update_interval:
                self._last_audio_update = current_time

                # Calculate RMS audio level
                level = self._calculate_audio_level(frame.audio)

                if self.tars_client and self.tars_client.is_connected():
                    asyncio.create_task(
                        self.tars_client.set_audio_level(level, "speaker")
                    )

        # User audio frames - measure user audio level
        elif isinstance(frame, AudioRawFrame) and self._user_speaking:
            current_time = time.time()
            if current_time - self._last_audio_update > self._audio_update_interval:
                self._last_audio_update = current_time

                # Calculate RMS audio level
                level = self._calculate_audio_level(frame.audio)

                if self.tars_client and self.tars_client.is_connected():
                    asyncio.create_task(
                        self.tars_client.set_audio_level(level, "mic")
                    )

    def _calculate_audio_level(self, audio_data: bytes) -> float:
        """
        Calculate normalized RMS audio level from raw audio bytes.

        Args:
            audio_data: Raw audio bytes (16-bit PCM)

        Returns:
            Normalized audio level (0.0 to 1.0)
        """
        try:
            # Convert bytes to numpy array (assuming 16-bit PCM)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)

            # Calculate RMS (root mean square)
            if len(audio_array) > 0:
                rms = np.sqrt(np.mean(audio_array.astype(float) ** 2))
                # Normalize to 0-1 range (15000 is a typical speaking level for 16-bit audio)
                level = min(1.0, rms / 15000.0)
                return level
            return 0.0
        except Exception as e:
            logger.debug(f"Error calculating audio level: {e}")
            return 0.0
