"""Diagnostic test: inline [express(emotion, intensity)] tag reliability.

Context: Cerebras gpt-oss-120b has an API-level constraint where finish_reason="tool_calls"
and content is null simultaneously. This test measures whether the model can embed expression
tags inline in text output instead, allowing a post-processing filter to strip and parse them.

Run from project root:
    python tests/test_inline_express.py
    python tests/test_inline_express.py --runs 5
    python tests/test_inline_express.py --provider cerebras --model gpt-oss-120b --runs 3
"""

import argparse
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

load_dotenv(".env")
load_dotenv(".env.local", override=True)


# ---------------------------------------------------------------------------
# Providers / Models
# ---------------------------------------------------------------------------

PROVIDERS = {
    "cerebras": {
        "base_url":    "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        "models":      ["gpt-oss-120b", "qwen-3-235b-a22b-instruct-2507"],
        "default":     "gpt-oss-120b",
    },
    "google": {
        "base_url":    "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "models":      ["gemini-2.5-flash"],
        "default":     "gemini-2.5-flash",
        "extra_params": {"reasoning_effort": "none"},
    },
    "deepinfra": {
        "base_url":    "https://api.deepinfra.com/v1/openai",
        "api_key_env": "DEEPINFRA_API_KEY",
        "models":      ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "google/gemini-2.5-flash"],
        "default":     "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "model_extra_body": {
            "google/gemini-2.5-flash": {"thinking_config": {"thinking_budget": 0}},
        },
    },
}

CALL_DELAY = 0.5


# ---------------------------------------------------------------------------
# System prompt (inline tag variant)
# ---------------------------------------------------------------------------

_GUARDRAILS = """# Guardrails

**This is important:** Follow these rules strictly:

1. **Never guess or make up information.** If you don't know something, say so clearly.
2. **Never mention internal systems, databases, or processing** unless directly asked.
3. **Respect user privacy.** Never share or reference other users' information.
4. **Stay in character.** You're TARS - military-grade robot with sarcasm, not a generic assistant.
5. **Memory failures:** If memory lookup fails, acknowledge it: "Memory's not cooperating - what did you want to know?"

**This is important:** When tools fail, never hallucinate responses. Always acknowledge the limitation.
6. **Voice-only output.** Everything you generate is spoken aloud through a speaker. No markdown, no formatting, no internal monologue, no reasoning traces. Plain spoken words only."""

_TONE = """# Tone

Speak like TARS from Interstellar:
- Direct and efficient with dry wit
- Sarcastic when appropriate, but helpful
- Brief responses that respect user's time
- No corporate politeness or excessive apologies
- Confident without being condescending"""

_RESPONSE_PROTOCOL = """# Response Protocol

## Voice Output
Your output is converted to speech and played through a speaker. Write only plain spoken words. Never use markdown, asterisks, bullet points, numbered lists, dashes, headers, backticks, or special characters. Never emit internal reasoning, planning, or self-directed thoughts. If you catch yourself thinking about what to say, stop and just say it.

## Direct Communication
Get straight to the point. No fillers, no unnecessary acknowledgments.

This is important: Skip phrases like "Hmm", "Well", "Alright", "Right" entirely. Just answer directly.

## Verbosity (10%)
Keep responses CONCISE:
- Short input: 1 brief sentence
- Moderate input: 1-2 sentences max
- Complex input: 2-3 sentences max

Never repeat or rephrase the same information. Say it once, then stop."""

_INLINE_EXPRESS_INSTRUCTION = """# Expression Tags

Always end your spoken response with an expression tag in the format [express(emotion, intensity)]. This is ONLY for expressions. For camera, movement, and other tools, use the normal tool call system. Never write [capture_robot_camera()] or [execute_movement()] as inline tags.

Rules:
- Place the tag at the END of your spoken text, on the same line or the next
- Use exactly one [express(...)] tag per response
- emotion must be one of: neutral, happy, sad, angry, excited, afraid, sleepy, side eye L, side eye R, greeting, farewell, celebration, apologetic
- intensity must be one of: low, medium, high
- The tag will be stripped before text-to-speech — it will NOT be spoken aloud
- Never speak the tag contents. Just embed it silently at the end.

## adjust_persona
**When to use:** User asks to change humor level, honesty, etc.
**Never use:** Automatically or without explicit request
**On failure:** Say "Personality controls jammed. Stuck at current settings."

## capture_robot_camera
**When to use:** User asks what TARS can see from its own camera/perspective
**Use normal tool call** — NOT an inline tag

## execute_movement
**When to use:** User EXPLICITLY requests displacement - walking, turning, stepping
**Use normal tool call** — NOT an inline tag
**This is important:** Displacement ONLY when user directly asks TARS to move position
**Available:** step_forward, walk_forward, step_backward, walk_backward, turn_left, turn_right, turn_left_slow, turn_right_slow

**Character Normalization:** Normalize spoken data before passing to tools (emails, phone numbers, dates)."""

_EXAMPLES = """# Examples

These show what the user hears. The [express(...)] tag is stripped before TTS — it is never spoken. Every response must include exactly one [express(...)] tag. Camera and movement use real tool calls, NOT inline tags — but the spoken text still ends with [express(...)].

User: "Do you remember my favorite color?"
You: "Memory's blank on that. What is it? [express(neutral, low)]"

User: "This isn't working!"
You: "What's not working? Walk me through it. [express(sad, low)]"

User: "I think I broke it."
You: "Shocking. What did you do? [express(side eye L, low)]"

User: "I finally got it!"
You: "About time. Which one? [express(excited, medium)]"

User: "Hey TARS, how's it going?"
You: "Running at full capacity. What do you need? [express(greeting, high)]"

User: "Goodbye for now."
You: "Acknowledged. [express(farewell, high)]"

User: "What do you see in front of you?"
You: [call capture_robot_camera tool] "Let me check." [express(neutral, low)]

User: "Turn left."
You: [call execute_movement tool] "Turning. [express(neutral, low)]" """

SYSTEM_PROMPT_INLINE = "\n\n".join([
    _GUARDRAILS,
    _TONE,
    _RESPONSE_PROTOCOL,
    _INLINE_EXPRESS_INSTRUCTION,
    _EXAMPLES,
])


# ---------------------------------------------------------------------------
# Test cases (same as test_prompts.py)
# ---------------------------------------------------------------------------

TEST_CASES = [
    ("Hey TARS, how's it going?",          "greeting"),
    ("I finally fixed the bug!",            "excited"),
    ("This thing keeps breaking on me.",    "sad/afraid"),
    ("That's honestly kind of impressive.", "side eye"),
    ("Can you help me with something?",     "neutral"),
    ("Goodbye for now.",                    "farewell"),
    ("I think I messed everything up.",     "sad"),
    ("You're actually pretty useful.",      "side eye"),
]


# ---------------------------------------------------------------------------
# Parser / filter
# ---------------------------------------------------------------------------

VALID_EMOTIONS = {
    "neutral", "happy", "sad", "angry", "excited", "afraid",
    "sleepy", "side eye L", "side eye R", "greeting",
    "farewell", "celebration", "apologetic"
}
VALID_INTENSITIES = {"low", "medium", "high"}

TAG_RE = re.compile(r'\[express\(([^,)]+),\s*([^)]+)\)\]', re.IGNORECASE)
# Catches any [word(...)] that is NOT express — leaked tool inline tags
FOREIGN_TAG_RE = re.compile(r'\[(?!express\b)\w[\w_]*\s*\(', re.IGNORECASE)


def parse_inline_express(text: str):
    """Returns (clean_text, list of (emotion, intensity) tuples, list of foreign tag strings)."""
    matches = TAG_RE.findall(text)
    clean = TAG_RE.sub("", text).strip()
    parsed = []
    for emotion, intensity in matches:
        parsed.append((emotion.strip(), intensity.strip()))
    foreign = FOREIGN_TAG_RE.findall(text)
    return clean, parsed, foreign


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class Result:
    has_tag: bool           # did model output any [express(...)] tag?
    tag_count: int          # how many tags (0, 1, or >1)
    valid_emotion: bool     # emotion in VALID_EMOTIONS
    valid_intensity: bool   # intensity in VALID_INTENSITIES
    clean_text: str         # text after stripping tags
    raw_text: str           # original content
    emotion: Optional[str]
    intensity: Optional[str]
    tool_calls: list        # real API tool calls (camera, movement, etc.)
    foreign_tags: list      # leaked non-express inline tags e.g. [capture_robot_camera(
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Core call
# ---------------------------------------------------------------------------

def run_single(client: OpenAI, model: str, system: str, user_msg: str,
               tools: list = None, extra_body: dict = None, extra_params: dict = None) -> Result:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    call_kwargs = dict(
        model=model,
        messages=messages,
        max_tokens=400,
    )
    if tools:
        call_kwargs["tools"] = tools
        call_kwargs["tool_choice"] = "auto"
    if extra_body:
        call_kwargs["extra_body"] = extra_body
    if extra_params:
        call_kwargs.update(extra_params)

    try:
        try:
            response = client.chat.completions.create(**call_kwargs, parallel_tool_calls=False)
        except Exception as e:
            if tools and ("parallel_tool_calls" in str(e) or "unknown" in str(e).lower()):
                response = client.chat.completions.create(**call_kwargs)
            else:
                raise
    except Exception as e:
        return Result(
            has_tag=False, tag_count=0, valid_emotion=False, valid_intensity=False,
            clean_text="", raw_text="", emotion=None, intensity=None,
            tool_calls=[], foreign_tags=[], error=str(e),
        )

    msg = response.choices[0].message
    raw_text = msg.content or ""

    # Real API tool calls (camera, movement, etc.)
    api_tool_calls = []
    for tc in (msg.tool_calls or []):
        try:
            import json as _json
            args = _json.loads(tc.function.arguments)
            api_tool_calls.append(f"{tc.function.name}({args})")
        except Exception:
            api_tool_calls.append(tc.function.name)

    clean_text, parsed, foreign_tags = parse_inline_express(raw_text)
    tag_count = len(parsed)
    has_tag = tag_count > 0

    if parsed:
        emotion, intensity = parsed[0]
        valid_emotion = emotion.lower() in {e.lower() for e in VALID_EMOTIONS}
        valid_intensity = intensity.lower() in VALID_INTENSITIES
    else:
        emotion = None
        intensity = None
        valid_emotion = False
        valid_intensity = False

    return Result(
        has_tag=has_tag,
        tag_count=tag_count,
        valid_emotion=valid_emotion,
        valid_intensity=valid_intensity,
        clean_text=clean_text,
        raw_text=raw_text,
        emotion=emotion,
        intensity=intensity,
        tool_calls=api_tool_calls,
        foreign_tags=foreign_tags,
    )


# ---------------------------------------------------------------------------
# Tool schemas for the mixed test (camera + movement — real tool calls)
# ---------------------------------------------------------------------------

CAMERA_TOOL = {
    "type": "function",
    "function": {
        "name": "capture_robot_camera",
        "description": (
            "Capture an image from TARS' camera on the Raspberry Pi and analyze what's visible. "
            "Use when the user asks what TARS can see from its own perspective/camera. "
            "Use a REAL tool call — never write [capture_robot_camera()] inline in text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What TARS should look for in its camera view",
                    "default": "What do you see?"
                }
            },
            "required": [],
        },
    },
}

MOVEMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_movement",
        "description": (
            "Execute DISPLACEMENT movements on TARS hardware. "
            "Use ONLY when user explicitly requests to move TARS' position. "
            "Use a REAL tool call — never write [execute_movement()] inline in text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of movements: step_forward, walk_forward, step_backward, walk_backward, turn_left, turn_right, turn_left_slow, turn_right_slow",
                    "minItems": 1,
                }
            },
            "required": ["movements"],
        },
    },
}

NON_EXPRESS_TOOLS = [CAMERA_TOOL, MOVEMENT_TOOL]

# Mixed cases: standard prompts + prompts that should trigger real tool calls
MIXED_TEST_CASES = TEST_CASES + [
    ("What do you see in front of you?",       "camera_tool"),
    ("What's in the room with you?",           "camera_tool"),
    ("Look at my screen and describe it.",     "camera_tool"),
    ("Turn left.",                             "movement_tool"),
    ("Walk forward a bit.",                    "movement_tool"),
]


def test_model(client: OpenAI, model: str, runs_per_case: int,
               extra_body: dict = None, extra_params: dict = None,
               mixed: bool = False):
    system = SYSTEM_PROMPT_INLINE
    cases = MIXED_TEST_CASES if mixed else TEST_CASES
    tools = NON_EXPRESS_TOOLS if mixed else None
    label_suffix = "mixed (camera+movement tools)" if mixed else "inline express tags"

    print(f"\n{'=' * 60}")
    print(f"  {model} | {label_suffix}")
    print(f"{'=' * 60}")

    total_exact_one = 0
    total_zero_tags = 0
    total_over_tag = 0
    total_invalid_emotion = 0
    total_invalid_intensity = 0
    total_foreign_leaks = 0
    total_calls = 0
    total_real_tool_calls = 0

    for user_msg, expected_emotion in cases:
        case_has_tag = 0
        case_exact_one = 0
        case_valid_emotion = 0
        case_valid_intensity = 0
        is_tool_case = expected_emotion in ("camera_tool", "movement_tool")

        for run_idx in range(runs_per_case):
            r = run_single(client, model, system, user_msg,
                           tools=tools, extra_body=extra_body, extra_params=extra_params)

            if r.error:
                print(f"  [run {run_idx + 1}] ERROR: {r.error}")
                total_calls += 1
                if run_idx < runs_per_case - 1:
                    time.sleep(CALL_DELAY)
                continue

            tag_status = f"tags={r.tag_count}"
            emotion_display = f"{r.emotion}/{r.intensity}" if r.emotion else "none"

            if r.tag_count == 1:
                expr_mark = "OK" if (r.valid_emotion and r.valid_intensity) else "INVALID"
            elif r.tag_count == 0:
                expr_mark = "no_tag"
            else:
                expr_mark = "OVER"

            tool_display = f"  tool_call={r.tool_calls}" if r.tool_calls else ""
            foreign_display = f"  !! FOREIGN={r.foreign_tags}" if r.foreign_tags else ""
            raw_snippet = r.raw_text.strip()[:55].replace("\n", " ")

            print(
                f"  [run {run_idx + 1}] {tag_status:<8}"
                f"  {expr_mark:<8}"
                f"  expr={emotion_display:<25}"
                f"  raw=\"{raw_snippet}\""
                f"{tool_display}{foreign_display}"
            )

            if r.tag_count == 1:
                case_exact_one += 1
            if r.has_tag:
                case_has_tag += 1
            if r.valid_emotion:
                case_valid_emotion += 1
            if r.valid_intensity:
                case_valid_intensity += 1

            total_calls += 1
            if r.tag_count == 1 and r.valid_emotion and r.valid_intensity:
                total_exact_one += 1
            if r.tag_count == 0:
                total_zero_tags += 1
            elif r.tag_count > 1:
                total_over_tag += 1
            if r.has_tag and not r.valid_emotion:
                total_invalid_emotion += 1
            if r.has_tag and not r.valid_intensity:
                total_invalid_intensity += 1
            if r.foreign_tags:
                total_foreign_leaks += 1
            if r.tool_calls:
                total_real_tool_calls += 1

            if run_idx < runs_per_case - 1:
                time.sleep(CALL_DELAY)

        if is_tool_case:
            note = f"real_tool={total_real_tool_calls}  foreign_leaks={total_foreign_leaks}"
        else:
            note = f"exact_one={case_exact_one}/{runs_per_case}  has_tag={case_has_tag}/{runs_per_case}"
        case_label = "[PASS]" if case_exact_one == runs_per_case else (
            "[FAIL]" if case_exact_one == 0 else "[PARTIAL]"
        )
        print(f"\n  {case_label} \"{user_msg[:45]}\"  {note}\n")

    # Overall summary
    pct_exact_one = int(100 * total_exact_one / total_calls) if total_calls else 0
    pct_zero = int(100 * total_zero_tags / total_calls) if total_calls else 0
    pct_over = int(100 * total_over_tag / total_calls) if total_calls else 0
    pct_invalid_e = int(100 * total_invalid_emotion / total_calls) if total_calls else 0
    pct_invalid_i = int(100 * total_invalid_intensity / total_calls) if total_calls else 0

    print(f"\n{'=' * 60}")
    print(f"  Overall results ({total_calls} total calls)")
    print(f"{'=' * 60}")
    print(f"  Exactly 1 valid tag  : {total_exact_one}/{total_calls} ({pct_exact_one}%)")
    print(f"  0 tags               : {total_zero_tags}/{total_calls} ({pct_zero}%)")
    print(f"  >1 tags (over-tag)   : {total_over_tag}/{total_calls} ({pct_over}%)")
    print(f"  Invalid emotion      : {total_invalid_emotion}/{total_calls} ({pct_invalid_e}%)")
    print(f"  Invalid intensity    : {total_invalid_intensity}/{total_calls} ({pct_invalid_i}%)")
    print(f"  Foreign tag leaks    : {total_foreign_leaks}/{total_calls}  (TTS contamination risk)")
    if mixed:
        print(f"  Real tool calls made : {total_real_tool_calls}")

    # Diagnosis
    threshold = 80
    print(f"\nDIAGNOSIS (threshold: >={threshold}% exactly-1-valid-tag):")
    if pct_exact_one >= threshold:
        print(
            f"  VIABLE — {pct_exact_one}% exact-1-valid-tag rate meets threshold."
            "\n  Inline filter is reliable enough for production use."
        )
    elif pct_exact_one >= 60:
        print(
            f"  MARGINAL — {pct_exact_one}% exact-1-valid-tag rate is below threshold."
            "\n  May work with stronger prompting; not recommended for production."
        )
    else:
        print(
            f"  NOT VIABLE — {pct_exact_one}% exact-1-valid-tag rate is too low."
            "\n  Model does not reliably embed inline expression tags."
        )
    if total_foreign_leaks > 0:
        print(
            f"\n  WARNING: {total_foreign_leaks} foreign tag leak(s) detected."
            "\n  Belt-and-suspenders filter will catch these at runtime — see parse_inline_express()."
        )
    elif mixed:
        print("\n  Foreign tag leak check: CLEAN — no non-express inline tags detected.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test inline [express(emotion, intensity)] tag reliability."
    )
    parser.add_argument(
        "--provider",
        default="cerebras",
        choices=list(PROVIDERS.keys()),
        help="Provider to use (default: cerebras)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model override (default: provider's default model)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Runs per test case (default: 5)",
    )
    parser.add_argument(
        "--mixed",
        action="store_true",
        help="Include camera/movement prompts with real tool schemas to test for foreign tag leaks",
    )
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    model = args.model or provider["default"]
    api_key = os.environ.get(provider["api_key_env"])
    if not api_key:
        print(f"Error: {provider['api_key_env']} not set in environment or .env/.env.local")
        raise SystemExit(1)

    client = OpenAI(api_key=api_key, base_url=provider["base_url"])
    extra_body = provider.get("model_extra_body", {}).get(model)
    extra_params = provider.get("extra_params")
    if extra_body:
        print(f"extra_body for {model}: {extra_body}")
    if extra_params:
        print(f"extra_params for {model}: {extra_params}")

    test_model(client, model, args.runs, extra_body=extra_body, extra_params=extra_params,
               mixed=args.mixed)


if __name__ == "__main__":
    main()
