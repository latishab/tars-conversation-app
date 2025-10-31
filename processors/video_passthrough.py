"""Processor for passing through video frames to the output."""

from loguru import logger
from pipecat.frames.frames import Frame, InputImageRawFrame, OutputImageRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class VideoPassThrough(FrameProcessor):
    """A simple processor that forwards camera video frames back to the user."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        # Forward camera video frames back to the user
        # Accept InputImageRawFrame from any source and convert to OutputImageRawFrame
        if isinstance(frame, InputImageRawFrame):
            # Log the frame to help debug
            transport_source = getattr(frame, 'transport_source', 'unknown')
            logger.info(f"📹 Received InputImageRawFrame from source: {transport_source}, size={frame.size if hasattr(frame, 'size') else 'unknown'}")
            
            # Create an output frame with the same image data
            # This will be sent back to the client via the transport
            try:
                out_frame = OutputImageRawFrame(
                    image=frame.image,
                    size=frame.size if hasattr(frame, 'size') else None,
                    format=frame.format if hasattr(frame, 'format') else None
                )
                logger.info(f"📹 Created OutputImageRawFrame, pushing downstream")
                # Push OutputImageRawFrame downstream - this will be sent back to client
                await self.push_frame(out_frame, FrameDirection.DOWNSTREAM)
            except Exception as e:
                logger.error(f"Error creating OutputImageRawFrame: {e}", exc_info=True)
            
            # Also push the InputImageRawFrame through so it can be processed by Moondream if needed
            # This allows the vision pipeline to still work
            await self.push_frame(frame, direction)
        else:
            # Push all other frames through unchanged (audio frames, OutputImageRawFrame, etc.)
            await self.push_frame(frame, direction)

