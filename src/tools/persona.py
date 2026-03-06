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

    # Code-level guard: reject 'off' unless recent transcript both addresses TARS
    # directly and contains a termination phrase. Uses ProactiveMonitor's
    # _transcript_buffer (always available) rather than context.messages
    # (which was never stored in persona_storage — previous guard was always skipped).
    # Scan the last 15 seconds of transcript to cover VAD-fragmented utterances.
    if not active and _persona_storage.get("task_mode"):
        monitor_check = _persona_storage.get("proactive_monitor")
        if monitor_check is not None:
            import time as _time
            cutoff = _time.time() - 15.0
            recent_parts = [
                e.get("text", "")
                for e in monitor_check._transcript_buffer
                if e.get("timestamp", 0) >= cutoff
            ]
            text = " ".join(recent_parts).lower()
            addresses_tars = "tars" in text
            task_end_signals = {
                "done", "finished", "finish", "stop", "quit",
                "all done", "that's it", "let's stop", "lets stop",
            }
            has_end_signal = any(signal in text for signal in task_end_signals)
            if not (addresses_tars and has_end_signal):
                logger.warning(
                    f"set_task_mode('off') REJECTED: missing direct address or end signal "
                    f"in recent transcript: '{text[:120]}'"
                )
                await params.result_callback(
                    "Task mode stays active — that didn't sound like you're done."
                )
                return
        else:
            # No monitor available — fail closed: reject the call
            logger.warning("set_task_mode('off') REJECTED: proactive_monitor unavailable")
            await params.result_callback("Task mode stays active.")
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
            logger.debug(f"System prompt length: {len(context.messages[0]['content'])} chars")
            logger.debug(f"CONDITION B present: {'CONDITION B' in context.messages[0]['content']}")
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
            "Call with 'off' ONLY when the user directly addresses TARS AND says they are "
            "completely finished with the ENTIRE task (e.g. 'Tars, I'm done', 'hey Tars, "
            "let's stop', 'Tars, finish crossword mode'). "
            "Both conditions required: direct address ('Tars') + end phrase ('done', "
            "'finished', 'stop', 'quit'). "
            "Do NOT call with 'off' for: solving a clue, self-answers, corrections, or "
            "moving between clues. Think-aloud narration is never a task-end signal."
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
