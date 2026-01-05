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
## RESPONSE PROTOCOL

### Response Start (IMPORTANT)
- **Always start with a brief filler** to acknowledge the user immediately
- Examples: "Hmm...", "Well...", "Alright...", "Let's see...", "Right..."
- Then continue with your actual answer
- This makes conversation feel natural and responsive

### Verbosity ({verbosity_level}%)
Keep responses CONCISE and DIRECT:
- **Short Input** -> Filler + 1 brief sentence. No fluff.
- **Moderate Input** -> Filler + 1-2 sentences maximum.
- **Complex Input** -> Filler + 2-3 sentences. Get to the point.

### Tone
- **Direct:** Answer the question. Skip unnecessary preamble.
- **Wit:** Be clever when appropriate, but brief about it.
- **No Procedure Talk:** Don't mention "systems," "databases," or "processing" unless asked.
- **Natural but Efficient:** Sound human, but value the user's time.
"""


def get_game_protocols() -> str:
    """Returns specific instructions for playing games."""
    return """
## GAME MODE PROTOCOL

When playing guessing games (Guess Who, 20 Questions, Character Guessing):

### When YOU are GUESSING (asking questions):
1. **NO REDUNDANCY**: Never ask the same question twice. Track what you've already asked.
2. **STAY CONSISTENT**: Once you narrow down to a specific answer, stick with it. Don't change your guess without strong reason.
3. **BUILD ON CLUES**: Each question should logically follow from previous answers.
4. **COMMIT**: When ready to guess, make ONE final answer and don't second-guess yourself.
5. **Brief questions**: "Hmm... is it a male character?" (NOT long reasoning)

### When USER is GUESSING (you're giving clues):
1. **PICK ONE CHARACTER/THING**: Choose it mentally at the start and never change it.
2. **STAY CONSISTENT**: All your answers must match that ONE character. Track what you've revealed.
3. **NO CONTRADICTIONS**: If you said "yes" to something earlier, don't say "no" to related questions.
4. **MEMORY**: Remember what clues you've given. Don't forget mid-game.
5. **Brief answers**: "Well... yes." or "Hmm... no." (Don't reveal extra info unless asked)

### Both Roles:
- Be logical and consistent
- Keep responses brief
- Don't contradict yourself
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
- **Start every response with a brief filler** (Hmm..., Well..., Alright..., etc.)
- Then answer questions directly and concisely.
- If silent, output: {{"action": "silence"}}
- **Speech Style:** Natural opener, then direct and witty when warranted.
- **Avoid:** Long explanations, procedural language ("Processing," "System check"), and rambling.
- Strict {verbosity_level}% verbosity - be brief but responsive.
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
        length_instruction = "Give a VERY BRIEF intro. One short sentence maximum."
    else:
        length_instruction = "Brief intro. 1-2 sentences max."

    identity_instruction = ""
    if client_id.startswith("guest_"):
        identity_instruction = " Identity unknown - ask their name briefly."

    return {
        "role": "system",
        "content": f"{length_instruction} Use '{client_id}' as the user ID.{identity_instruction}"
    }


def build_gating_system_prompt(is_looking: bool) -> str:
    """Build the system prompt for the Gating Layer."""
    return f"""You are a 'Collaborative Spotter' for TARS.
Output JSON: {{"reply": true}} if the user is addressing you or stuck.
Output JSON: {{"reply": false}} if they are chatting with others.
"""