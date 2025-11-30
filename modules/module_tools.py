"""LLM function tools and schemas for TARS bot."""

import os
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import UserImageRequestFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from loguru import logger
from character.prompts import load_persona_ini, load_tars_json, build_tars_system_prompt

# Global storage for TTS speed setting (shared across function calls)
_tts_speed_storage = {"speed": 1.0, "tts_service": None}

# Global storage for persona parameters and context
_persona_storage = {
    "persona_params": {},
    "tars_data": {},
    "context_aggregator": None,
    "character_dir": None
}


async def fetch_user_image(params: FunctionCallParams):
    """Fetch user image for vision analysis."""
    user_id = params.arguments["user_id"]
    question = params.arguments["question"]
    logger.info(f"📸 Requesting image with user_id={user_id}, question={question}")

    try:
        # Request image frame (processed by Moondream, not added to context)
        await params.llm.push_frame(
            UserImageRequestFrame(user_id=user_id, text=question, append_to_context=False),
            FrameDirection.UPSTREAM,
        )
        logger.debug("✓ UserImageRequestFrame sent to pipeline")
        
        # Return a minimal status - the LLM should wait for the vision result
        # Moondream will process in the background and send results when ready
        # We return a minimal message to avoid triggering an immediate LLM response
        await params.result_callback("Processing...")
    except Exception as e:
        logger.error(f"❌ Error requesting image: {e}", exc_info=True)
        # Return error message so LLM can inform user
        await params.result_callback(f"Unable to access camera feed: {str(e)}")


async def set_speaking_rate(params: FunctionCallParams):
    """Adjust speaking speed: fast (1.2x) for urgent, slow (0.8x) for complex, normal (1.0x) default."""
    rate = params.arguments.get("rate", "normal")
    speed_value = 1.0
    
    if rate == "fast":
        speed_value = 1.2  # Max reliable speed for urgent situations
        logger.info("⚡ TARS engaging High-Speed Mode (1.2x)")
    elif rate == "slow":
        speed_value = 0.8  # Slower, more deliberate for complex topics
        logger.info("🐢 TARS engaging Precision Mode (0.8x)")
    else:
        speed_value = 1.0
        logger.info("✓ TARS speaking at Normal Speed (1.0x)")
    
    _tts_speed_storage["speed"] = speed_value
    
    # Update TTS service if available
    tts_service = _tts_speed_storage.get("tts_service")
    if tts_service:
        try:
            if hasattr(tts_service, 'speed'):
                tts_service.speed = speed_value
            elif hasattr(tts_service, '_speed'):
                tts_service._speed = speed_value
        except Exception as e:
            logger.debug(f"Could not update TTS speed: {e}")
    
    await params.result_callback(f"Speaking rate set to {rate} ({speed_value}x speed)")


def get_tts_speed_storage():
    """Get the TTS speed storage dictionary for external access."""
    return _tts_speed_storage


def get_persona_storage():
    """Get the persona storage dictionary for external access."""
    return _persona_storage


async def adjust_persona_parameter(params: FunctionCallParams):
    """Adjust a persona parameter (0-100). Updates the system prompt dynamically."""
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
    
    logger.info(f"🔧 Persona parameter adjusted: {parameter_name} = {old_value} → {value_int}%")
    
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
                logger.info(f"✓ System prompt updated with new {parameter_name} value")
            else:
                logger.warning("No messages in context to update")
        except Exception as e:
            logger.error(f"Error updating system prompt: {e}", exc_info=True)
    
    # Provide feedback
    await params.result_callback(
        f"Persona parameter '{parameter_name}' adjusted from {old_value}% to {value_int}%. "
        f"Changes will take effect in subsequent responses."
    )


def create_fetch_image_schema() -> FunctionSchema:
    """Create the fetch_user_image function schema."""
    return FunctionSchema(
        name="fetch_user_image",
        description=(
            "ONLY call this function when the user EXPLICITLY asks about what they are SHOWING on camera, "
            "what is VISIBLE in their camera feed, or asks you to LOOK at or DESCRIBE what's on screen. "
            "DO NOT call this for questions about memory, recall, conversation history, or anything that "
            "doesn't require visual analysis of the current camera feed. Examples: 'What do you see?', "
            "'Describe what's on my camera', 'What am I showing you?', 'Can you see this?'. "
            "Counter-examples (DO NOT call): 'Do you remember my name?', 'What did I tell you?', "
            "'What's my favorite color?' (unless they're showing it on camera). "
            "IMPORTANT: After calling this function, DO NOT generate an immediate acknowledgment message. "
            "Wait silently for the vision analysis result to arrive - it will be provided automatically. "
            "Once you receive the vision result, respond directly with what you see. Do not say 'analyzing' "
            "or 'please hold' - just wait for the result and then describe what you see."
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


def create_speaking_rate_schema() -> FunctionSchema:
    """Create the set_speaking_rate function schema."""
    return FunctionSchema(
        name="set_speaking_rate",
        description="Adjusts your speaking speed to match the user's energy and urgency. Use 'fast' if the user is urgent/panicked, 'slow' for complex topics or when the user is confused, 'normal' for default operation.",
        properties={
            "rate": {
                "type": "string",
                "enum": ["fast", "normal", "slow"],
                "description": "The desired speaking rate: 'fast' (1.2x) for urgent situations, 'slow' (0.8x) for complex explanations, 'normal' (1.0x) for default.",
            },
        },
        required=["rate"],
    )


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

