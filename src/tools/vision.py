"""Vision and camera analysis tools.

Two camera sources:
- capture_user_camera() - User's video feed during call
- capture_robot_camera() - TARS' Pi camera view
"""

import base64
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import UserImageRequestFrame, UserImageRawFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams
from loguru import logger


async def capture_user_camera(params: FunctionCallParams):
    """Capture image from user's camera feed for vision analysis."""
    user_id = params.arguments["user_id"]
    question = params.arguments["question"]
    logger.info(f"Requesting user camera image with user_id={user_id}, question={question}")

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
        logger.error(f"Error requesting user camera image: {e}", exc_info=True)
        await params.result_callback(f"Unable to access camera feed: {str(e)}")


async def capture_robot_camera(params: FunctionCallParams):
    """Capture image from TARS' Pi camera and analyze with vision model."""
    question = params.arguments.get("question", "What do you see?")

    try:
        from services import tars_robot

        logger.info(f"Capturing robot camera view for question: {question}")
        result = await tars_robot.capture_camera_view()

        if result.get("status") == "error":
            error = result.get("error", "unknown error")
            logger.warning(f"Robot camera capture failed: {error}")
            await params.result_callback(f"Unable to capture camera image: {error}")
            return

        # Get base64 image
        img_base64 = result.get("image")
        if not img_base64:
            await params.result_callback("Camera returned no image data.")
            return

        # Decode base64 to bytes
        img_bytes = base64.b64decode(img_base64)

        # Send vision frame for analysis
        vision_frame = UserImageRawFrame(
            image=img_bytes,
            size=(result.get("width", 640), result.get("height", 480)),
            format=result.get("format", "jpeg"),
            text=question
        )

        await params.llm.push_frame(vision_frame, FrameDirection.UPSTREAM)
        logger.info(f"Robot camera image sent for vision analysis: {result.get('width')}x{result.get('height')}")

        await params.result_callback("Processing camera image...")

    except Exception as e:
        logger.error(f"Robot camera capture error: {e}", exc_info=True)
        await params.result_callback(f"Error capturing camera view: {str(e)}")


def create_user_camera_schema() -> FunctionSchema:
    """Create the capture_user_camera function schema."""
    return FunctionSchema(
        name="capture_user_camera",
        description=(
            "Capture image from user's camera feed during video call for vision analysis. "
            "ONLY call this when the user EXPLICITLY asks about what they are SHOWING on camera, "
            "what is VISIBLE in their camera feed, or asks you to LOOK at or DESCRIBE what's on screen. "
            "DO NOT call this for questions about memory, recall, conversation history, or anything that "
            "doesn't require visual analysis of the current camera feed. Examples: 'What do you see?', "
            "'Describe what's on my camera', 'What am I showing you?', 'Can you see this?'. "
            "Counter-examples (DO NOT call): 'Do you remember my name?', 'What did I tell you?', "
            "'What's my favorite color?' (unless they're showing it on camera). "
            "IMPORTANT: After calling this function, DO NOT generate an immediate acknowledgment message. "
            "Wait silently for the vision analysis result to arrive - it will be provided automatically. "
            "Once you receive the vision result, respond directly with what you see."
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


def create_robot_camera_schema() -> FunctionSchema:
    """Create the capture_robot_camera function schema."""
    return FunctionSchema(
        name="capture_robot_camera",
        description=(
            "Capture an image from TARS' camera on the Raspberry Pi and analyze what's visible. "
            "Use this when the user asks what TARS can see from its own perspective/camera, "
            "such as 'What can you see from your camera?', 'Look around', 'What's in front of you?'. "
            "This is DIFFERENT from capture_user_camera which captures from the user's camera during a video call. "
            "ONLY call this for questions about TARS' physical camera view, not the user's camera feed."
        ),
        properties={
            "question": {
                "type": "string",
                "description": "The specific question about what TARS should look for in its camera view",
                "default": "What do you see?"
            }
        },
        required=[],
    )
