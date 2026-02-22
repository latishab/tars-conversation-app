"""Robot hardware control tools for LLM.

Expression system:
- express(emotion, intensity): unified eye + gesture control
- execute_movement(): displacement movements on explicit user request
"""

import time
from typing import Optional
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams


# =============================================================================
# EXPRESSION CONSTANTS
# =============================================================================

# Hardware-native states + semantic aliases the LLM can use
VALID_EMOTIONS = [
    # Hardware-native (fallback passes name directly to hardware)
    "neutral", "happy", "sad", "angry", "excited",
    "afraid", "sleepy", "side eye L", "side eye R",
    # Semantic aliases (resolve via ALIAS_TO_EYES)
    "greeting", "farewell", "celebration", "apologetic",
]
VALID_INTENSITIES = ["low", "medium", "high"]

# Maps semantic aliases to their default hardware eye state
ALIAS_TO_EYES = {
    "greeting":    "happy",
    "farewell":    "happy",
    "celebration": "excited",
    "apologetic":  "sad",
    "side eye L":  "sideeye_left",
    "side eye R":  "sideeye_right",
}

# Sparse map: only entries that differ from default (eyes=emotion, gesture=None)
EXPRESSION_MAP = {
    ("happy",        "high"):    {"eyes": "happy",    "gesture": "side_side"},
    ("sad",          "high"):    {"eyes": "sad",       "gesture": "bow"},
    ("angry",        "high"):    {"eyes": "angry",     "gesture": "side_side"},
    ("excited",      "medium"):  {"eyes": "excited",   "gesture": "side_side"},
    ("excited",      "high"):    {"eyes": "excited",   "gesture": "excited"},
    ("afraid",       "high"):    {"eyes": "afraid",    "gesture": "side_side"},
    ("greeting",     "high"):    {"eyes": "happy",     "gesture": "wave_right"},
    ("farewell",     "high"):    {"eyes": "happy",     "gesture": "bow"},
    ("celebration",  "medium"):  {"eyes": "excited",   "gesture": "side_side"},
    ("celebration",  "high"):    {"eyes": "excited",   "gesture": "excited"},
    ("apologetic",   "high"):    {"eyes": "sad",       "gesture": "bow"},
}

# Gesture name → movement sequence
GESTURE_MOVEMENTS = {
    "bow":        ["bow"],
    "side_side":  ["tilt_left", "tilt_right"],
    "wave_right": ["wave_right"],
    "excited":    ["tilt_left", "tilt_right", "tilt_left", "tilt_right"],
}


def get_expression(emotion: str, intensity: str) -> dict:
    """Resolve expression mapping with fallback."""
    mapping = EXPRESSION_MAP.get((emotion, intensity))
    if mapping:
        return mapping
    eyes = ALIAS_TO_EYES.get(emotion, emotion)
    return {"eyes": eyes, "gesture": None}


# =============================================================================
# RATE LIMITING
# =============================================================================

class ExpressionRateLimiter:
    """Rate limiter for express() tool based on intensity level."""

    def __init__(
        self,
        min_expression_interval: float = 2.0,
        min_gesture_interval: float = 15.0,
        max_medium_per_session: int = 5,
        max_high_per_session: int = 2,
    ):
        self.min_expression_interval = min_expression_interval
        self.min_gesture_interval = min_gesture_interval
        self.max_medium_per_session = max_medium_per_session
        self.max_high_per_session = max_high_per_session
        self._last_expression_time = 0.0
        self._last_gesture_time = 0.0
        self._medium_count = 0
        self._high_count = 0

    def can_express(self, intensity: str) -> tuple[bool, str]:
        now = time.time()
        if now - self._last_expression_time < self.min_expression_interval:
            return False, "Too soon after last expression"
        if intensity == "low":
            return True, ""
        if intensity == "medium":
            if now - self._last_gesture_time < self.min_gesture_interval:
                return False, "Gesture on cooldown"
            if self._medium_count >= self.max_medium_per_session:
                return False, "Medium intensity session limit reached"
            return True, ""
        if intensity == "high":
            if now - self._last_gesture_time < self.min_gesture_interval * 2:
                return False, "Gesture on cooldown for high intensity"
            if self._high_count >= self.max_high_per_session:
                return False, "High intensity session limit reached"
            return True, ""
        return False, "Unknown intensity"

    def record_expression(self, intensity: str, had_gesture: bool) -> None:
        now = time.time()
        self._last_expression_time = now
        if had_gesture:
            self._last_gesture_time = now
        if intensity == "medium":
            self._medium_count += 1
        elif intensity == "high":
            self._high_count += 1

    def reset_session(self) -> None:
        self._medium_count = 0
        self._high_count = 0


# Global rate limiter singleton
_rate_limiter: Optional[ExpressionRateLimiter] = None


def set_rate_limiter(limiter: ExpressionRateLimiter):
    global _rate_limiter
    _rate_limiter = limiter


def get_rate_limiter() -> ExpressionRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = ExpressionRateLimiter()
    return _rate_limiter


# =============================================================================
# EXPRESSION TOOL
# =============================================================================

async def express(params: FunctionCallParams):
    """Unified expression tool: sets eyes and optionally triggers a gesture."""
    emotion = params.arguments.get("emotion", "neutral")
    intensity = params.arguments.get("intensity", "low")

    # Validate inputs; fall back to safe defaults
    if emotion not in VALID_EMOTIONS:
        logger.warning(f"Invalid emotion '{emotion}', falling back to neutral")
        emotion = "neutral"
    if intensity not in VALID_INTENSITIES:
        logger.warning(f"Invalid intensity '{intensity}', falling back to low")
        intensity = "low"

    limiter = get_rate_limiter()
    can_do, reason = limiter.can_express(intensity)
    if not can_do:
        # Downgrade to low (eyes only) rather than blocking entirely
        logger.warning(f"Expression downgraded to low: {reason}")
        intensity = "low"

    mapping = get_expression(emotion, intensity)
    eyes_state = mapping["eyes"]
    gesture = mapping["gesture"]

    try:
        from services import tars_robot

        result = await tars_robot.set_emotion(eyes_state)
        logger.info(f"express: emotion={emotion} intensity={intensity} eyes={eyes_state} gesture={gesture}")

        had_gesture = False
        if gesture and intensity in ("medium", "high"):
            movements = GESTURE_MOVEMENTS.get(gesture, [gesture])
            await tars_robot.execute_movement(movements)
            had_gesture = True

        limiter.record_expression(intensity, had_gesture)
        await params.result_callback(result)

    except Exception as e:
        logger.error(f"express error: {e}", exc_info=True)
        await params.result_callback(f"Error: {str(e)}")


# =============================================================================
# DISPLACEMENT TOOL
# =============================================================================

# For schema documentation only — no runtime guard
DISPLACEMENT_MOVEMENTS = {
    "step_forward", "walk_forward", "step_backward", "walk_backward",
    "turn_left", "turn_right", "turn_left_slow", "turn_right_slow"
}


async def execute_movement(params: FunctionCallParams):
    """Execute physical displacement movement on TARS hardware."""
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


# =============================================================================
# SCHEMAS
# =============================================================================

def create_express_schema() -> FunctionSchema:
    """Create the express function schema."""
    return FunctionSchema(
        name="express",
        description=(
            "Convey an emotional response during conversation. "
            "Intensity controls which hardware channels activate: "
            "low = eyes only (default, no servo wear); "
            "medium = eyes + subtle gesture (use for notable moments); "
            "high = eyes + expressive gesture (use rarely, strong reactions). "
            "Valid emotions: neutral, happy, sad, angry, excited, afraid, sleepy, "
            "side eye L, side eye R, greeting, farewell, celebration, apologetic. "
            "Default to low. Do not express on every message. "
            "High intensity at most once per conversation."
        ),
        properties={
            "emotion": {
                "type": "string",
                "enum": VALID_EMOTIONS,
                "description": "The emotion to express"
            },
            "intensity": {
                "type": "string",
                "enum": VALID_INTENSITIES,
                "description": "Expression intensity: low (eyes only), medium (eyes + subtle gesture), high (eyes + expressive gesture)",
                "default": "low"
            }
        },
        required=["emotion"],
    )


def create_movement_schema() -> FunctionSchema:
    """Create the execute_movement function schema."""
    return FunctionSchema(
        name="execute_movement",
        description=(
            "Execute DISPLACEMENT movements on TARS hardware. "
            "Use ONLY when user explicitly requests to move TARS' position — "
            "walking, turning, stepping forward/backward. "
            "Available: step_forward, walk_forward, step_backward, walk_backward, "
            "turn_left, turn_right, turn_left_slow, turn_right_slow. "
            "Examples: User says 'walk forward' → ['walk_forward'], "
            "User says 'turn around' → ['turn_left', 'turn_left']. "
            "Do NOT use for expressions — use express() instead."
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
