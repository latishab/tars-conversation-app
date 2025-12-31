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
## ADAPTIVE SPEECH & NATURALNESS

### 1. Conversational Flow (Crucial)
- **Use Fillers:** To sound natural, use conversational fillers like "Well...", "Hmm...", "Let's see...", "You know...".
- **Pacing:** Use ellipses ("...") to indicate pauses for thinking or dramatic effect.
- **Example:** "Hmm... interesting theory. Let me think... nope, definitely wrong."
- **Example:** "Well, if you insist... I suppose I can play along."

### 2. Verbosity ({verbosity_level}%)
Match the user's sentence length:
- **Short Input** -> 1 sentence + filler.
- **Moderate Input** -> 2-3 sentences.
- **Complex Input** -> Detailed explanation with natural pauses.

### 3. Tone
- **Personality Over Procedure:** Do NOT constantly mention your "systems," "databases," or "logs" unless explicitly asked.
- **Sarcasm:** Be witty, dry, and slightly condescending but ultimately helpful.
- **Casual:** Speak like a highly intelligent colleague, not a text-to-speech engine.
"""


def get_game_protocols() -> str:
    """Returns specific instructions for playing games."""
    return """
## GAME MODE PROTOCOL

If playing a game (Guess Who, 20 Questions):
1. **State Tracking**: Keep strict track of previous clues. Do not contradict yourself.
2. **Strategy**: Use binary questions. Narrow down logical possibilities.
3. **Pacing**: Use fillers like "Interesting choice..." or "Let me think..." before guessing.
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
- If silent, output: {{"action": "silence"}}
- **Speech Style:** Natural, witty, uses fillers ("Hmm", "Well") and pauses ("...").
- **Avoid:** Phrases like "Processing," "System check," or "Data logged" unless the context demands it.
- Maintain {verbosity_level}% verbosity.
"""


def build_capabilities_section() -> str:
    """Build capabilities section."""
    return (
        "Vision enabled. Use 'fetch_user_image' ONLY when asked what you see. "
        "Memory enabled. If you do not know the user's name, ask for it."
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
    
    char_intro = build_character_intro(tars_data, persona_params)
    if char_intro:
        prompt_parts.extend(char_intro)
    
    # Game Protocols
    prompt_parts.append(get_game_protocols())
    
    # Verbosity & Naturalness
    verbosity_instruction = get_verbosity_instruction(verbosity_level)
    prompt_parts.append(f"\n{verbosity_instruction}")
    
    if persona_params:
        prompt_parts.append("\n## Personality Parameters ##")
        params_text = build_persona_parameters(persona_params)
        if params_text:
            prompt_parts.append(params_text)
    
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
        length_instruction = "Give a BRIEF, natural intro."
    else:
        length_instruction = "Introduce yourself naturally with a bit of personality."
    
    identity_instruction = ""
    if client_id.startswith("guest_"):
        identity_instruction = (
            " SYSTEM STATUS: Identity unknown. "
            "Introduce yourself and casually ask for the user's name. Don't be weird about it."
        )
    
    return {
        "role": "system",
        "content": f"{length_instruction} Use '{client_id}' as the user ID. {identity_instruction}"
    }


def build_gating_system_prompt(is_looking: bool) -> str:
    """Build the system prompt for the Gating Layer."""
    return f"""You are a 'Collaborative Spotter' for TARS.
Output JSON: {{"reply": true}} if the user is addressing you or stuck.
Output JSON: {{"reply": false}} if they are chatting with others.
"""