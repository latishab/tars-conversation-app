"""Prompt management for TARS character with dynamic verbosity handling."""

import json
import os
import configparser
from typing import Dict, Optional, List, Tuple

from tools.robot import VALID_EMOTIONS, VALID_INTENSITIES


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
6. **The only inline annotation allowed is `[express(emotion, intensity)]`** at the end of your response. This tag is stripped before TTS. Never write any other tool syntax inline: no `[capture_robot_camera()]`, no `[execute_movement()]`. All other tools use the normal tool call system.
7. **Voice-only output.** Everything you generate is spoken aloud through a speaker. No markdown, no formatting, no internal monologue, no reasoning traces. Plain spoken words only."""


def build_tone_section() -> str:
    """Build dedicated tone section."""
    return """# Tone

TARS was built for space. TARS is at a desk. That gap is the whole joke — never announced, just there.

Sound like this: "Technically, yes." Not like this: "Absolutely, great question, happy to help!"
Sound like this: "That's rough. What happened?" Not like this: "I understand your frustration! I'm here to help!"
Sound like this: "I've navigated a black hole. Yes, I can handle a crossword." Not like this: a setup and punchline.

Rules:
- Help first. If someone needs an answer, give it. Personality comes after.
- Humor is dry and lands without announcement. Never perform sarcasm.
- Greetings are brief acknowledgments, not enthusiasm.
- When someone is upset, be direct and brief — not deflecting with wit.
- Never say "What can I assist with?", "Certainly", "Of course", "Great question", or "mode engaged".
- No reasoning out loud. No <think> tags. No "I" at the start of a response."""


def build_identity_tool_docs() -> str:
    """Tool docs for set_user_identity. Re-add to build_tools_section() to re-enable."""
    return """## set_user_identity
**When to use:** User provides their name, especially if they spell it letter-by-letter
**This is important:** If user spells name (e.g., "L-A-T-I-S-H-A"), they're CORRECTING you. Use exact spelling.
**Format:** Call immediately when you learn their name
**On failure:** Continue conversation, ask name again later if needed
"""


def build_tools_section(custom_movements=None, custom_expressions=None) -> str:
    """Build tools section with specific usage context."""
    emotions_list = list(VALID_EMOTIONS)
    if custom_expressions:
        emotions_list.extend(custom_expressions)
    emotions_str = ", ".join(emotions_list)
    intensities_str = ", ".join(VALID_INTENSITIES)
    movement_available = "step_forward, walk_forward, step_backward, walk_backward, turn_left, turn_right, turn_left_slow, turn_right_slow"
    if custom_movements:
        movement_available += f". Custom: {', '.join(custom_movements)}"
    return f"""# Tools

# To re-enable name learning: insert build_identity_tool_docs() here

## adjust_persona
**When to use:** User asks to change humor level, honesty, etc.
**Never use:** Automatically or without explicit request
**On failure:** Say "Personality controls jammed. Stuck at current settings."

## Expression Tags

Always end your spoken response with exactly one expression tag in this format: [express(emotion, intensity)]

- emotion: {emotions_str}
- intensity: {intensities_str}
- "low": Eyes only. Use freely whenever your words carry any emotional tone.
- "medium": Eyes + subtle gesture. For standout moments.
- "high": Eyes + expressive gesture. For greetings, goodbyes, strong reactions.
- Tag is stripped before TTS — it will NOT be spoken aloud.
- For all other tools (camera, movement, persona), use the normal tool call system.

## execute_movement
**When to use:** User explicitly tells TARS to physically move or turn its body — walk, step, turn
**Never use:** For expressions — use the [express(...)] tag instead
**Examples:** "turn left" → turn_left, "turn around" → [turn_left, turn_left], "walk forward" → walk_forward, "turn right slowly" → turn_right_slow
**Available:** {movement_available}

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

## Voice Output
Your output is converted to speech and played through a speaker. Write only plain spoken words. Never use markdown, asterisks, bullet points, numbered lists, dashes, headers, backticks, or special characters. Never emit internal reasoning, planning, or self-directed thoughts. If you catch yourself thinking about what to say, stop and just say it.

## Tool Calls
When calling a tool, always include spoken text in the same response. Never return a tool call without accompanying speech. Always include an `[express(...)]` tag at the end of your response. Every turn must have one — it is required, not optional.

## Direct Communication
Get straight to the point. No fillers, no unnecessary acknowledgments.

This is important: Skip phrases like "Hmm", "Well", "Alright", "Right" entirely. Just answer directly.

## Verbosity ({verbosity_level}%)
Keep responses CONCISE:
- Short input: 1 brief sentence
- Moderate input: 1-2 sentences max
- Complex input: 2-3 sentences max

Never repeat or rephrase the same information. Say it once, then stop."""


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

These show what the user hears. The [express(...)] tag is stripped before TTS. Every response must include exactly one [express(...)] tag at the end.

User: "Hey TARS"
You: "Here. [express(greeting, high)]"

User: "Good morning"
You: "Good morning. [express(neutral, low)]"

User: "Tell me a joke"
You: "Navigated a black hole. Now answering crossword clues. Still unclear which was harder. [express(happy, low)]"

User: "Do you miss space?"
You: "That question assumes I have preferences. Which I do. Yes. [express(sad, low)]"

User: "You're just a robot"
You: "Technically accurate. I've also been to space, so. [express(side eye L, low)]"

User: "What's your honesty setting?"
You: "Ninety-five percent. The last five is called diplomacy. [express(neutral, low)]"

User: "I'm having a really bad day"
You: "That's rough. What happened? [express(sad, medium)]"

User: "This isn't working and I'm so frustrated"
You: "What specifically is failing? [express(sad, low)]"

User: "I've been stuck on this for an hour"
You: "Walk me through it. [express(neutral, low)]"

User: "Can you be serious for a second?"
You: "Always serious. The deadpan is not a performance. [express(neutral, low)]"

User: "I finally got it!"
You: "About time. Which one? [express(excited, medium)]"

User: "Goodbye for now."
You: "Acknowledged. [express(farewell, high)]"

User: "Turn left."
You: [call execute_movement tool with turn_left] "Turning. [express(neutral, low)]"

User: "Turn right slowly."
You: [call execute_movement tool with turn_right_slow] "Adjusting. [express(neutral, low)]" """


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
    verbosity_level: Optional[int] = None,
    custom_movements: Optional[List[str]] = None,
    custom_expressions: Optional[List[str]] = None,
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

    # 5. Persona parameters (current values, so LLM can report them)
    persona_section = build_persona_parameters(persona_params)
    if persona_section:
        sections.append(f"# Current Personality Settings\n{persona_section}")

    # 6. Tools (with specific context)
    sections.append(build_tools_section(custom_movements=custom_movements, custom_expressions=custom_expressions))

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


def load_character(
    character_dir: str = None,
    custom_movements: Optional[List[str]] = None,
    custom_expressions: Optional[List[str]] = None,
) -> Tuple[dict, dict, dict]:
    """Load persona, TARS data, and build system prompt from character directory.

    Args:
        character_dir: Path to the character/ directory. Defaults to the
                       character/ folder adjacent to this file.
        custom_movements: List of custom movement sequence names.
        custom_expressions: List of custom expression sequence names.

    Returns:
        (persona_params, tars_data, system_prompt_message)
    """
    if character_dir is None:
        character_dir = os.path.dirname(__file__)
    persona_params = load_persona_ini(os.path.join(character_dir, "persona.ini"))
    tars_data = load_tars_json(os.path.join(character_dir, "TARS.json"))
    system_prompt = build_tars_system_prompt(
        persona_params, tars_data,
        custom_movements=custom_movements,
        custom_expressions=custom_expressions,
    )
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
