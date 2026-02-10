"""Persona and identity management tools."""

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from loguru import logger


# Global storage for persona parameters and context
_persona_storage = {
    "persona_params": {},
    "tars_data": {},
    "context_aggregator": None,
    "character_dir": None
}


def get_persona_storage():
    """Get the persona storage dictionary for external access."""
    return _persona_storage


async def adjust_persona_parameter(params: FunctionCallParams):
    """Adjust a persona parameter (0-100). Updates the system prompt dynamically."""
    from character.prompts import build_tars_system_prompt

    parameter_name = params.arguments.get("parameter")
    value = params.arguments.get("value")

    # Validate parameter name
    valid_parameters = [
        "honesty", "humor", "empathy", "curiosity", "confidence", "formality",
        "sarcasm", "adaptability", "discipline", "imagination", "emotional_stability",
        "pragmatism", "optimism", "resourcefulness", "cheerfulness", "engagement",
        "respectfulness", "verbosity"
    ]

    if parameter_name not in valid_parameters:
        await params.result_callback(
            f"Invalid parameter: {parameter_name}. Valid parameters: {', '.join(valid_parameters)}"
        )
        return

    # Validate value (0-100)
    try:
        value_int = int(value)
        if value_int < 0 or value_int > 100:
            await params.result_callback(f"Value must be between 0 and 100. Got: {value_int}")
            return
    except (ValueError, TypeError):
        await params.result_callback(f"Value must be a number between 0 and 100. Got: {value}")
        return

    # Update persona parameters
    persona_params = _persona_storage.get("persona_params", {})
    old_value = persona_params.get(parameter_name, "not set")
    persona_params[parameter_name] = value_int
    _persona_storage["persona_params"] = persona_params

    logger.info(f"Persona parameter adjusted: {parameter_name} = {old_value} → {value_int}%")

    # Update system prompt in LLM context
    context_aggregator = _persona_storage.get("context_aggregator")
    tars_data = _persona_storage.get("tars_data", {})

    if context_aggregator and hasattr(context_aggregator, 'context'):
        try:
            # Rebuild system prompt with updated parameters
            new_system_prompt = build_tars_system_prompt(persona_params, tars_data)

            # Update the first message (system prompt) in the context
            if context_aggregator.context.messages and len(context_aggregator.context.messages) > 0:
                context_aggregator.context.messages[0] = new_system_prompt
                logger.info(f"System prompt updated with new {parameter_name} value")
            else:
                logger.warning("No messages in context to update")
        except Exception as e:
            logger.error(f"Error updating system prompt: {e}", exc_info=True)

    # Provide feedback
    await params.result_callback(
        f"Persona parameter '{parameter_name}' adjusted from {old_value}% to {value_int}%. "
        f"Changes will take effect in subsequent responses."
    )


def set_user_identity(name: str):
    """Called when the user states their name."""
    return {"action": "update_identity", "name": name}


def create_adjust_persona_schema() -> FunctionSchema:
    """Create the adjust_persona_parameter function schema."""
    return FunctionSchema(
        name="adjust_persona_parameter",
        description=(
            "Adjust a personality parameter (0-100%) to change how you respond. "
            "Use this when the user explicitly asks to change your personality traits, "
            "like 'set honesty to 60%', 'make me more empathetic', 'reduce sarcasm', etc. "
            "Available parameters: honesty, humor, empathy, curiosity, confidence, formality, "
            "sarcasm, adaptability, discipline, imagination, emotional_stability, pragmatism, "
            "optimism, resourcefulness, cheerfulness, engagement, respectfulness, verbosity."
        ),
        properties={
            "parameter": {
                "type": "string",
                "enum": [
                    "honesty", "humor", "empathy", "curiosity", "confidence", "formality",
                    "sarcasm", "adaptability", "discipline", "imagination", "emotional_stability",
                    "pragmatism", "optimism", "resourcefulness", "cheerfulness", "engagement",
                    "respectfulness", "verbosity"
                ],
                "description": "The personality parameter to adjust",
            },
            "value": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "The new value for the parameter (0-100%)",
            },
        },
        required=["parameter", "value"],
    )


def create_identity_schema():
    """Create the set_user_identity function schema."""
    return FunctionSchema(
        name="set_user_identity",
        description=(
            "Call this function IMMEDIATELY when the user tells you their name, "
            "OR when they correct/clarify the spelling. "
            "CRITICAL: When user spells out their name (e.g. 'L-A-T-I-S-H-A'), "
            "that is the CORRECT spelling - use it exactly as spelled, not your assumption."
        ),
        properties={
            "name": {
                "type": "string",
                "description": (
                    "The user's name EXACTLY as they spelled it or said it. "
                    "If they spell it out letter-by-letter, reconstruct it carefully. "
                )
            }
        },
        required=["name"],
    )
