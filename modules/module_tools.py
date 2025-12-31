"""LLM function tools and schemas for TARS bot."""

import os
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.frames.frames import UserImageRequestFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import FunctionCallParams

from loguru import logger
from character.prompts import load_persona_ini, load_tars_json, build_tars_system_prompt

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
        await params.result_callback("Processing...")
    except Exception as e:
        logger.error(f"❌ Error requesting image: {e}", exc_info=True)
        # Return error message so LLM can inform user
        await params.result_callback(f"Unable to access camera feed: {str(e)}")

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

def set_user_identity(name: str):
    """
    Called when the user states their name.
    """
    # We return a structured dict. The wrapped handler in bot.py uses the name.
    return {"action": "update_identity", "name": name}

def create_identity_schema():
    return FunctionSchema(
        name="set_user_identity",
        description="Call this function IMMEDIATELY when the user tells you their name.",
        properties={
            "name": {
                "type": "string",
                "description": "The name the user provided."
            }
        },
        required=["name"],
    )