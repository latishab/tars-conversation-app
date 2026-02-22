"""LLM callable tools organized by domain."""

from .robot import (
    # Movement and gestures
    execute_movement,
    set_emotion,
    do_gesture,
    # Rate limiting
    set_rate_limiter,
    ExpressionRateLimiter,
    # Schemas
    create_movement_schema,
    create_emotion_schema,
    create_gesture_schema,
)

from .vision import (
    # Camera capture functions
    capture_user_camera,
    capture_robot_camera,
    # Schemas
    create_user_camera_schema,
    create_robot_camera_schema,
)

from .persona import (
    adjust_persona_parameter,
    set_user_identity,
    get_persona_storage,
    create_adjust_persona_schema,
    create_identity_schema,
)

from .crossword import (
    get_crossword_hint,
    create_crossword_hint_schema,
)

__all__ = [
    # Robot tools (movement and expressions)
    "execute_movement",
    "set_emotion",
    "do_gesture",
    "set_rate_limiter",
    "ExpressionRateLimiter",
    "create_movement_schema",
    "create_emotion_schema",
    "create_gesture_schema",
    # Vision tools (camera capture)
    "capture_user_camera",
    "capture_robot_camera",
    "create_user_camera_schema",
    "create_robot_camera_schema",
    # Persona tools
    "adjust_persona_parameter",
    "set_user_identity",
    "get_persona_storage",
    "create_adjust_persona_schema",
    "create_identity_schema",
    # Crossword tools
    "get_crossword_hint",
    "create_crossword_hint_schema",
]
