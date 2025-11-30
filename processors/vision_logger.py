"""Processor for logging vision/Moondream processing and sending status to the frontend."""

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    UserImageRequestFrame,
    LLMTextFrame,
    ErrorFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class VisionLogger(FrameProcessor):
    """Logs vision processing events and Moondream activity."""

    def __init__(self, webrtc_connection=None):
        super().__init__()
        self.webrtc_connection = webrtc_connection

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        frame_type = type(frame).__name__
        direction_str = "UPSTREAM" if direction == FrameDirection.UPSTREAM else "DOWNSTREAM"
        
        # Log vision request frames
        if isinstance(frame, UserImageRequestFrame):
            import time
            user_id = getattr(frame, 'user_id', 'unknown')
            question = getattr(frame, 'text', 'unknown')
            logger.info(f"👁️ Vision request received [{direction_str}]: user_id={user_id}, question={question}")
            self._last_vision_request_time = time.time()  # Track when vision was requested
            
            # Send status to frontend
            if self.webrtc_connection:
                try:
                    if self.webrtc_connection.is_connected():
                        self.webrtc_connection.send_app_message({
                            "type": "vision",
                            "status": "requested",
                            "question": question
                        })
                except Exception as e:
                    logger.debug(f"Error sending vision status: {e}")

        # Log ALL frames that might be vision-related - be very broad
        elif 'video' in frame_type.lower() or 'image' in frame_type.lower() or 'vision' in frame_type.lower():
            logger.info(f"📷 Vision-related frame [{direction_str}]: {frame_type}")
            # Try to get any useful info
            for attr in ['image', 'user_id', 'text', 'question', 'response']:
                if hasattr(frame, attr):
                    value = getattr(frame, attr)
                    if attr == 'image' and value is not None:
                        try:
                            if hasattr(value, 'size'):
                                logger.debug(f"   Image size: {value.size}")
                            elif hasattr(value, 'shape'):
                                logger.debug(f"   Image shape: {value.shape}")
                        except:
                            pass
                    elif value:
                        logger.debug(f"   {attr}: {str(value)[:100]}")

        # Log frames with image attribute
        elif hasattr(frame, 'image'):
            logger.info(f"📷 Frame with image attribute [{direction_str}]: {frame_type}")
            try:
                img = getattr(frame, 'image')
                if img is not None:
                    if hasattr(img, 'size'):
                        logger.debug(f"   Image size: {img.size}")
                    elif hasattr(img, 'shape'):
                        logger.debug(f"   Image shape: {img.shape}")
            except Exception as e:
                logger.debug(f"   Could not inspect image: {e}")

        # Log any frame that might be a vision response by checking attributes
        elif hasattr(frame, 'user_id') and hasattr(frame, 'text'):
            user_id = getattr(frame, 'user_id', 'unknown')
            text = getattr(frame, 'text', '')
            if 'vision' in frame_type.lower() or 'image' in frame_type.lower() or 'moondream' in frame_type.lower():
                logger.info(f"✅ Vision response frame [{direction_str}]: {frame_type}, user_id={user_id}")
                logger.info(f"   Response: {text[:200]}..." if len(text) > 200 else f"   Response: {text}")

        # Log LLM text frames that might contain vision responses
        # Moondream responses come through as LLMTextFrame with vision context
        elif isinstance(frame, LLMTextFrame):
            text = getattr(frame, 'text', '')
            vision_keywords = ['see', 'visible', 'camera', 'image', 'showing', 'appears', 'looks like', 'dimly lit', 'desk', 'monitor', 'room', 'window', 'mug', 'laptop', 'coffee']
            if text and any(keyword in text.lower() for keyword in vision_keywords):
                logger.info(f"✅ Possible vision response in LLM text [{direction_str}]: {text[:200]}..." if len(text) > 200 else f"✅ Possible vision response: {text}")

        # Log errors
        elif isinstance(frame, ErrorFrame):
            error_msg = getattr(frame, 'error', str(frame))
            if 'vision' in error_msg.lower() or 'moondream' in error_msg.lower() or 'image' in error_msg.lower():
                logger.error(f"❌ Vision error: {error_msg}")
                
                # Send error to frontend
                if self.webrtc_connection:
                    try:
                        if self.webrtc_connection.is_connected():
                            self.webrtc_connection.send_app_message({
                                "type": "vision",
                                "status": "error",
                                "error": str(error_msg)
                            })
                    except Exception as e:
                        logger.debug(f"Error sending vision error: {e}")

        # TEMPORARY: Log all frame types to debug what's happening
        # This will help us see what frames are flowing through after a vision request
        # Remove this after we identify the issue
        if hasattr(self, '_last_vision_request_time'):
            import time
            if time.time() - self._last_vision_request_time < 30:  # Log for 30 seconds after vision request
                logger.debug(f"🔍 Frame after vision request [{direction_str}]: {frame_type}")

        await self.push_frame(frame, direction)

