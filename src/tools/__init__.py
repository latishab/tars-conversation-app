"""LLM callable tools organized by domain."""

from .robot import (
    execute_movement,
    capture_camera_view,
    create_movement_schema,
    create_camera_capture_schema,
)

from .persona import (
    adjust_persona_parameter,
    set_user_identity,
    get_persona_storage,
    create_adjust_persona_schema,
    create_identity_schema,
)

from .vision import (
    fetch_user_image,
    create_fetch_image_schema,
)

from .crossword import (
    get_crossword_hint,
    create_crossword_hint_schema,
)

from .expressions import (
    set_emotion,
    do_gesture,
    create_emotion_schema,
    create_gesture_schema,
    set_rate_limiter,
    ExpressionRateLimiter,
)

__all__ = [
    # Robot tools
    "execute_movement",
    "capture_camera_view",
    "create_movement_schema",
    "create_camera_capture_schema",
    # Persona tools
    "adjust_persona_parameter",
    "set_user_identity",
    "get_persona_storage",
    "create_adjust_persona_schema",
    "create_identity_schema",
    # Vision tools
    "fetch_user_image",
    "create_fetch_image_schema",
    # Crossword tools
    "get_crossword_hint",
    "create_crossword_hint_schema",
    # Expression tools
    "set_emotion",
    "do_gesture",
    "create_emotion_schema",
    "create_gesture_schema",
    "set_rate_limiter",
    "ExpressionRateLimiter",
]
