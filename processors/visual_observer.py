"""Visual Observer: Background visual heartbeat for eye contact detection."""

import time
import asyncio
from loguru import logger
from PIL import Image
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, UserImageRawFrame, ImageRawFrame
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
        
        # Shared Context 
        self.visual_context = {
            "is_looking_at_robot": False,
            "last_updated": 0
        }

    async def _analyze_frame(self, frame: UserImageRawFrame):
        """Background task: Asks Moondream if there is eye contact."""
        try:
            # We create a temporary one-off query for Moondream
            prompt = "Is the person in the image looking directly at the camera? Answer YES or NO."
            
            # Check if the service has the underlying model available
            if not hasattr(self._moondream, "_model"):
                logger.warning("VisualObserver: Moondream model not initialized yet.")
                return

            # Skip empty frames (common with VP8/decoding errors)
            if not frame.image or len(frame.image) == 0:
                return

            # Internal helper to run inference in a thread (blocking operation)
            def run_inference():
                try:
                    # Convert raw frame bytes to a PIL Image
                    image = Image.frombytes(frame.format, frame.size, frame.image)
                    
                    # Access the underlying model directly
                    model = self._moondream._model
                    enc_image = model.encode_image(image)
                    return model.query(enc_image, prompt)["answer"]
                except Exception as inner_e:
                    logger.warning(f"Inference error: {inner_e}")
                    return "no"

            # Run inference (This takes ~1.5s but runs in background)
            response = await asyncio.to_thread(run_inference)
            
            # Parse result
            is_looking = "yes" in response.lower()
            
            # Update the global variable
            self.visual_context["is_looking_at_robot"] = is_looking
            self.visual_context["last_updated"] = time.time()
            
            if is_looking:
                logger.debug("👀 VisualObserver: Eye contact detected")
                
        except Exception as e:
            logger.warning(f"Visual observer failed: {e}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """
        Intercepts UserImageRawFrames. Fires background task if interval passed.
        ALWAYS pushes frame downstream immediately.
        """
        await super().process_frame(frame, direction)

        # Use UserImageRawFrame 
        if isinstance(frame, (UserImageRawFrame, ImageRawFrame)) and direction == FrameDirection.DOWNSTREAM:
            now = time.time()
            # If 2 seconds have passed since last check
            if now - self._last_check > self._interval:
                self._last_check = now
                # Fire and forget! (create_task ensures we don't wait/block)
                asyncio.create_task(self._analyze_frame(frame))
        
        # PUSH IMMEDIATELY - Do not wait for analysis
        await self.push_frame(frame, direction)