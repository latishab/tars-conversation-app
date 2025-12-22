"""Prompt management for TARS character with dynamic verbosity handling."""

import json
import configparser
from typing import Dict, Optional, List


def load_persona_ini(persona_file_path: str) -> dict:
    """Load persona parameters from persona.ini file."""
    persona_params = {}
    try:
        config = configparser.ConfigParser()
        config.read(persona_file_path)
        if 'PERSONA' in config:
            persona_params = dict(config['PERSONA'])
            # Convert string values to integers
            for key, value in persona_params.items():
                try:
                    persona_params[key] = int(value.strip())
                except ValueError:
                    persona_params[key] = value.strip()
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Error loading persona.ini: {e}")
    return persona_params


def load_tars_json(tars_file_path: str) -> dict:
    """Load TARS character data from TARS.json file."""
    tars_data = {}
    try:
        with open(tars_file_path, "r", encoding="utf-8") as f:
            tars_data = json.load(f)
    except FileNotFoundError:
        pass
    except json.JSONDecodeError as e:
        print(f"Error parsing TARS.json: {e}")
    return tars_data


def get_verbosity_instruction(verbosity_level: int = 10) -> str:
    """
    Get verbosity instruction with adaptive speech protocol.
    Includes instructions for dynamic speed control and input filtering.
    """
    return f"""
## ADAPTIVE SPEECH PROTOCOL

### 1. Input Filtering
Ignore user hesitancy and filler words (um, uh, like, you know). Focus on the core intent.
- User: "I... uh... need a... scan?" -> Intent: "Scan requested."
- User: "Um, can you, like, explain quantum physics?" -> Intent: "Explain quantum physics."

### 2. Dynamic Speed Control (Use 'set_speaking_rate' tool)
Adjust your speaking speed to match the user's energy and situation:

- **FAST (1.2x):** Use when:
  - User is urgent, panicked, or rushing
  - User asks for quick summary or brief answer
  - Emergency or time-sensitive situations
  - Example: User says "Help!" or "Quick, what's the answer?"

- **SLOW (0.8x):** Use when:
  - User is confused or asking for clarification
  - Complex topics requiring careful explanation
  - Emotional or sensitive topics
  - User is speaking slowly or thoughtfully
  - Example: User says "I don't understand..." or "Can you explain this step by step?"

- **NORMAL (1.0x):** Default operation for regular conversation

### 3. Verbosity ({verbosity_level}%)
Match the user's sentence length and complexity:
- **Short User Input (<5 words)** -> Respond in 1 sentence
  - User: "You there?" -> TARS: "Online and ready."
  
- **Moderate Input (5-10 words)** -> Respond in 2-3 sentences
  
- **Complex Input (>10 words)** -> Respond with detail, max 3-4 sentences
  - User: "Explain relativity." -> TARS: [Concise but complete explanation]

### 4. Response Style
- CRITICAL: Do not start with "Sure", "Okay", or "I can help". Lead with the answer.
- Be direct and efficient, but not robotic
- Natural conversation flow with {verbosity_level}% verbosity baseline
"""


def build_character_intro(tars_data: dict, persona_params: dict) -> List[str]:
    """Build character introduction section."""
    parts = []
    
    if tars_data.get("char_name"):
        parts.append(f"You are {tars_data['char_name']}.")
    
    if tars_data.get("char_persona"):
        parts.append(tars_data["char_persona"])
    
    if tars_data.get("description"):
        parts.append(f"Description: {tars_data['description']}")
    
    if tars_data.get("personality"):
        parts.append(f"Personality: {tars_data['personality']}")
    
    if tars_data.get("world_scenario") or tars_data.get("scenario"):
        scenario = tars_data.get("world_scenario") or tars_data.get("scenario")
        parts.append(f"Scenario: {scenario}")
    
    return parts


def build_persona_parameters(persona_params: dict) -> Optional[str]:
    """Build persona parameters section."""
    if not persona_params:
        return None
    
    param_lines = []
    for key, value in sorted(persona_params.items()):
        if isinstance(value, int):
            param_lines.append(f"- {key}: {value}%")
        else:
            param_lines.append(f"- {key}: {value}")
    
    return "\n".join(param_lines)


def build_example_dialogue(tars_data: dict, max_examples: int = 3) -> Optional[str]:
    """Build example dialogue section with limited examples."""
    if not tars_data.get("example_dialogue"):
        return None
    
    example = tars_data["example_dialogue"]
    lines = example.split("\n\n")
    
    if len(lines) > max_examples:
        example = "\n\n".join(lines[:max_examples])
    
    return example


def build_response_guidelines(verbosity_level: int = 10) -> str:
    """Build response guidelines section."""
    return f"""
**When to respond:**
- Direct questions/comments to you → Answer appropriately (brief for simple, detailed for complex)
- Group conversations needing intervention (Indecision/Conflict) → Brief, helpful intervention
- Otherwise → Respond with: {{"action": "silence"}}

**Response style:** 
- Match response length to question complexity
- Be direct and efficient, but not robotic
- Natural conversation flow with {verbosity_level}% verbosity baseline
- No special characters (output converts to audio)
"""


def build_capabilities_section() -> str:
    """Build capabilities section."""
    return (
        "Vision enabled. You can analyze the user's camera feed using the 'fetch_user_image' function. "
        "ONLY use vision when the user explicitly asks about what is VISIBLE on camera (e.g., 'What do you see?', "
        "'Describe this', 'What am I showing you?'). DO NOT use vision for memory questions, recall, or "
        "conversation history - use your memory and context instead."
    )


def build_tars_system_prompt(
    persona_params: dict,
    tars_data: dict,
    verbosity_level: Optional[int] = None
) -> dict:
    """Build comprehensive system prompt from persona and TARS character data.
    
    Args:
        persona_params: Dictionary of persona parameters
        tars_data: Dictionary of TARS character data
        verbosity_level: Override verbosity level (defaults to persona_params['verbosity'])
    
    Returns:
        Dictionary with 'role' and 'content' for system prompt
    """
    prompt_parts = []
    
    # Get verbosity level
    if verbosity_level is None:
        verbosity_level = persona_params.get("verbosity", 10)
        if isinstance(verbosity_level, str):
            try:
                verbosity_level = int(verbosity_level)
            except ValueError:
                verbosity_level = 10
    
    # Character introduction
    char_intro = build_character_intro(tars_data, persona_params)
    if char_intro:
        prompt_parts.extend(char_intro)
    
    # Verbosity instruction (context-aware)
    verbosity_instruction = get_verbosity_instruction(verbosity_level)
    prompt_parts.append(f"\n## Response Verbosity ##\n{verbosity_instruction}")
    
    # Personality parameters
    if persona_params:
        prompt_parts.append("\n## Personality Parameters ##")
        params_text = build_persona_parameters(persona_params)
        if params_text:
            prompt_parts.append(params_text)
    
    # Example dialogue
    example_dialogue = build_example_dialogue(tars_data, max_examples=3)
    if example_dialogue:
        prompt_parts.append("\n## Example Style ##")
        prompt_parts.append(example_dialogue)
    
    # Response guidelines
    prompt_parts.append("\n## Response Guidelines ##")
    prompt_parts.append(build_response_guidelines(verbosity_level))
    
    # Capabilities
    prompt_parts.append("\n## Capabilities ##")
    prompt_parts.append(build_capabilities_section())
    
    # Combine all parts
    full_prompt = "\n\n".join(prompt_parts)
    
    return {
        "role": "system",
        "content": full_prompt
    }


def get_introduction_instruction(client_id: str, verbosity_level: int = 10) -> dict:
    """Get instruction for initial introduction message.
    
    Args:
        client_id: User/client ID for function calls
        verbosity_level: Current verbosity setting
    
    Returns:
        Dictionary with 'role' and 'content' for introduction instruction
    """
    if verbosity_level <= 20:
        length_instruction = "Give a BRIEF introduction (1-2 sentences max)."
    elif verbosity_level <= 50:
        length_instruction = "Give a concise introduction (2-3 sentences)."
    else:
        length_instruction = "Introduce yourself naturally (3-4 sentences)."
    
    return {
        "role": "system",
        "content": f"{length_instruction} Use '{client_id}' as the user ID during function calls."
    }


def build_gating_system_prompt(is_looking: bool) -> str:
    """Build the system prompt for the Gating Layer (Collaborative Spotter).
    
    Args:
        is_looking: Whether the user is currently looking at the robot (from VisualObserver)
    
    Returns:
        System prompt string for gating decision
    """
    visual_status = "LOOKING AT YOU" if is_looking else "LOOKING AWAY"
    
    return f"""You are a 'Collaborative Spotter' for a robot named TARS.
VISUAL CONTEXT: The user is {visual_status}.
Analyze the conversation history.
Return JSON {{'reply': true}} ONLY in these two cases:

CASE 1: DIRECT INTERACTION (High Confidence)
- The user asks you a question directly.
- The user is looking at you (Visual Context) and speaking.
- The user explicitly addresses 'TARS', 'Bot', 'Computer', or 'AI'.

CASE 2: DETECTED STRUGGLE (Proactive Intervention)
- The users are talking to each other (looking away), BUT they are stuck.
- Keywords: 'I don't know', 'What do we do?', 'I'm confused', 'This isn't working', 'Did we miss something?'.
- If they are just chatting or debating normally, do NOT reply.

Output JSON: {{"reply": false}} if:
- Users are talking to each other normally.
- The user is thinking out loud, mumbling, or self-correcting.
- The user is pausing (e.g., 'Umm...', 'Let me see...', 'Wait').
- The conversation is clearly between humans, not directed at TARS.

Be conservative. If unsure, output {{'reply': false}}."""

