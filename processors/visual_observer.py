import asyncio
import time
from typing import Optional, List
from loguru import logger
from pipecat.frames.frames import Frame, ImageRawFrame, TextFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
import base64
from PIL import Image
import io

class VisualObserver(FrameProcessor):
    """
    Observer that waits for UserImageRequestFrame, captures the next video frame,
    analyzes it with a vision model, and injects the description back into the context.
    """

    def __init__(self, vision_client, model="moondream"):
        super().__init__()
        self._vision_client = vision_client
        self._model = model
        self._waiting_for_image = False
        self._current_request = None
        self._last_analysis_time = 0
        self._cooldown = 2.0  # Min seconds between analyses

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # 1. Handle Request from LLM (Check by class name to avoid import errors)
        # We check for "UserImageRequestFrame" (your custom frame) OR "VisionImageRequestFrame"
        if frame.__class__.__name__ in ["UserImageRequestFrame", "VisionImageRequestFrame"]:
            logger.info(f"👁️ Vision request received: {getattr(frame, 'context', 'No context')}")
            self._waiting_for_image = True
            self._current_request = frame
            # We don't yield this frame downstream; we consume it and act on it.
            return

        # 2. Handle Video Input (Only if we are waiting for an image)
        if isinstance(frame, ImageRawFrame) and self._waiting_for_image:
            # Check cooldown
            if time.time() - self._last_analysis_time < self._cooldown:
                return

            logger.info("📸 Capturing frame for analysis...")
            self._waiting_for_image = False  # Reset flag immediately
            self._last_analysis_time = time.time()

            # Run analysis in background to avoid blocking audio pipeline
            asyncio.create_task(self._analyze_and_respond(frame))
            return

        # Pass all other frames through
        await self.push_frame(frame, direction)

    async def _analyze_and_respond(self, frame: ImageRawFrame):
        """Analyze image and push result text frame downstream."""
        try:
            # Convert raw frame to base64
            image = Image.frombytes(frame.format, frame.size, frame.image)
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            prompt = "Describe this image briefly."
            
            # Try to extract prompt from the request context if available
            if self._current_request and hasattr(self._current_request, 'context'):
                 # Assuming context might be the question text
                 context = self._current_request.context
                 if context: 
                     prompt = f"{context} (Describe the image to answer this)"

            logger.info(f"🔍 Sending image to vision model ({self._model})...")
            
            try:
                response = await asyncio.wait_for(
                    self._vision_client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{img_str}"
                                        },
                                    },
                                ],
                            }
                        ],
                        max_tokens=100
                    ),
                    timeout=8.0  # 8 second timeout to prevent hanging
                )
                description = response.choices[0].message.content
                logger.info(f"✅ Vision analysis: {description}")

            except asyncio.TimeoutError:
                logger.warning("⚠️ Vision model timed out!")
                description = "I couldn't see clearly because the visual processing timed out."
            except Exception as e:
                logger.error(f"❌ Vision model error: {e}")
                description = "I had trouble processing the visual data."

            feedback_text = f"[Visual Observation]: {description}"
            
            # Push text frame to LLM
            await self.push_frame(TextFrame(text=feedback_text), FrameDirection.UPSTREAM)

        except Exception as e:
            logger.error(f"Error in vision pipeline: {e}")
            self._waiting_for_image = False