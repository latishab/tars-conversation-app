"""LLM callable tools organized by domain."""

from .robot import (
    # Expression and movement
    express,
    execute_movement,
    # Rate limiting
    set_rate_limiter,
    ExpressionRateLimiter,
    # Constants
    VALID_EMOTIONS,
    VALID_INTENSITIES,
    # Schemas
    create_express_schema,
    create_movement_schema,
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
    # Robot tools
    "express",
    "execute_movement",
    "set_rate_limiter",
    "ExpressionRateLimiter",
    "VALID_EMOTIONS",
    "VALID_INTENSITIES",
    "create_express_schema",
    "create_movement_schema",
    # Vision tools
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
