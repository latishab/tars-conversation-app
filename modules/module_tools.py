"""LLM function tools and schemas for TARS bot."""

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import UserImageRequestFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from loguru import logger

# Global storage for TTS speed setting (shared across function calls)
_tts_speed_storage = {"speed": 1.0, "tts_service": None}


async def fetch_user_image(params: FunctionCallParams):
    """Fetch user image for vision analysis."""
    user_id = params.arguments["user_id"]
    question = params.arguments["question"]
    logger.info(f"📸 Requesting image with user_id={user_id}, question={question}")

    try:
        # Request image frame (processed by Moondream, not added to context)
        await params.llm.push_frame(
            UserImageRequestFrame(user_id=user_id, text=question, append_to_context=False),
            FrameDirection.UPSTREAM,
        )
        logger.debug("✓ UserImageRequestFrame sent to pipeline")
        
        # Return immediately with a status message so LLM can acknowledge right away
        # Moondream will process in the background and send results when ready
        # This prevents the LLM from blocking while waiting for vision processing
        await params.result_callback("Vision request sent. Processing camera feed...")
    except Exception as e:
        logger.error(f"❌ Error requesting image: {e}", exc_info=True)
        # Return error message so LLM can inform user
        await params.result_callback(f"Unable to access camera feed: {str(e)}")


async def set_speaking_rate(params: FunctionCallParams):
    """Adjust speaking speed: fast (1.2x) for urgent, slow (0.8x) for complex, normal (1.0x) default."""
    rate = params.arguments.get("rate", "normal")
    speed_value = 1.0
    
    if rate == "fast":
        speed_value = 1.2  # Max reliable speed for urgent situations
        logger.info("⚡ TARS engaging High-Speed Mode (1.2x)")
    elif rate == "slow":
        speed_value = 0.8  # Slower, more deliberate for complex topics
        logger.info("🐢 TARS engaging Precision Mode (0.8x)")
    else:
        speed_value = 1.0
        logger.info("✓ TARS speaking at Normal Speed (1.0x)")
    
    _tts_speed_storage["speed"] = speed_value
    
    # Update TTS service if available
    tts_service = _tts_speed_storage.get("tts_service")
    if tts_service:
        try:
            if hasattr(tts_service, 'speed'):
                tts_service.speed = speed_value
            elif hasattr(tts_service, '_speed'):
                tts_service._speed = speed_value
        except Exception as e:
            logger.debug(f"Could not update TTS speed: {e}")
    
    await params.result_callback(f"Speaking rate set to {rate} ({speed_value}x speed)")


def get_tts_speed_storage():
    """Get the TTS speed storage dictionary for external access."""
    return _tts_speed_storage


def create_fetch_image_schema() -> FunctionSchema:
    """Create the fetch_user_image function schema."""
    return FunctionSchema(
        name="fetch_user_image",
        description=(
            "ONLY call this function when the user EXPLICITLY asks about what they are SHOWING on camera, "
            "what is VISIBLE in their camera feed, or asks you to LOOK at or DESCRIBE what's on screen. "
            "DO NOT call this for questions about memory, recall, conversation history, or anything that "
            "doesn't require visual analysis of the current camera feed. Examples: 'What do you see?', "
            "'Describe what's on my camera', 'What am I showing you?', 'Can you see this?'. "
            "Counter-examples (DO NOT call): 'Do you remember my name?', 'What did I tell you?', "
            "'What's my favorite color?' (unless they're showing it on camera). "
            "IMPORTANT: After calling this function, immediately respond to the user acknowledging their request. "
            "The vision analysis will process in the background and you will receive the results automatically. "
            "Do not wait for the vision result before responding - acknowledge first, then describe what you see once the result arrives."
        ),
        properties={
            "user_id": {
                "type": "string",
                "description": "The ID of the user to grab the image from",
            },
            "question": {
                "type": "string",
                "description": "The specific question about what is visible in the camera feed",
            },
        },
        required=["user_id", "question"],
    )


def create_speaking_rate_schema() -> FunctionSchema:
    """Create the set_speaking_rate function schema."""
    return FunctionSchema(
        name="set_speaking_rate",
        description="Adjusts your speaking speed to match the user's energy and urgency. Use 'fast' if the user is urgent/panicked, 'slow' for complex topics or when the user is confused, 'normal' for default operation.",
        properties={
            "rate": {
                "type": "string",
                "enum": ["fast", "normal", "slow"],
                "description": "The desired speaking rate: 'fast' (1.2x) for urgent situations, 'slow' (0.8x) for complex explanations, 'normal' (1.0x) for default.",
            },
        },
        required=["rate"],
    )

