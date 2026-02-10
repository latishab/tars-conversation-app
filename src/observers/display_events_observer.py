"""Observer for sending pipeline events to TARS Raspberry Pi display.

NOTE: This observer is deprecated. Display control is now handled via gRPC
in robot mode (tars_bot.py). Browser mode does not support display control.
"""

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

    DEPRECATED: Display control moved to gRPC in robot mode.
    This observer is kept for compatibility but does nothing.
    """

    def __init__(self, tars_client=None):
        super().__init__()
        self.tars_client = None
        self._user_speaking = False
        self._bot_speaking = False
        self._last_audio_update = 0
        self._audio_update_interval = 0.05

    async def on_push_frame(self, data: FramePushed):
        """Watch frames as they're pushed through the pipeline."""
        frame = data.frame

        # User started speaking
        if isinstance(frame, UserStartedSpeakingFrame):
            logger.debug("User started speaking")
            self._user_speaking = True

        # User stopped speaking
        elif isinstance(frame, UserStoppedSpeakingFrame):
            logger.debug("User stopped speaking")
            self._user_speaking = False

        # Bot started speaking
        elif isinstance(frame, BotStartedSpeakingFrame):
            logger.debug("Bot started speaking")
            self._bot_speaking = True

        # Bot stopped speaking
        elif isinstance(frame, BotStoppedSpeakingFrame):
            logger.debug("Bot stopped speaking")
            self._bot_speaking = False

        # TTS audio frames - measure audio level for display visualization
        elif isinstance(frame, TTSAudioRawFrame):
            current_time = time.time()
            if current_time - self._last_audio_update > self._audio_update_interval:
                self._last_audio_update = current_time
                level = self._calculate_audio_level(frame.audio)

        # User audio frames - measure user audio level
        elif isinstance(frame, AudioRawFrame) and self._user_speaking:
            current_time = time.time()
            if current_time - self._last_audio_update > self._audio_update_interval:
                self._last_audio_update = current_time
                level = self._calculate_audio_level(frame.audio)

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
