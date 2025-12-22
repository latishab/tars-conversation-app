"""Visual Observer: Background visual heartbeat for eye contact detection."""

import time
import asyncio
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, UserImageRawFrame
from pipecat.services.moondream.vision import MoondreamService


class VisualObserver(FrameProcessor):
    """
    Checks if the user is looking at the robot every 2 seconds.
    Running in the background ensures it NEVER blocks the audio conversation.
    """
    def __init__(self, moondream_service: MoondreamService, check_interval_sec: float = 2.0):
        super().__init__()
        self._moondream = moondream_service
        self._interval = check_interval_sec
        self._last_check = 0
        
        # Shared Context (The Gating Layer reads this)
        self.visual_context = {
            "is_looking_at_robot": False,
            "last_updated": 0
        }

    async def _analyze_frame(self, frame: UserImageRawFrame):
        """Background task: Asks Moondream if there is eye contact."""
        try:
            prompt = "Is the person in the image looking directly at the camera? Answer YES or NO."
            response = await self._moondream.run_image_query(frame.image, prompt)
            
            # Parse result
            is_looking = "yes" in response.lower()
            
            # Update the global variable
            self.visual_context["is_looking_at_robot"] = is_looking
            self.visual_context["last_updated"] = time.time()
            
            if is_looking:
                logger.debug("👀 VisualObserver: Eye contact detected")
                
        except Exception as e:
            logger.warning(f"Visual heartbeat failed: {e}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """
        Intercepts VideoFrames. Fires background task if interval passed.
        ALWAYS pushes frame downstream immediately.
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, UserImageRawFrame) and direction == FrameDirection.DOWNSTREAM:
            now = time.time()
            if now - self._last_check > self._interval:
                self._last_check = now
                asyncio.create_task(self._analyze_frame(frame))
        
        # PUSH IMMEDIATELY - Do not wait for analysis
        await self.push_frame(frame, direction)

