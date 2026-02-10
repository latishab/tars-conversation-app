"""
TARS Robot Service - gRPC-based hardware control

Provides LLM tools and helper functions for controlling TARS robot via gRPC.
Replaces HTTP REST-based tars_client.py with low-latency gRPC SDK.
"""

import base64
from typing import Dict, Any, List, Optional
from loguru import logger

# Import TARS SDK
import sys
from pathlib import Path

# Add tars repo to path to import SDK
tars_repo = Path(__file__).parent.parent.parent.parent / "tars"
if tars_repo.exists():
    sys.path.insert(0, str(tars_repo))

try:
    from tars_sdk import TarsClient
    TARS_SDK_AVAILABLE = True
except ImportError:
    TARS_SDK_AVAILABLE = False
    logger.warning("TARS SDK not available - install with: pip install -e ../tars")


# Singleton client
_client: Optional[TarsClient] = None


def get_robot_client(address: Optional[str] = None) -> Optional[TarsClient]:
    """
    Get singleton TARS robot client.

    Args:
        address: gRPC server address (e.g., "100.64.0.2:50051")
                 If None, uses TARS_GRPC_ADDRESS env var or localhost:50051

    Returns:
        TarsClient instance or None if SDK not available
    """
    global _client

    if not TARS_SDK_AVAILABLE:
        logger.warning("TARS SDK not available")
        return None

    if _client is None:
        _client = TarsClient(address=address)
        logger.info(f"Connected to TARS robot via gRPC at {_client.address}")

    return _client


def close_robot_client():
    """Close the robot client connection."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


# ============== LLM Tool Functions ==============


async def execute_movement(movements: List[str]) -> str:
    """
    LLM tool: Execute movement sequence on TARS robot.

    Args:
        movements: List of movements to execute
                   Valid: step_forward, walk_forward, step_backward, walk_backward,
                         turn_left, turn_right, turn_left_slow, turn_right_slow,
                         wave_left, wave_right, bow, tilt_left, tilt_right, etc.

    Returns:
        Human-readable result string
    """
    client = get_robot_client()
    if client is None:
        return "TARS robot not available. Cannot execute movements."

    try:
        results = []
        for movement in movements:
            result = client.move(movement)
            if result["success"]:
                results.append(f"{movement} (took {result['duration']:.2f}s)")
            else:
                results.append(f"{movement} FAILED: {result['error']}")
                logger.error(f"Movement '{movement}' failed: {result['error']}")

        if all("FAILED" not in r for r in results):
            logger.info(f"Movements executed: {', '.join(movements)}")
            return f"Successfully executed: {', '.join(results)}"
        else:
            return f"Movements completed with errors: {', '.join(results)}"

    except Exception as e:
        error_msg = f"Movement execution error: {str(e)}"
        logger.error(error_msg)
        return error_msg


async def capture_camera_view() -> Dict[str, Any]:
    """
    LLM tool: Capture image from robot's camera.

    Returns:
        Dict with:
        - status: "ok" or "error"
        - image: base64-encoded JPEG
        - width, height: Image dimensions
        - format: "jpeg"
    """
    client = get_robot_client()
    if client is None:
        return {
            "status": "error",
            "error": "TARS robot not available"
        }

    try:
        # Capture frame via gRPC
        jpeg_bytes = client.capture_camera(width=640, height=480, quality=80)

        if jpeg_bytes:
            # Encode to base64 for consistency with old API
            img_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')

            logger.info(f"Captured camera frame: {len(jpeg_bytes)} bytes")

            return {
                "status": "ok",
                "image": img_base64,
                "width": 640,
                "height": 480,
                "format": "jpeg"
            }
        else:
            return {
                "status": "error",
                "error": "Failed to capture frame"
            }

    except Exception as e:
        error_msg = f"Camera capture error: {str(e)}"
        logger.error(error_msg)
        return {
            "status": "error",
            "error": error_msg
        }


# ============== Helper Functions ==============


def set_emotion(emotion: str):
    """
    Set robot facial emotion.

    Args:
        emotion: Emotion name ("happy", "sad", "angry", "surprised", "neutral")
    """
    client = get_robot_client()
    if client is None:
        logger.warning("Cannot set emotion - robot not available")
        return

    try:
        client.set_emotion(emotion)
        logger.debug(f"Emotion set to: {emotion}")
    except Exception as e:
        logger.error(f"Set emotion error: {e}")


def set_eye_state(state: str):
    """
    Set robot eye state.

    Args:
        state: Eye state ("idle", "listening", "thinking", "speaking")
    """
    client = get_robot_client()
    if client is None:
        logger.warning("Cannot set eye state - robot not available")
        return

    try:
        client.set_eye_state(state)
        logger.debug(f"Eye state set to: {state}")
    except Exception as e:
        logger.error(f"Set eye state error: {e}")


def get_robot_status() -> Optional[Dict[str, Any]]:
    """
    Get current robot status.

    Returns:
        Dict with battery, emotion, eye_state, movement status, or None if unavailable
    """
    client = get_robot_client()
    if client is None:
        return None

    try:
        status = client.get_status()
        return status
    except Exception as e:
        logger.error(f"Get status error: {e}")
        return None


def reset_robot():
    """Reset robot to neutral position."""
    client = get_robot_client()
    if client is None:
        logger.warning("Cannot reset - robot not available")
        return

    try:
        client.reset()
        logger.info("Robot reset to neutral position")
    except Exception as e:
        logger.error(f"Reset error: {e}")


def is_robot_available() -> bool:
    """Check if robot is available."""
    client = get_robot_client()
    if client is None:
        return False

    try:
        status = client.get_status()
        return status.get("connected", False)
    except Exception as e:
        logger.debug(f"Robot availability check failed: {e}")
        return False
