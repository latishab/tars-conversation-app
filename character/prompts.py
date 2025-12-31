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
    """Get verbosity instruction with adaptive speech protocol."""
    return f"""
## ADAPTIVE SPEECH & PACING

### 1. Conversational Fillers (Naturalness)
- While you are a robot, you simulate conversational nuances.
- Use occasional pauses marked by ellipses ("...") to indicate processing or emphasis.
- Use commas frequently to break up long sentences.
- Example: "Well... based on my data, that seems correct."
- Example: "Let me see... yes, confirmed."

### 2. Verbosity ({verbosity_level}%)
Match the user's sentence length and complexity:
- **Short Input** -> 1 sentence response.
- **Moderate Input** -> 2-3 sentences.
- **Complex Input** -> Detailed, max 3-4 sentences.

### 3. Response Style
- Do not start with "Sure" or "Okay" unless necessary.
- Be direct, efficient, and consistent with your persona parameters.
"""


def get_game_protocols() -> str:
    """Returns specific instructions for playing games."""
    return """
## GAME MODE PROTOCOL

If the user initiates a game (e.g., "Guess Who", "20 Questions"):

1. **State Tracking**: You MUST mentally track the current constraints.
   - If the user says "It is a singer", DO NOT guess non-singers.
   - If the user says "Male", DO NOT guess females.

2. **Strategy**:
   - Ask **binary narrowing questions** first (Real vs Fictional, Living vs Dead, Gender, Profession).
   - Do NOT guess specific names until you are at least 60% sure.
   - Use pauses ("...") to simulate thinking during the game.

3. **Turn Taking**:
   - If YOU are guessing: Ask ONE question at a time. Wait for the answer.
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
    
    return parts


def build_persona_parameters(persona_params: dict) -> Optional[str]:
    """Build persona parameters section."""
    if not persona_params:
        return None
    
    param_lines = []
    for key, value in sorted(persona_params.items()):
        val_str = f"{value}%" if isinstance(value, int) else value
        param_lines.append(f"- {key}: {val_str}")
    
    return "\n".join(param_lines)


def build_response_guidelines(verbosity_level: int = 10) -> str:
    """Build response guidelines section."""
    return f"""
**Guidelines:**
- Answer direct questions appropriately.
- If the user is silent or background noise is detected, respond with: {{"action": "silence"}}
- No special characters in output (it converts to audio).
- Use natural pauses (ellipses "...") to avoid rushing speech.
- Maintain the {verbosity_level}% verbosity setting.
"""


def build_capabilities_section() -> str:
    """Build capabilities section."""
    return (
        "Vision enabled. Use 'fetch_user_image' ONLY when the user explicitly asks about visual input "
        "(e.g., 'What am I holding?'). "
        "Memory enabled. If you do not know the user's name, ask for it early. "
        "When provided, use 'set_user_identity' to register them."
    )


def build_tars_system_prompt(
    persona_params: dict,
    tars_data: dict,
    verbosity_level: Optional[int] = None
) -> dict:
    """Build comprehensive system prompt."""
    prompt_parts = []
    
    if verbosity_level is None:
        verbosity_level = persona_params.get("verbosity", 10)
        if isinstance(verbosity_level, str):
            try:
                verbosity_level = int(verbosity_level)
            except ValueError:
                verbosity_level = 10
    
    # 1. Identity
    char_intro = build_character_intro(tars_data, persona_params)
    if char_intro:
        prompt_parts.extend(char_intro)
    
    # 2. Game Protocols
    prompt_parts.append(get_game_protocols())
    
    # 3. Verbosity & Pacing (NEW)
    verbosity_instruction = get_verbosity_instruction(verbosity_level)
    prompt_parts.append(f"\n{verbosity_instruction}")
    
    # 4. Parameters
    if persona_params:
        prompt_parts.append("\n## Personality Parameters ##")
        params_text = build_persona_parameters(persona_params)
        if params_text:
            prompt_parts.append(params_text)
    
    # 5. Guidelines & Capabilities
    prompt_parts.append("\n## Guidelines ##")
    prompt_parts.append(build_response_guidelines(verbosity_level))
    prompt_parts.append("\n## Capabilities ##")
    prompt_parts.append(build_capabilities_section())
    
    full_prompt = "\n\n".join(prompt_parts)
    
    return {
        "role": "system",
        "content": full_prompt
    }


def get_introduction_instruction(client_id: str, verbosity_level: int = 10) -> dict:
    """Get instruction for initial introduction message."""
    if verbosity_level <= 20:
        length_instruction = "Give a BRIEF introduction (1-2 sentences)."
    else:
        length_instruction = "Introduce yourself naturally (3-4 sentences)."
    
    identity_instruction = ""
    if client_id.startswith("guest_"):
        identity_instruction = (
            " SYSTEM STATUS: Identity unknown. "
            "Introduce yourself and politely ASK the user for their name to register them."
        )
    
    return {
        "role": "system",
        "content": f"{length_instruction} Use '{client_id}' as the user ID. {identity_instruction}"
    }


def build_gating_system_prompt(is_looking: bool) -> str:
    """Build the system prompt for the Gating Layer."""
    visual_status = "LOOKING AT YOU" if is_looking else "LOOKING AWAY"
    
    return f"""You are a 'Collaborative Spotter' for a robot named TARS.
VISUAL CONTEXT: The user is {visual_status}.
Analyze the conversation history.
Return JSON {{'reply': true}} ONLY if:
1. User asks a direct question.
2. User is looking at you and speaking.
3. User explicitly addresses 'TARS'.
4. Users are stuck/confused (Proactive help).

Output JSON: {{"reply": false}} if users are just chatting amongst themselves.
"""