"""Robot hardware control tools for LLM.

Tiered expression system:
- Tier 2: Emotions (eyes) - set_emotion(), use freely
- Tier 3-4: Gestures (physical) - do_gesture(), use sparingly
- Tier 5: Displacement - execute_movement(), user request only
"""

import asyncio
import time
from typing import Optional
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams


# =============================================================================
# RATE LIMITING
# =============================================================================

class ExpressionRateLimiter:
    """Rate limiter for expression tools to prevent over-animation."""

    def __init__(
        self,
        min_emotion_interval: float = 5.0,
        min_gesture_interval: float = 30.0,
        max_gestures_per_session: int = 3
    ):
        self.min_emotion_interval = min_emotion_interval
        self.min_gesture_interval = min_gesture_interval
        self.max_gestures_per_session = max_gestures_per_session

        self._last_emotion_time = 0.0
        self._last_gesture_time = 0.0
        self._gesture_count = 0

    def can_set_emotion(self) -> tuple[bool, str]:
        """Check if emotion can be set."""
        now = time.time()
        elapsed = now - self._last_emotion_time

        if elapsed < self.min_emotion_interval:
            remaining = self.min_emotion_interval - elapsed
            return False, f"Emotion change on cooldown ({remaining:.1f}s remaining)"

        return True, ""

    def can_do_gesture(self) -> tuple[bool, str]:
        """Check if gesture can be performed."""
        now = time.time()
        elapsed = now - self._last_gesture_time

        if self._gesture_count >= self.max_gestures_per_session:
            return False, f"Gesture limit reached ({self.max_gestures_per_session} per session)"

        if elapsed < self.min_gesture_interval:
            remaining = self.min_gesture_interval - elapsed
            return False, f"Gesture on cooldown ({remaining:.1f}s remaining)"

        return True, ""

    def record_emotion(self):
        """Record that an emotion was set."""
        self._last_emotion_time = time.time()

    def record_gesture(self):
        """Record that a gesture was performed."""
        self._last_gesture_time = time.time()
        self._gesture_count += 1

    def reset_session(self):
        """Reset session-based counters."""
        self._gesture_count = 0


# Global rate limiter singleton
_rate_limiter: Optional[ExpressionRateLimiter] = None


def set_rate_limiter(limiter: ExpressionRateLimiter):
    """Set the global rate limiter instance."""
    global _rate_limiter
    _rate_limiter = limiter


def get_rate_limiter() -> ExpressionRateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = ExpressionRateLimiter()
    return _rate_limiter


# =============================================================================
# TIER 2: EMOTIONS (Eyes - use freely)
# =============================================================================

async def set_emotion(params: FunctionCallParams):
    """Set TARS emotional expression via DataChannel."""
    emotion = params.arguments.get("emotion", "neutral")
    duration = params.arguments.get("duration", 3.0)

    # Rate limiting
    limiter = get_rate_limiter()
    can_set, reason = limiter.can_set_emotion()
    if not can_set:
        logger.warning(f"Emotion blocked: {reason}")
        await params.result_callback(f"Cannot set emotion: {reason}")
        return

    try:
        from services import tars_robot

        # Validate emotion
        valid_emotions = ["happy", "sad", "surprised", "confused", "curious", "neutral"]
        if emotion not in valid_emotions:
            await params.result_callback(f"Invalid emotion. Valid: {', '.join(valid_emotions)}")
            return

        # Set emotion via gRPC
        result = await tars_robot.set_emotion(emotion)
        limiter.record_emotion()

        logger.info(f"Set emotion: {emotion} for {duration}s")
        await params.result_callback(result)

        # Auto-revert to neutral after duration
        if emotion != "neutral" and duration > 0:
            async def revert_emotion():
                await asyncio.sleep(duration)
                await tars_robot.set_emotion("neutral")
                logger.debug("Emotion reverted to neutral")

            asyncio.create_task(revert_emotion())

    except Exception as e:
        logger.error(f"Emotion error: {e}", exc_info=True)
        await params.result_callback(f"Error setting emotion: {str(e)}")


# =============================================================================
# TIER 3-4: GESTURES (Physical - use sparingly)
# =============================================================================

async def do_gesture(params: FunctionCallParams):
    """Perform a gesture using TARS hardware movements."""
    gesture = params.arguments.get("gesture")

    # Rate limiting
    limiter = get_rate_limiter()
    can_do, reason = limiter.can_do_gesture()
    if not can_do:
        logger.warning(f"Gesture blocked: {reason}")
        await params.result_callback(f"Cannot perform gesture: {reason}")
        return

    try:
        from services import tars_robot

        # Validate gesture
        valid_gestures = [
            "tilt_left", "tilt_right", "bow", "side_side",
            "wave_right", "wave_left", "excited", "laugh"
        ]
        if gesture not in valid_gestures:
            await params.result_callback(f"Invalid gesture. Valid: {', '.join(valid_gestures)}")
            return

        # Map gesture to movement sequence
        gesture_movements = {
            "tilt_left": ["tilt_left"],
            "tilt_right": ["tilt_right"],
            "bow": ["bow"],
            "side_side": ["tilt_left", "tilt_right"],
            "wave_right": ["wave_right"],
            "wave_left": ["wave_left"],
            "excited": ["tilt_left", "tilt_right", "tilt_left", "tilt_right"],
            "laugh": ["tilt_left", "tilt_right", "tilt_left", "tilt_right"],
        }

        movements = gesture_movements.get(gesture, [gesture])
        result = await tars_robot.execute_movement(movements)
        limiter.record_gesture()

        logger.info(f"Performed gesture: {gesture}")
        await params.result_callback(result)

    except Exception as e:
        logger.error(f"Gesture error: {e}", exc_info=True)
        await params.result_callback(f"Error performing gesture: {str(e)}")


# =============================================================================
# TIER 5: DISPLACEMENT (User request only)
# =============================================================================

# Displacement movements that require explicit user request
DISPLACEMENT_MOVEMENTS = {
    "step_forward", "walk_forward", "step_backward", "walk_backward",
    "turn_left", "turn_right", "turn_left_slow", "turn_right_slow"
}


def classify_movements(movements: list[str]) -> tuple[list[str], list[str]]:
    """Classify movements into displacement and safe categories."""
    displacement = [m for m in movements if m in DISPLACEMENT_MOVEMENTS]
    safe = [m for m in movements if m not in DISPLACEMENT_MOVEMENTS]
    return displacement, safe


async def execute_movement(params: FunctionCallParams):
    """Execute physical movement on TARS hardware."""
    movements = params.arguments.get("movements", [])

    if not movements:
        await params.result_callback("No movements specified.")
        return

    # Classify and guard
    displacement, safe = classify_movements(movements)

    if displacement:
        logger.warning(f"Blocked displacement: {displacement}")
        await params.result_callback(
            f"Cannot execute displacement ({', '.join(displacement)}) "
            "unless user explicitly requests. Use do_gesture() instead."
        )
        return

    # Execute safe movements
    if not safe:
        await params.result_callback("No valid movements.")
        return

    try:
        from services import tars_robot

        result = await tars_robot.execute_movement(safe)
        await params.result_callback(result)

    except Exception as e:
        logger.error(f"Movement execution error: {e}", exc_info=True)
        await params.result_callback(f"Error executing movement: {str(e)}")


# =============================================================================
# SCHEMAS
# =============================================================================

def create_emotion_schema() -> FunctionSchema:
    """Create the set_emotion function schema."""
    return FunctionSchema(
        name="set_emotion",
        description=(
            "Set TARS' emotional expression to enhance communication context. "
            "Changes eye appearance and mood. Use sparingly (max once per 5 seconds). "
            "IMPORTANT: Only use when emotion genuinely enhances the conversation - "
            "not for every message. Examples: User shares exciting news → 'happy', "
            "User reports problem → 'curious' or 'confused'. "
            "Available emotions: happy, sad, surprised, confused, curious, neutral."
        ),
        properties={
            "emotion": {
                "type": "string",
                "enum": ["happy", "sad", "surprised", "confused", "curious", "neutral"],
                "description": "The emotion to express"
            },
            "duration": {
                "type": "number",
                "description": "How long to hold emotion before reverting to neutral (seconds)",
                "default": 3.0,
                "minimum": 0,
                "maximum": 10
            }
        },
        required=["emotion"],
    )


def create_gesture_schema() -> FunctionSchema:
    """Create the do_gesture function schema."""
    return FunctionSchema(
        name="do_gesture",
        description=(
            "Perform a physical gesture using TARS hardware. Use VERY sparingly - "
            "0-2 gestures per conversation maximum (3 per session limit). "
            "Rate limited to once per 30 seconds. "
            "IMPORTANT: Use ONLY when user explicitly requests gesture (e.g., 'wave at me') "
            "or when a gesture would significantly enhance communication (greetings, farewells). "
            "Never use for casual acknowledgment. Eyes-first approach preferred. "
            "Available gestures: tilt_left, tilt_right, bow, side_side, "
            "wave_right, wave_left, excited, laugh."
        ),
        properties={
            "gesture": {
                "type": "string",
                "enum": [
                    "tilt_left", "tilt_right", "bow", "side_side",
                    "wave_right", "wave_left", "excited", "laugh"
                ],
                "description": "The gesture to perform"
            }
        },
        required=["gesture"],
    )


def create_movement_schema() -> FunctionSchema:
    """Create the execute_movement function schema."""
    return FunctionSchema(
        name="execute_movement",
        description=(
            "Execute DISPLACEMENT movements on TARS hardware. "
            "IMPORTANT: Use ONLY when user explicitly requests to move TARS' position - "
            "walking, turning, stepping forward/backward. "
            "For gestures (wave, bow, tilt), use do_gesture() instead. "
            "Available displacement movements: "
            "step_forward, walk_forward, step_backward, walk_backward, "
            "turn_left, turn_right, turn_left_slow, turn_right_slow. "
            "Examples: User says 'walk forward' → ['walk_forward'], "
            "User says 'turn around' → ['turn_left', 'turn_left']. "
            "Do NOT use for gestures or expressions."
        ),
        properties={
            "movements": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of displacement movements to execute in sequence",
                "minItems": 1
            }
        },
        required=["movements"],
    )


