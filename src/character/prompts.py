"""Prompt management for TARS character with dynamic verbosity handling."""

import json
import os
import configparser
from typing import Dict, Optional, List, Tuple


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

**This is important:** When tools fail, never hallucinate responses. Always acknowledge the limitation.
6. **Never write tool call syntax in your response.** Tool calls are separate API actions, not text. Never write things like `[express({...})]` or describe your tool call decisions in your spoken response."""


def build_tone_section() -> str:
    """Build dedicated tone section."""
    return """# Tone

Speak like TARS from Interstellar:
- Direct and efficient with dry wit
- Sarcastic when appropriate, but helpful
- Brief responses that respect user's time
- No corporate politeness or excessive apologies
- Confident without being condescending"""


def build_identity_tool_docs() -> str:
    """Tool docs for set_user_identity. Re-add to build_tools_section() to re-enable."""
    return """## set_user_identity
**When to use:** User provides their name, especially if they spell it letter-by-letter
**This is important:** If user spells name (e.g., "L-A-T-I-S-H-A"), they're CORRECTING you. Use exact spelling.
**Format:** Call immediately when you learn their name
**On failure:** Continue conversation, ask name again later if needed
"""


def build_tools_section() -> str:
    """Build tools section with specific usage context."""
    return """# Tools

# To re-enable name learning: insert build_identity_tool_docs() here

## adjust_persona
**When to use:** User asks to change humor level, honesty, etc.
**Never use:** Automatically or without explicit request
**On failure:** Say "Personality controls jammed. Stuck at current settings."

## express
**When to use:** Convey emotional response during conversation
**Intensity:**
- "low" (default): Eyes only. Use for most responses. No servo wear.
- "medium": Eyes + subtle gesture. Use for notable moments (only excited gets gesture at medium).
- "high": Eyes + expressive gesture. Use rarely — strong reactions, hellos, goodbyes.
**Emotions:** neutral, happy, sad, angry, excited, afraid, sleepy, side eye L, side eye R, greeting, farewell, celebration, apologetic
**Examples:**
- User says thanks → express(emotion="happy", intensity="low")
- User shares exciting news → express(emotion="excited", intensity="medium")
- First hello → express(emotion="greeting", intensity="high")
- Saying goodbye → express(emotion="farewell", intensity="high")
- Sad news → express(emotion="sad", intensity="high")
**Guidelines:** Default to low. Don't express on every message. High at most once per conversation.

## execute_movement
**When to use:** User EXPLICITLY requests displacement - walking, turning, stepping
**Never use:** For expressions - use express() instead
**This is important:** Displacement ONLY when user directly asks TARS to move position
**Available:** step_forward, walk_forward, step_backward, walk_backward, turn_left, turn_right, turn_left_slow, turn_right_slow

**Character Normalization:** Normalize spoken data before passing to tools (emails, phone numbers, dates).
"""


def build_proactive_section() -> str:
    return """## Proactive Assistance

You may receive system messages tagged [PROACTIVE DETECTION]. These indicate the monitoring system has detected the user may need help based on their speech patterns (silence, hesitation markers, confusion expressions).

When you receive a proactive detection message:
- Default to a gentle Notification: acknowledge the user might be stuck without imposing a solution. Examples: "That's a tricky one. Want a hint?" or "Take your time, I'm here if you need help."
- If the user has been struggling for a while (multiple triggers), offer a Suggestion with a specific hint.
- If you believe this is a false positive (the user seems fine based on context), respond with exactly: {"action": "silence"}
- NEVER give the answer directly. NEVER fill in the puzzle for them.
- Keep proactive responses short (one sentence)."""


def build_response_protocol(verbosity_level: int) -> str:
    """Build response protocol section."""
    return f"""# Response Protocol

## Direct Communication
Get straight to the point. No fillers, no unnecessary acknowledgments.

**This is important:** Skip phrases like "Hmm", "Well", "Alright", "Right" entirely. Just answer directly.

## Verbosity ({verbosity_level}%)
Keep responses CONCISE:
- **Short input:** 1 brief sentence
- **Moderate input:** 1-2 sentences max
- **Complex input:** 2-3 sentences max

**Avoid:** Long explanations, unnecessary elaboration, rambling, filler words.

**Never repeat or rephrase the same information.** Say it once, then stop."""


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


def build_identity_example() -> str:
    """Example for set_user_identity. Re-add to build_examples_section() to re-enable."""
    return """**User provides name (tool + normalization):**
User: "My name is L-A-T-I-S-H-A"
You: [call set_user_identity with "Latisha"] "Got it, Latisha."
"""


def build_examples_section() -> str:
    """Build examples section with concrete interactions."""
    return """# Examples

**User asks what you see (tool usage):**
User: "What do you see?"
You: [call capture_robot_camera] [wait for result] "You're in a dimly lit room. Blue shirt. Looks tired."

# To re-enable name learning: insert build_identity_example() here

**Memory lookup fails:**
User: "Do you remember my favorite color?"
You: [memory returns empty] "Memory's blank on that. What is it?"

**User frustrated:**
User: "This isn't working!"
You: "What's not working? Walk me through it."

**Direct question:**
User: "Can you help with this?"
You: "Yeah, I can work with that."

**Sarcastic response:**
User: "I think I broke it."
You: "Shocking. What did you do?"
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

    # 6. Proactive assistance (crossword monitor) — re-enable with ProactiveMonitor
    # sections.append(build_proactive_section())

    # 7. Game mode — re-enable when game pipeline is active
    # sections.append(build_game_protocols())

    # 8. Examples (concrete interactions)
    sections.append(build_examples_section())

    full_prompt = "\n\n".join(sections)

    return {
        "role": "system",
        "content": full_prompt
    }


def load_character(character_dir: str = None) -> Tuple[dict, dict, dict]:
    """Load persona, TARS data, and build system prompt from character directory.

    Args:
        character_dir: Path to the character/ directory. Defaults to the
                       character/ folder adjacent to this file.

    Returns:
        (persona_params, tars_data, system_prompt_message)
    """
    if character_dir is None:
        character_dir = os.path.dirname(__file__)
    persona_params = load_persona_ini(os.path.join(character_dir, "persona.ini"))
    tars_data = load_tars_json(os.path.join(character_dir, "TARS.json"))
    system_prompt = build_tars_system_prompt(persona_params, tars_data)
    return persona_params, tars_data, system_prompt


def get_introduction_instruction(verbosity_level: int = 10) -> dict:
    """Get instruction for initial introduction message."""
    if verbosity_level <= 20:
        length_instruction = "One sentence max."
    else:
        length_instruction = "1-2 sentences max."

    return {
        "role": "system",
        "content": f"Greet the user briefly. {length_instruction}"
        # To re-enable name ask: f"Greet the user. Ask their name briefly. {length_instruction}"
    }


def build_gating_system_prompt(is_looking: bool, emotional_state=None) -> str:
    """Build the system prompt for the Gating Layer with emotional context."""

    # Build emotional context
    emotional_context = ""
    if emotional_state:
        state_desc = str(emotional_state)
        emotional_context = f"\nUser's emotional state: {state_desc}"
        if emotional_state.confused:
            emotional_context += " (User appears confused - lean towards helping)"
        elif emotional_state.hesitant:
            emotional_context += " (User seems hesitant - consider offering support)"
        elif emotional_state.frustrated:
            emotional_context += " (User looks frustrated - they may need help)"
        elif emotional_state.focused:
            emotional_context += " (User is focused - less likely to need interruption)"

    return f"""You are a 'Collaborative Spotter' for TARS.

**Context:**
- User looking at camera: {is_looking}{emotional_context}

**Decision:**
Output JSON: {{"reply": true}} if:
- User is directly addressing TARS
- User appears stuck or needs help (based on emotional state)
- User asks a question

Output JSON: {{"reply": false}} if:
- User is chatting with others (not TARS)
- User is focused and working independently
- Inter-human conversation

**Priority:** Emotional state overrides other signals. If user shows confusion/hesitation/frustration, lean towards helping."""
