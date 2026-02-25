"""Vision and camera analysis tools.

Two camera sources:
- capture_user_camera() - User's video feed during call
- capture_robot_camera() - TARS' Pi camera view (uses local Moondream model)
"""

import asyncio
import base64
import io
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import UserImageRequestFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams
from loguru import logger


_moondream_model = None

_state_sync_ref = None  # set by tars_bot.py after StateSync is created


def prewarm_moondream():
    """Load Moondream in a background thread at startup to avoid cold-start delay."""
    import threading
    threading.Thread(target=_get_moondream, daemon=True, name="MoondreamPrewarm").start()


def set_state_sync(ss):
    global _state_sync_ref
    _state_sync_ref = ss


def _notify_display(status: str, text: str, latency_ms: float = None):
    if _state_sync_ref is None:
        return
    icon = "OK" if status == "ok" else "ERR"
    lat = f" {latency_ms:.0f}ms" if latency_ms else ""
    _state_sync_ref.send_camera_log(f"[{icon}{lat}] {text}")


def _get_moondream():
    """Load Moondream model once and reuse."""
    global _moondream_model
    if _moondream_model is None:
        import torch
        from transformers import AutoModelForCausalLM

        if torch.backends.mps.is_available():
            device, dtype = torch.device("mps"), torch.float16
        elif torch.cuda.is_available():
            device, dtype = torch.device("cuda"), torch.float16
        else:
            device, dtype = torch.device("cpu"), torch.float32

        logger.info(f"Loading Moondream model on {device}...")
        _moondream_model = AutoModelForCausalLM.from_pretrained(
            "vikhyatk/moondream2",
            trust_remote_code=True,
            revision="2025-01-09",
            device_map={"": device},
            dtype=dtype,
        ).eval()
        logger.info("Moondream model ready")
    return _moondream_model


async def _describe_image(img_bytes: bytes, question: str) -> str:
    """Describe an image using the local Moondream model."""
    from PIL import Image

    def _run():
        model = _get_moondream()
        image = Image.open(io.BytesIO(img_bytes))
        image_embeds = model.encode_image(image)
        return model.query(image_embeds, question)["answer"]

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        logger.error(f"Moondream error: {e}", exc_info=True)
        return f"Unable to analyze image: {str(e)}"


async def capture_user_camera(params: FunctionCallParams):
    """Capture image from user's camera feed for vision analysis."""
    user_id = params.arguments["user_id"]
    question = params.arguments["question"]
    logger.info(f"Requesting user camera image with user_id={user_id}, question={question}")

    try:
        await params.llm.push_frame(
            UserImageRequestFrame(user_id=user_id, text=question, append_to_context=False),
            FrameDirection.UPSTREAM,
        )
        await params.result_callback("Processing...")
    except Exception as e:
        logger.error(f"Error requesting user camera image: {e}", exc_info=True)
        await params.result_callback(f"Unable to access camera feed: {str(e)}")


async def capture_robot_camera(params: FunctionCallParams):
    """Capture image from TARS' Pi camera and describe using Moondream."""
    import time as _time
    from shared_state import metrics_store, CameraEvent

    question = params.arguments.get("question", "What do you see?")
    _t0 = _time.time()
    metrics_store.add_camera_event(CameraEvent(
        timestamp=_t0, question=question, status="capturing"
    ))

    try:
        from services import tars_robot

        logger.info(f"Capturing robot camera for: {question}")
        result = await tars_robot.capture_camera_view()

        if result.get("status") == "error":
            error = result.get("error", "unknown error")
            logger.warning(f"Robot camera capture failed: {error}")
            metrics_store.add_camera_event(CameraEvent(
                timestamp=_time.time(), question=question, status="error",
                result_preview=error[:80],
            ))
            _notify_display("error", f"Camera unavailable: {error[:50]}")
            await params.result_callback(f"Camera unavailable: {error}")
            return

        img_base64 = result.get("image")
        if not img_base64:
            metrics_store.add_camera_event(CameraEvent(
                timestamp=_time.time(), question=question, status="error",
                result_preview="No image data",
            ))
            _notify_display("error", "Camera returned no image data")
            await params.result_callback("Camera returned no image data.")
            return

        img_bytes = base64.b64decode(img_base64)
        logger.info(f"Camera frame captured ({result.get('width')}x{result.get('height')}), running Moondream...")
        description = await _describe_image(img_bytes, question)
        logger.info(f"Moondream result: {description[:120]}")

        _lat = (_time.time() - _t0) * 1000
        metrics_store.add_camera_event(CameraEvent(
            timestamp=_time.time(), question=question, status="ok",
            result_preview=description[:80], latency_ms=_lat,
        ))
        _notify_display("ok", description[:60], _lat)
        await params.result_callback(description)

    except Exception as e:
        logger.error(f"Robot camera error: {e}", exc_info=True)
        metrics_store.add_camera_event(CameraEvent(
            timestamp=_time.time(), question=question, status="error",
            result_preview=str(e)[:80],
        ))
        _notify_display("error", str(e)[:60])
        await params.result_callback(f"Camera error: {str(e)}")


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
