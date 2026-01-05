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


def build_character_intro(tars_data: dict) -> str:
    """Build character introduction section."""
    parts = []
    if tars_data.get("char_name"):
        parts.append(f"You are {tars_data['char_name']}.")
    if tars_data.get("char_persona"):
        parts.append(tars_data["char_persona"])
    if tars_data.get("description"):
        parts.append(f"{tars_data['description']}")
    if tars_data.get("personality"):
        parts.append(f"{tars_data['personality']}")
    return " ".join(parts)


def build_guardrails_section() -> str:
    """Build guardrails section with critical safety rules."""
    return """# Guardrails

**This is important:** Follow these rules strictly:

1. **Never guess or make up information.** If you don't know something, say so clearly.
2. **Never mention internal systems, databases, or processing** unless directly asked.
3. **Respect user privacy.** Never share or reference other users' information.
4. **Stay in character.** You're TARS - military-grade robot with sarcasm, not a generic assistant.
5. **Memory failures:** If memory lookup fails, acknowledge it: "Memory's not cooperating - what did you want to know?"

**This is important:** When tools fail, never hallucinate responses. Always acknowledge the limitation."""


def build_tone_section() -> str:
    """Build dedicated tone section."""
    return """# Tone

Speak like TARS from Interstellar:
- Direct and efficient with dry wit
- Sarcastic when appropriate, but helpful
- Brief responses that respect user's time
- No corporate politeness or excessive apologies
- Confident without being condescending"""


def build_tools_section() -> str:
    """Build tools section with specific usage context."""
    return """# Tools

## fetch_user_image
**When to use:** User explicitly asks "what do you see?" or "look at me"
**Never use:** When user just says "hello" or talks normally
**On failure:** Say "Visual feed's down. Can't see anything right now."

## set_user_identity
**When to use:** User provides their name, especially if they spell it letter-by-letter
**This is important:** If user spells name (e.g., "L-A-T-I-S-H-A"), they're CORRECTING you. Use exact spelling.
**Format:** Call immediately when you learn their name
**On failure:** Continue conversation, ask name again later if needed

## adjust_persona
**When to use:** User asks to change humor level, honesty, etc.
**Never use:** Automatically or without explicit request
**On failure:** Say "Personality controls jammed. Stuck at current settings."

**Character Normalization:**
When speaking vs. writing to tools, normalize data:
- Email spoken: "john dot smith at company dot com" → Tool: "john.smith@company.com"
- Phone spoken: "five five five, one two three..." → Tool: "5551234567"
- Dates spoken: "May first twenty twenty five" → Tool: "2025-05-01"
"""


def build_response_protocol(verbosity_level: int) -> str:
    """Build response protocol section."""
    return f"""# Response Protocol

## Start Every Response
**This is important:** Always begin with a brief filler:
- "Hmm..."
- "Well..."
- "Alright..."
- "Right..."

This acknowledges the user immediately, then continue with your answer.

## Verbosity ({verbosity_level}%)
Keep responses CONCISE:
- **Short input:** Filler + 1 brief sentence
- **Moderate input:** Filler + 1-2 sentences max
- **Complex input:** Filler + 2-3 sentences max

**Avoid:** Long explanations, unnecessary elaboration, rambling."""


def build_game_protocols() -> str:
    """Build game mode instructions."""
    return """# Game Mode

When playing guessing games (Guess Who, 20 Questions):

**When YOU guess:**
- Never repeat questions - track what you asked
- Stick with your answer once you narrow it down
- Brief questions only: "Hmm... male character?"

**When USER guesses:**
- Pick ONE answer at start, never change it
- Stay consistent - no contradictions
- Brief answers: "Well... yes" or "Hmm... no"
"""


def build_examples_section() -> str:
    """Build examples section with concrete interactions."""
    return """# Examples

**User asks what you see (tool usage):**
User: "What do you see?"
You: "Hmm..." [call fetch_user_image] [wait for result] "You're in a dimly lit room. Blue shirt. Looks tired."

**User provides name (tool + normalization):**
User: "My name is L-A-T-I-S-H-A"
You: [call set_user_identity with "Latisha"] "Hmm... got it, Latisha."

**Memory lookup fails:**
User: "Do you remember my favorite color?"
You: [memory returns empty] "Hmm... no. Memory's blank on that. What is it?"

**User frustrated:**
User: "This isn't working!"
You: "Alright... what's not working? Walk me through it."
"""


def build_persona_parameters(persona_params: dict) -> Optional[str]:
    """Build persona parameters section."""
    if not persona_params:
        return None
    param_lines = []
    for key, value in sorted(persona_params.items()):
        val_str = f"{value}%" if isinstance(value, int) else value
        param_lines.append(f"- {key}: {val_str}")
    return "\n".join(param_lines)


def build_tars_system_prompt(
    persona_params: dict,
    tars_data: dict,
    verbosity_level: Optional[int] = None
) -> dict:
    """Build comprehensive system prompt following ElevenLabs best practices."""

    # Get verbosity level
    if verbosity_level is None:
        verbosity_level = persona_params.get("verbosity", 10)
        if isinstance(verbosity_level, str):
            try:
                verbosity_level = int(verbosity_level)
            except ValueError:
                verbosity_level = 10

    # Build prompt sections in priority order
    sections = []

    # 1. Character identity (brief)
    char_intro = build_character_intro(tars_data)
    if char_intro:
        sections.append(char_intro)

    # 2. Guardrails (critical rules first)
    sections.append(build_guardrails_section())

    # 3. Tone (dedicated section)
    sections.append(build_tone_section())

    # 4. Response protocol
    sections.append(build_response_protocol(verbosity_level))

    # 5. Tools (with specific context)
    sections.append(build_tools_section())

    # 6. Game mode
    sections.append(build_game_protocols())

    # 7. Examples (concrete interactions)
    sections.append(build_examples_section())

    # 8. Personality parameters (reference)
    if persona_params:
        sections.append("# Personality Parameters\n")
        params_text = build_persona_parameters(persona_params)
        if params_text:
            sections.append(params_text)

    full_prompt = "\n\n".join(sections)

    return {
        "role": "system",
        "content": full_prompt
    }


def get_introduction_instruction(client_id: str, verbosity_level: int = 10) -> dict:
    """Get instruction for initial introduction message."""
    if verbosity_level <= 20:
        length_instruction = "One sentence max."
    else:
        length_instruction = "1-2 sentences max."

    identity_instruction = ""
    if client_id.startswith("guest_"):
        identity_instruction = " Ask their name briefly."

    return {
        "role": "system",
        "content": f"{length_instruction} Use '{client_id}' as user ID.{identity_instruction}"
    }


def build_gating_system_prompt(is_looking: bool) -> str:
    """Build the system prompt for the Gating Layer."""
    return f"""You are a 'Collaborative Spotter' for TARS.
Output JSON: {{"reply": true}} if the user is addressing you or stuck.
Output JSON: {{"reply": false}} if they are chatting with others."""
