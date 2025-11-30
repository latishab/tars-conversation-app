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
        self._video_frame_count = 0
        self._last_video_frame_time = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        import time
        current_time = time.time()
        
        frame_type = type(frame).__name__
        direction_str = "UPSTREAM" if direction == FrameDirection.UPSTREAM else "DOWNSTREAM"
        
        # Log vision request frames
        if isinstance(frame, UserImageRequestFrame):
            user_id = getattr(frame, 'user_id', 'unknown')
            question = getattr(frame, 'text', 'unknown')
            logger.info(f"👁️ Vision request received [{direction_str}]: user_id={user_id}, question={question}")
            self._last_vision_request_time = current_time  # Track when vision was requested
            self._vision_request_count = getattr(self, '_vision_request_count', 0) + 1
            logger.info(f"📊 Vision request #{self._vision_request_count} - waiting for video frames and Moondream response...")
            
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

        elif 'video' in frame_type.lower() or 'image' in frame_type.lower() or 'vision' in frame_type.lower():
            # Only log at info level if we're actively processing a vision request
            is_vision_active = hasattr(self, '_last_vision_request_time') and self._last_vision_request_time is not None
            if is_vision_active:
                time_since_request = current_time - self._last_vision_request_time
                if time_since_request < 5:  # Only log during active vision processing (5 seconds)
                    logger.debug(f"📷 Vision-related frame [{direction_str}]: {frame_type}")
            else:
                # Otherwise, only log at debug level (won't show unless debug logging is enabled)
                logger.debug(f"📷 Vision-related frame [{direction_str}]: {frame_type}")

        # Log frames with image attribute only at debug level
        elif hasattr(frame, 'image'):
            logger.debug(f"📷 Frame with image attribute [{direction_str}]: {frame_type}")

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
            vision_keywords = ['see', 'visible', 'camera', 'image', 'showing', 'appears', 'looks like', 'dimly lit', 'desk', 'monitor', 'room', 'window', 'mug', 'laptop', 'coffee', 'analyzing', 'processing']
            
            # Check if this is a vision response (either from keywords or if we recently requested vision)
            is_vision_response = False
            if hasattr(self, '_last_vision_request_time'):
                time_since_request = current_time - self._last_vision_request_time
                if time_since_request < 10:  # Within 10 seconds of vision request
                    is_vision_response = True
                    logger.info(f"✅ Vision response received [{direction_str}] (within {time_since_request:.1f}s of request): {text[:200]}..." if len(text) > 200 else f"✅ Vision response: {text}")
            
            if text and any(keyword in text.lower() for keyword in vision_keywords) and not is_vision_response:
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

        # Check for actual video frames (exclude audio frames)
        # Check for video frames - be specific to avoid false positives
        is_video_frame = False
        
        # Explicitly exclude audio frames
        if 'audio' in frame_type.lower():
            is_video_frame = False
        # Check for actual video frame types
        elif 'VideoRawFrame' in frame_type or 'InputVideoRawFrame' in frame_type:
            is_video_frame = True
        elif 'video' in frame_type.lower() and 'audio' not in frame_type.lower():
            # Only if it's a video frame and not an audio frame
            is_video_frame = True
        elif hasattr(frame, 'video') and not hasattr(frame, 'audio'):
            # Has video attribute but not audio
            is_video_frame = True
        elif hasattr(frame, 'image') and hasattr(frame, 'user_id'):
            # User image request/response frames
            is_video_frame = True
        
        # Only log actual video frames, not audio frames
        if is_video_frame:
            self._video_frame_count += 1
            self._last_video_frame_time = current_time
            # Only log every 100 frames to reduce spam significantly
            if self._video_frame_count % 100 == 0:
                logger.debug(f"🎥 Video frames streaming [{direction_str}]: {self._video_frame_count} frames received")
        
        # Log frame count summary every 30 seconds (less frequent)
        if not hasattr(self, '_last_summary_time'):
            self._last_summary_time = current_time
        elif current_time - self._last_summary_time >= 30:
            if self._video_frame_count > 0:
                logger.debug(f"📊 Video stream: {self._video_frame_count} frames in last 30 seconds")
            else:
                logger.warning(f"⚠️ No video frames detected in last 30 seconds!")
            self._video_frame_count = 0
            self._last_summary_time = current_time

        await self.push_frame(frame, direction)

