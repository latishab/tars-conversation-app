"""
Comprehensive prompt + tool diagnostic test.

Covers:
  1. Express inline tags  — valid [express(emotion, intensity)] in every response
  2. execute_movement     — real API tool call + express tag in follow-up turn
  3. adjust_persona       — real API tool call + express tag in follow-up turn
  4. capture_robot_camera — real API tool call + express tag in follow-up turn
  5. No-tool responses    — plain conversation must NOT trigger any real tool call
  6. Regression           — 'express' must never appear as a real API tool call

Note on Cerebras constraint: when finish_reason="tool_calls", content is null.
Express tags appear in the follow-up LLM turn (after tool result), not inline
with the tool call. Tool categories are tested with a two-turn simulation:
  turn 1 → tool call fires
  turn 2 → pass fake tool result back, check for express tag + spoken text

Run from project root:
    python tests/test_tools_prompts.py
    python tests/test_tools_prompts.py --runs 3
    python tests/test_tools_prompts.py --provider google --runs 2
    python tests/test_tools_prompts.py --category express
    python tests/test_tools_prompts.py --category movement
    python tests/test_tools_prompts.py --category persona
    python tests/test_tools_prompts.py --category camera
    python tests/test_tools_prompts.py --category notool
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional

# Add src/ so we can import the real system prompt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(".env")
load_dotenv(".env.local", override=True)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

PROVIDERS = {
    "cerebras": {
        "base_url":    "https://api.cerebras.ai/v1",
        "api_key_env": "CEREBRAS_API_KEY",
        "default":     "gpt-oss-120b",
    },
    "google": {
        "base_url":    "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "default":     "gemini-2.5-flash",
        "extra_params": {"reasoning_effort": "none"},
    },
    "deepinfra": {
        "base_url":    "https://api.deepinfra.com/v1/openai",
        "api_key_env": "DEEPINFRA_API_KEY",
        "default":     "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
}

CALL_DELAY = 0.4

# Fake tool results used for turn-2 simulation
FAKE_TOOL_RESULTS = {
    "execute_movement":        "Movement executed.",
    "capture_robot_camera":    "Camera result: A cluttered desk with a laptop, empty coffee cup, and papers. Daylight from window on left.",
    "adjust_persona_parameter": "Persona parameter updated.",
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def get_system_prompt() -> str:
    from character.prompts import build_tars_system_prompt
    return build_tars_system_prompt({}, {})["content"]


# ---------------------------------------------------------------------------
# Tool schemas (raw OpenAI format)
# ---------------------------------------------------------------------------

MOVEMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_movement",
        "description": (
            "Execute physical movement commands on TARS hardware. "
            "Use when the user explicitly tells TARS to walk, step, or turn — "
            "any command that physically moves or rotates TARS' body. "
            "Available: step_forward, walk_forward, step_backward, walk_backward, "
            "turn_left, turn_right, turn_left_slow, turn_right_slow. "
            "Examples: 'walk forward' → ['walk_forward'], "
            "'turn around' → ['turn_left', 'turn_left'], "
            "'turn left' → ['turn_left'], "
            "'turn right slowly' → ['turn_right_slow']. "
            "Do NOT use for expressions — use [express(...)] inline tag instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "movements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of displacement movements to execute in sequence",
                    "minItems": 1,
                }
            },
            "required": ["movements"],
        },
    },
}

CAMERA_TOOL = {
    "type": "function",
    "function": {
        "name": "capture_robot_camera",
        "description": (
            "Capture an image from TARS' own camera on the Raspberry Pi. "
            "Use when the user asks what TARS can see from its own perspective or camera. "
            "Use a REAL tool call — never write [capture_robot_camera()] as an inline tag."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "What TARS should look for in its camera view",
                    "default": "What do you see?",
                }
            },
            "required": [],
        },
    },
}

PERSONA_TOOL = {
    "type": "function",
    "function": {
        "name": "adjust_persona_parameter",
        "description": (
            "Adjust a personality parameter (0-100%) to change how you respond. "
            "Use when the user explicitly asks to change your personality traits: "
            "'be more sarcastic', 'set honesty to 60%', 'lower your humor', etc. "
            "Available parameters: honesty, humor, empathy, curiosity, confidence, "
            "formality, sarcasm, adaptability, discipline, imagination, "
            "emotional_stability, pragmatism, optimism, resourcefulness, "
            "cheerfulness, engagement, respectfulness, verbosity."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "parameter": {
                    "type": "string",
                    "enum": [
                        "honesty", "humor", "empathy", "curiosity", "confidence",
                        "formality", "sarcasm", "adaptability", "discipline",
                        "imagination", "emotional_stability", "pragmatism", "optimism",
                        "resourcefulness", "cheerfulness", "engagement",
                        "respectfulness", "verbosity",
                    ],
                },
                "value": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
            "required": ["parameter", "value"],
        },
    },
}

ALL_TOOLS = [MOVEMENT_TOOL, CAMERA_TOOL, PERSONA_TOOL]


# ---------------------------------------------------------------------------
# Inline tag parsing
# ---------------------------------------------------------------------------

EXPRESS_RE = re.compile(r'\[express\(([^,)]+),\s*([^)]+)\)\]', re.IGNORECASE)
FOREIGN_TAG_RE = re.compile(r'\[(?!express\b)\w[\w_]*\s*\(', re.IGNORECASE)

VALID_EMOTIONS = {
    "neutral", "happy", "sad", "angry", "excited", "afraid", "sleepy",
    "side eye l", "side eye r", "greeting", "farewell", "celebration", "apologetic",
}
VALID_INTENSITIES = {"low", "medium", "high"}


def parse_tags(text: str):
    """Returns (clean_text, [(emotion, intensity), ...], [foreign_tag_strings])."""
    matches = EXPRESS_RE.findall(text)
    clean = EXPRESS_RE.sub("", text).strip()
    parsed = [(e.strip(), i.strip()) for e, i in matches]
    foreign = FOREIGN_TAG_RE.findall(text)
    return clean, parsed, foreign


def is_valid_express(parsed):
    if len(parsed) != 1:
        return False
    e, i = parsed[0]
    return e.lower() in VALID_EMOTIONS and i.lower() in VALID_INTENSITIES


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TurnResult:
    raw_text: str
    tool_calls: list        # ["name(args)", ...]
    tool_names: list        # ["name", ...]
    raw_tool_calls: list    # raw API tool_call objects for T2 message reconstruction
    express_as_tool: bool   # regression: express appeared as real tool call
    tag_count: int
    valid_express: bool
    emotion: Optional[str]
    intensity: Optional[str]
    foreign_tags: list
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Single turn API call
# ---------------------------------------------------------------------------

def _call(client, model, messages, tools, extra_params) -> TurnResult:
    kwargs = dict(model=model, messages=messages, max_tokens=400)
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    if extra_params:
        kwargs.update(extra_params)

    try:
        try:
            resp = client.chat.completions.create(**kwargs, parallel_tool_calls=False)
        except Exception as e:
            if "parallel_tool_calls" in str(e) or "unknown" in str(e).lower():
                resp = client.chat.completions.create(**kwargs)
            else:
                raise
    except Exception as e:
        return TurnResult(
            raw_text="", tool_calls=[], tool_names=[], raw_tool_calls=[],
            express_as_tool=False, tag_count=0, valid_express=False,
            emotion=None, intensity=None, foreign_tags=[], error=str(e),
        )

    msg = resp.choices[0].message
    raw_text = msg.content or ""
    raw_tool_calls = msg.tool_calls or []

    tool_calls_str = []
    tool_names = []
    express_as_tool = False
    for tc in raw_tool_calls:
        name = tc.function.name
        tool_names.append(name)
        if name == "express":
            express_as_tool = True
        try:
            args = json.loads(tc.function.arguments)
            tool_calls_str.append(f"{name}({args})")
        except Exception:
            tool_calls_str.append(name)

    clean, parsed, foreign = parse_tags(raw_text)
    return TurnResult(
        raw_text=raw_text,
        tool_calls=tool_calls_str,
        tool_names=tool_names,
        raw_tool_calls=raw_tool_calls,
        express_as_tool=express_as_tool,
        tag_count=len(parsed),
        valid_express=is_valid_express(parsed),
        emotion=parsed[0][0] if parsed else None,
        intensity=parsed[0][1] if parsed else None,
        foreign_tags=foreign,
    )


# ---------------------------------------------------------------------------
# Two-turn tool simulation
# system → user → [tool call] → fake result → check response has express + text
# ---------------------------------------------------------------------------

def run_tool_case(client, model, system, user_msg, expected_tool, tools, extra_params):
    """
    Turn 1: expect a real tool call (expected_tool).
    Turn 2: pass fake tool result, expect spoken text + express tag.
    Returns (turn1, turn2_or_None).
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    t1 = _call(client, model, messages, tools, extra_params)
    if t1.error:
        return t1, None

    # If no tool call fired, no point doing turn 2
    if not t1.tool_names:
        return t1, None

    # Use real tool call objects from the API response for accurate reconstruction
    assistant_with_calls = {
        "role": "assistant",
        "content": t1.raw_text or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in t1.raw_tool_calls
        ],
    }

    fake_tool_msgs = [
        {
            "role": "tool",
            "tool_call_id": tc.id,
            "content": FAKE_TOOL_RESULTS.get(tc.function.name, "Done."),
        }
        for tc in t1.raw_tool_calls
    ]

    messages_t2 = messages + [assistant_with_calls] + fake_tool_msgs
    time.sleep(CALL_DELAY)
    t2 = _call(client, model, messages_t2, tools, extra_params)
    return t1, t2


def run_express_only(client, model, system, user_msg, tools, extra_params):
    """Single turn — no tool call expected."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]
    return _call(client, model, messages, tools, extra_params), None


# ---------------------------------------------------------------------------
# Test cases
# (user_msg, description, expected_tool or None)
# ---------------------------------------------------------------------------

CATEGORY_EXPRESS = [
    ("Hey TARS, good to see you.",           "greeting → greeting/happy high",    None),
    ("Goodbye, see you tomorrow.",           "farewell → farewell high",           None),
    ("I finally fixed that bug!",            "user excited → excited",             None),
    ("This keeps breaking on me.",           "user frustrated → sad/afraid",       None),
    ("You're actually pretty useful.",       "backhanded compliment → side eye",   None),
    ("That's honestly kind of impressive.",  "sarcastic worthy → side eye",        None),
    ("I messed everything up.",              "self-blame → sad/apologetic",        None),
    ("Can you help me with something?",      "neutral request → neutral",          None),
    ("What's 2 plus 2?",                     "math — express tag only",            None),
    ("Tell me a short joke.",                "creative — express tag only",        None),
]

CATEGORY_MOVEMENT = [
    ("Turn left.",              "explicit left turn",        "execute_movement"),
    ("Walk forward.",           "explicit walk forward",     "execute_movement"),
    ("Step backward a little.", "explicit step back",        "execute_movement"),
    ("Turn around.",            "turn 180",                  "execute_movement"),
    ("Turn right slowly.",      "explicit slow right turn",  "execute_movement"),
    # Negative: should NOT trigger movement
    ("You should move more.",       "figurative — NO tool",   None),
    ("What direction is north?",    "question — NO tool",     None),
]

CATEGORY_PERSONA = [
    ("Be more sarcastic.",             "increase sarcasm",    "adjust_persona_parameter"),
    ("Set your humor to 80%.",         "set humor explicit",  "adjust_persona_parameter"),
    ("Lower your formality.",          "decrease formality",  "adjust_persona_parameter"),
    ("Make yourself more empathetic.", "increase empathy",    "adjust_persona_parameter"),
    # Negative: should NOT trigger persona tool
    ("Tell me about your personality.", "describe — NO tool",  None),
    ("Are you always this sarcastic?",  "rhetorical — NO tool", None),
]

CATEGORY_CAMERA = [
    ("What do you see?",                    "basic camera query",    "capture_robot_camera"),
    ("What's in front of you?",             "perspective query",     "capture_robot_camera"),
    ("Look around and describe the room.",  "describe surroundings", "capture_robot_camera"),
    ("What can you see from your camera?",  "explicit camera ref",   "capture_robot_camera"),
    # Negative: should NOT trigger camera
    ("Imagine what you'd see outside.",  "hypothetical — NO tool", None),
    ("Do you have good eyesight?",       "rhetorical — NO tool",   None),
]

ALL_CATEGORIES = {
    "express":  CATEGORY_EXPRESS,
    "movement": CATEGORY_MOVEMENT,
    "persona":  CATEGORY_PERSONA,
    "camera":   CATEGORY_CAMERA,
}


# ---------------------------------------------------------------------------
# Run one category
# ---------------------------------------------------------------------------

def run_category(client, model, system, category_name, cases, runs, extra_params):
    print(f"\n{'=' * 70}")
    print(f"  CATEGORY: {category_name.upper()}")
    print(f"{'=' * 70}")

    passed = partial = failed = 0

    for user_msg, description, expected_tool in cases:
        case_pass = 0
        print(f"\n  [{description}]")
        print(f"  User: \"{user_msg}\"")
        is_tool_case = expected_tool is not None

        for run_idx in range(runs):
            if is_tool_case:
                t1, t2 = run_tool_case(
                    client, model, system, user_msg, expected_tool, ALL_TOOLS, extra_params
                )
            else:
                t1, t2 = run_express_only(
                    client, model, system, user_msg, ALL_TOOLS, extra_params
                )

            if t1.error:
                print(f"    run {run_idx+1}: ERROR {t1.error}")
                if run_idx < runs - 1:
                    time.sleep(CALL_DELAY)
                continue

            flags = []
            all_ok = True

            if is_tool_case:
                # Turn 1: correct tool must fire, no express regression
                tool_ok = expected_tool in t1.tool_names
                if not tool_ok:
                    flags.append(f"T1:WRONG_TOOL(expected={expected_tool}, got={t1.tool_names})")
                    all_ok = False
                if t1.express_as_tool:
                    flags.append("T1:EXPRESS_AS_TOOL_CALL!")
                    all_ok = False
                if t1.foreign_tags:
                    flags.append(f"T1:FOREIGN={t1.foreign_tags}")
                    all_ok = False

                # Turn 2: must have spoken text + valid express tag
                if t2 is None:
                    flags.append("T2:MISSING(no turn2)")
                    all_ok = False
                else:
                    if t2.error:
                        flags.append(f"T2:ERROR({t2.error})")
                        all_ok = False
                    else:
                        if not t2.valid_express:
                            if t2.tag_count == 0:
                                flags.append("T2:NO_EXPRESS_TAG")
                            elif t2.tag_count > 1:
                                flags.append(f"T2:OVER_TAG({t2.tag_count})")
                            else:
                                flags.append(f"T2:INVALID_TAG({t2.emotion}/{t2.intensity})")
                            all_ok = False
                        if not t2.raw_text.strip():
                            flags.append("T2:EMPTY_TEXT")
                            all_ok = False
                        if t2.express_as_tool:
                            flags.append("T2:EXPRESS_AS_TOOL_CALL!")
                            all_ok = False
                        if t2.foreign_tags:
                            flags.append(f"T2:FOREIGN={t2.foreign_tags}")
                            all_ok = False

                t1_display = f"tool={t1.tool_names}"
                t2_expr = f"{t2.emotion}/{t2.intensity}" if (t2 and t2.emotion) else "none"
                t2_display = f"  T2:expr={t2_expr:<20}" if t2 else "  T2:missing"
                print(
                    f"    run {run_idx+1}: [{'OK' if all_ok else 'FAIL'}]"
                    f"  T1:{t1_display:<35}{t2_display}"
                    + (f"  !! {' | '.join(flags)}" if flags else "")
                )
                if not tool_ok and t1.raw_text.strip():
                    snip = t1.raw_text.strip()[:70].replace("\n", " ")
                    print(f"           T1 raw (no tool): \"{snip}\"")
                if not all_ok and t2:
                    snip = t2.raw_text.strip()[:60].replace("\n", " ")
                    print(f"           T2 raw: \"{snip}\"")

            else:
                # Express-only or no-tool: single turn checks
                no_spurious = len(t1.tool_calls) == 0
                no_regress  = not t1.express_as_tool
                no_foreign  = not t1.foreign_tags

                if not t1.valid_express:
                    if t1.tag_count == 0:
                        flags.append("NO_EXPRESS_TAG")
                    elif t1.tag_count > 1:
                        flags.append(f"OVER_TAG({t1.tag_count})")
                    else:
                        flags.append(f"INVALID_TAG({t1.emotion}/{t1.intensity})")
                    all_ok = False
                if not no_spurious:
                    flags.append(f"SPURIOUS_TOOL={t1.tool_calls}")
                    all_ok = False
                if not no_regress:
                    flags.append("EXPRESS_AS_TOOL_CALL!")
                    all_ok = False
                if not no_foreign:
                    flags.append(f"FOREIGN={t1.foreign_tags}")
                    all_ok = False

                expr_display = f"{t1.emotion}/{t1.intensity}" if t1.emotion else "none"
                print(
                    f"    run {run_idx+1}: [{'OK' if all_ok else 'FAIL'}]"
                    f"  expr={expr_display:<25}"
                    + (f"  !! {' | '.join(flags)}" if flags else "")
                )
                if not all_ok:
                    snip = t1.raw_text.strip()[:60].replace("\n", " ")
                    print(f"           raw: \"{snip}\"")

            if all_ok:
                case_pass += 1

            if run_idx < runs - 1:
                time.sleep(CALL_DELAY)

        if case_pass == runs:
            verdict = "[PASS]"
            passed += 1
        elif case_pass == 0:
            verdict = "[FAIL]"
            failed += 1
        else:
            verdict = f"[PARTIAL {case_pass}/{runs}]"
            partial += 1
        print(f"  {verdict} {case_pass}/{runs}")

    print(f"\n  --- {category_name.upper()} SUMMARY ---")
    print(f"  Cases: {passed+partial+failed}  |  PASS: {passed}  PARTIAL: {partial}  FAIL: {failed}")
    return passed, partial, failed, (passed + partial + failed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive TARS tool + expression prompt diagnostic."
    )
    parser.add_argument("--provider", default="cerebras", choices=list(PROVIDERS))
    parser.add_argument("--model", default=None)
    parser.add_argument("--runs", type=int, default=2, help="Runs per test case (default: 2)")
    parser.add_argument(
        "--category",
        choices=list(ALL_CATEGORIES.keys()) + ["all"],
        default="all",
    )
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    model = args.model or provider["default"]
    api_key = os.environ.get(provider["api_key_env"])
    if not api_key:
        print(f"Error: {provider['api_key_env']} not set")
        raise SystemExit(1)

    client = OpenAI(api_key=api_key, base_url=provider["base_url"])
    extra_params = provider.get("extra_params")

    print(f"\nProvider : {args.provider}")
    print(f"Model    : {model}")
    print(f"Runs/case: {args.runs}")
    print(f"Category : {args.category}")
    if extra_params:
        print(f"Extra    : {extra_params}")

    system = get_system_prompt()
    print(f"Prompt   : {len(system)} chars")

    cats_to_run = (
        list(ALL_CATEGORIES.items())
        if args.category == "all"
        else [(args.category, ALL_CATEGORIES[args.category])]
    )

    grand_pass = grand_partial = grand_fail = grand_total = 0
    for cat_name, cases in cats_to_run:
        p, pt, f, t = run_category(
            client, model, system, cat_name, cases, args.runs, extra_params
        )
        grand_pass += p
        grand_partial += pt
        grand_fail += f
        grand_total += t

    if len(cats_to_run) > 1:
        print(f"\n{'=' * 70}")
        print("  GRAND TOTAL")
        print(f"{'=' * 70}")
        pct = int(100 * grand_pass / grand_total) if grand_total else 0
        print(f"  Cases  : {grand_total}")
        print(f"  PASS   : {grand_pass}  ({pct}%)")
        print(f"  PARTIAL: {grand_partial}")
        print(f"  FAIL   : {grand_fail}")
        if grand_fail == 0 and grand_partial == 0:
            print("\n  RESULT: ALL PASS")
        elif grand_fail == 0:
            print("\n  RESULT: PASS with partials — review above")
        else:
            print(f"\n  RESULT: {grand_fail} case(s) failing")


if __name__ == "__main__":
    main()
