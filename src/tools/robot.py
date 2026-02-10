"""Robot hardware control tools."""

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from loguru import logger


async def execute_movement(params: FunctionCallParams):
    """Execute physical movement on TARS hardware."""
    movements = params.arguments.get("movements", [])

    if not movements:
        await params.result_callback("No movements specified.")
        return

    try:
        from services import tars_robot

        result = await tars_robot.execute_movement(movements)
        await params.result_callback(result)

    except Exception as e:
        logger.error(f"Movement execution error: {e}", exc_info=True)
        await params.result_callback(f"Error executing movement: {str(e)}")


async def capture_camera_view(params: FunctionCallParams):
    """Capture image from RPi camera and analyze with vision model."""
    question = params.arguments.get("question", "What do you see?")

    try:
        from services import tars_robot
        import base64
        from pipecat.frames.frames import VisionImageRawFrame
        from pipecat.processors.frame_processor import FrameDirection

        logger.info(f"Capturing camera view for question: {question}")
        result = await tars_robot.capture_camera_view()

        if result.get("status") == "error":
            error = result.get("error", "unknown error")
            logger.warning(f"Camera capture failed: {error}")
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
        vision_frame = VisionImageRawFrame(
            image=img_bytes,
            size=(result.get("width", 640), result.get("height", 480)),
            format=result.get("format", "jpeg"),
            text=question
        )

        await params.llm.push_frame(vision_frame, FrameDirection.UPSTREAM)
        logger.info(f"Camera image sent for vision analysis: {result.get('width')}x{result.get('height')}")

        await params.result_callback("Processing camera image...")

    except Exception as e:
        logger.error(f"Camera capture error: {e}", exc_info=True)
        await params.result_callback(f"Error capturing camera view: {str(e)}")


def create_movement_schema() -> FunctionSchema:
    """Create the execute_movement function schema."""
    return FunctionSchema(
        name="execute_movement",
        description=(
            "Execute physical movements on TARS hardware. Use this when the user asks you to move, "
            "walk, turn, or perform physical actions. Available movements: "
            "step_forward, walk_forward, step_backward, walk_backward, "
            "turn_left, turn_right, turn_left_slow, turn_right_slow, "
            "wave_left, wave_right, bow, pose, tilt_left, tilt_right. "
            "You can provide multiple movements in sequence. "
            "Examples: ['wave_right'], ['turn_left', 'step_forward'], ['walk_forward']. "
            "ONLY call this when the user explicitly requests physical movement."
        ),
        properties={
            "movements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of movements to execute in sequence",
                "minItems": 1
            }
        },
        required=["movements"],
    )


def create_camera_capture_schema() -> FunctionSchema:
    """Create the capture_camera_view function schema."""
    return FunctionSchema(
        name="capture_camera_view",
        description=(
            "Capture an image from TARS' camera on the Raspberry Pi and analyze what's visible. "
            "Use this when the user asks what TARS can see from its own perspective/camera, "
            "such as 'What can you see from your camera?', 'Look around', 'What's in front of you?'. "
            "This is DIFFERENT from fetch_user_image which captures from the user's camera during a video call. "
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
