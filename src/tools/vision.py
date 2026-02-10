"""Vision and camera analysis tools."""

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import UserImageRequestFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams
from loguru import logger


async def fetch_user_image(params: FunctionCallParams):
    """Fetch user image for vision analysis."""
    user_id = params.arguments["user_id"]
    question = params.arguments["question"]
    logger.info(f"Requesting image with user_id={user_id}, question={question}")

    try:
        # Request image frame (processed by Moondream, not added to context)
        await params.llm.push_frame(
            UserImageRequestFrame(user_id=user_id, text=question, append_to_context=False),
            FrameDirection.UPSTREAM,
        )
        logger.debug("UserImageRequestFrame sent to pipeline")

        # Return a minimal status - the LLM should wait for the vision result
        await params.result_callback("Processing...")
    except Exception as e:
        logger.error(f"Error requesting image: {e}", exc_info=True)
        await params.result_callback(f"Unable to access camera feed: {str(e)}")


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
            "IMPORTANT: After calling this function, DO NOT generate an immediate acknowledgment message. "
            "Wait silently for the vision analysis result to arrive - it will be provided automatically. "
            "Once you receive the vision result, respond directly with what you see. Do not say 'analyzing' "
            "or 'please hold' - just wait for the result and then describe what you see."
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
