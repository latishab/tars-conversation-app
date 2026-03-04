"""Persona and identity management tools."""

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.llm_service import FunctionCallParams
from loguru import logger


# Global storage for persona parameters and context
_persona_storage = {
    "persona_params": {},
    "tars_data": {},
    "context_aggregator": None,
    "character_dir": None,
    "proactive_monitor": None,
    "task_mode": None,
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
    tars_data = _persona_storage.get("tars_data", {})
    context = _persona_storage.get("context")
    task_mode = _persona_storage.get("task_mode")

    if context and context.messages:
        try:
            new_system_prompt = build_tars_system_prompt(persona_params, tars_data, task_mode=task_mode)
            context.messages[0] = new_system_prompt
            logger.info(f"System prompt updated with new {parameter_name} value")
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


async def set_task_mode(params: FunctionCallParams):
    """Toggle task mode on/off. Adjusts system prompt and proactive monitor."""
    from character.prompts import build_tars_system_prompt

    mode = (params.arguments.get("mode") or "").strip().lower()
    active = mode not in ("", "off", "none", "disable", "disabled")
    mode_value = mode if active else None

    # Code-level guard: reject 'off' if last user utterance is too short or filler-only.
    # Prompt rules alone are insufficient — this is deterministic and cannot be bypassed by the LLM.
    if not active and _persona_storage.get("task_mode"):
        context = _persona_storage.get("context")
        if context and context.messages:
            last_user = None
            for m in reversed(context.messages):
                if m.get("role") == "user":
                    last_user = m.get("content", "").strip()
                    break
            if last_user:
                words = last_user.lower().split()
                filler_words = {"um", "uh", "hmm", "okay", "ok", "i", "well",
                                "ugh", "oh", "ah", "er", "like", "so", "and"}
                is_short = len(words) <= 4
                is_filler_only = all(w.strip(".,!?") in filler_words for w in words)
                if is_short or is_filler_only:
                    logger.warning(
                        f"set_task_mode('off') REJECTED: last utterance too short "
                        f"or filler-only: '{last_user}'"
                    )
                    await params.result_callback(
                        "Task mode stays active — that didn't sound like you're done."
                    )
                    return

    monitor = _persona_storage.get("proactive_monitor")
    if monitor:
        monitor.set_task_mode(mode_value)

    _persona_storage["task_mode"] = mode_value

    persona_params = _persona_storage.get("persona_params", {})
    tars_data = _persona_storage.get("tars_data", {})
    context = _persona_storage.get("context")

    if context and context.messages:
        try:
            new_system_prompt = build_tars_system_prompt(
                persona_params, tars_data, task_mode=mode_value
            )
            context.messages[0] = new_system_prompt
            logger.info(f"System prompt updated: task_mode={mode_value}")
        except Exception as e:
            logger.error(f"Error updating system prompt for task mode: {e}")

    label = mode if active else "off"
    logger.info(f"Task mode set: {label}")
    await params.result_callback(f"Task mode: {label}.")


def create_task_mode_schema() -> FunctionSchema:
    return FunctionSchema(
        name="set_task_mode",
        description=(
            "Toggle task mode when the user starts or stops a focused activity. "
            "Call with a mode like 'crossword', 'coding', 'reading', 'thinking' "
            "when the user announces they're working on something. "
            "Call with 'off' ONLY when the user explicitly says they are completely finished "
            "with the ENTIRE task (e.g. 'I'm done with the crossword', 'let's stop', "
            "'I'm all done'). "
            "Do NOT call with 'off' for: solving a clue ('okay evening', 'I got it', "
            "'moving on'), corrections ('you shouldn't answer', 'stop helping'), "
            "or moving between clues. Those keep task mode active. "
            "Do NOT call with 'off' if the user's last utterance is 4 words or fewer "
            "or consists only of filler words (um, uh, hmm, okay, I, well, oh). "
            "Short fragments are never a task-end signal."
        ),
        properties={
            "mode": {
                "type": "string",
                "description": (
                    "The task type (e.g. 'crossword', 'coding', 'reading', 'thinking') "
                    "or 'off' to exit task mode."
                ),
            },
        },
        required=["mode"],
    )
