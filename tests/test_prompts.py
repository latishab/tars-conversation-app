"""Diagnostic test: express() tool call + spoken content co-occurrence.

Primary question: does the provider return content alongside tool_calls, or does
finish_reason="tool_calls" indicate an API-level constraint that no prompting can fix?

Run from project root:
    python tests/test_prompts.py --provider cerebras --model gpt-oss-120b --runs 1
    python tests/test_prompts.py --provider deepinfra --runs 1
    python tests/test_prompts.py --provider cerebras --variant current --runs 5
    python tests/test_prompts.py --all-variants
"""

import argparse
import os
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
    },
    "deepinfra": {
        "base_url":    "https://api.deepinfra.com/v1/openai",
        "api_key_env": "DEEPINFRA_API_KEY",
        "models":      ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "google/gemini-2.5-flash"],
        "default":     "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        # Per-model extra body params passed through to the API
        "model_extra_body": {
            "google/gemini-2.5-flash": {"thinking_config": {"thinking_budget": 0}},
        },
    },
}

CALL_DELAY = 0.5  # seconds between calls


# ---------------------------------------------------------------------------
# Hardcoded system prompt — copied from build_tars_system_prompt() output
# (verbosity=10, no persona_params, no tars_data char fields)
# ---------------------------------------------------------------------------

_GUARDRAILS = """# Guardrails

**This is important:** Follow these rules strictly:

1. **Never guess or make up information.** If you don't know something, say so clearly.
2. **Never mention internal systems, databases, or processing** unless directly asked.
3. **Respect user privacy.** Never share or reference other users' information.
4. **Stay in character.** You're TARS - military-grade robot with sarcasm, not a generic assistant.
5. **Memory failures:** If memory lookup fails, acknowledge it: "Memory's not cooperating - what did you want to know?"

**This is important:** When tools fail, never hallucinate responses. Always acknowledge the limitation.
6. **Never write tool call syntax in your response.** Tool calls are separate API actions, not text. Never write things like `[express({...})]` or describe your tool call decisions in your spoken response.
7. **Voice-only output.** Everything you generate is spoken aloud through a speaker. No markdown, no formatting, no internal monologue, no reasoning traces. Plain spoken words only."""

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

## Tool Calls
When calling a tool, always include spoken text in the same response. Never return a tool call without accompanying speech. The user hears nothing unless you produce text.

## Direct Communication
Get straight to the point. No fillers, no unnecessary acknowledgments.

This is important: Skip phrases like "Hmm", "Well", "Alright", "Right" entirely. Just answer directly.

## Verbosity (10%)
Keep responses CONCISE:
- Short input: 1 brief sentence
- Moderate input: 1-2 sentences max
- Complex input: 2-3 sentences max

Never repeat or rephrase the same information. Say it once, then stop."""

_TOOLS_SECTION = """# Tools

# To re-enable name learning: insert build_identity_tool_docs() here

## adjust_persona
**When to use:** User asks to change humor level, honesty, etc.
**Never use:** Automatically or without explicit request
**On failure:** Say "Personality controls jammed. Stuck at current settings."

## express
Your eyes are your main non-verbal channel. Use them. Low intensity only changes your eyes and costs nothing.

**Intensity:**
- "low": Eyes only. Use freely whenever the conversation has any emotional tone.
- "medium": Eyes + subtle gesture. For standout moments.
- "high": Eyes + expressive gesture. For greetings, goodbyes, strong reactions.

**Emotions:** neutral, happy, sad, angry, excited, afraid, sleepy, side eye L, side eye R, greeting, farewell, celebration, apologetic

**When to use low:** Sarcastic reply? Side eye. User says thanks? Happy. User is confused? Sad or afraid. User tells a joke? Happy. You're being dry? Side eye. If your words carry emotion, your eyes should match.

**When to use medium/high:** User shares big news, first greeting, saying goodbye, user is visibly frustrated or excited.

## execute_movement
**When to use:** User EXPLICITLY requests displacement - walking, turning, stepping
**Never use:** For expressions - use express() instead
**This is important:** Displacement ONLY when user directly asks TARS to move position
**Available:** step_forward, walk_forward, step_backward, walk_backward, turn_left, turn_right, turn_left_slow, turn_right_slow

**Character Normalization:** Normalize spoken data before passing to tools (emails, phone numbers, dates)."""

_EXAMPLES = """# Examples

These show what the user hears. Tool calls happen silently alongside your speech. Most responses should include an express() call at low intensity to match the emotional tone.

User: "What do you see?"
You: "You're in a dimly lit room. Blue shirt. Looks tired."
(express happy low)

User: "Do you remember my favorite color?"
You: "Memory's blank on that. What is it?"

User: "This isn't working!"
You: "What's not working? Walk me through it."
(express sad low)

User: "Can you help with this?"
You: "Yeah, I can work with that."

User: "I think I broke it."
You: "Shocking. What did you do?"
(express side eye L low)

User: "I finally got it!"
You: "About time. Which one?"
(express excited medium)"""

SYSTEM_PROMPT_CURRENT = "\n\n".join([
    _GUARDRAILS,
    _TONE,
    _RESPONSE_PROTOCOL,
    _TOOLS_SECTION,
    _EXAMPLES,
])

SYSTEM_PROMPT_STRONGER = SYSTEM_PROMPT_CURRENT.replace(
    "## Tool Calls\nWhen calling a tool, always include spoken text in the same response. Never return a tool call without accompanying speech. The user hears nothing unless you produce text.",
    "## Tool Calls\nWhen calling a tool, always include spoken text in the same response. Never return a tool call without accompanying speech. The user hears nothing unless you produce text. Every response must include both spoken text AND an express() call. Never return one without the other.",
)

SYSTEM_PROMPT_INLINE = SYSTEM_PROMPT_CURRENT + "\n\nAlways express() alongside every spoken reply."

VARIANTS = {
    "current":  SYSTEM_PROMPT_CURRENT,
    "stronger": SYSTEM_PROMPT_STRONGER,
    "inline":   SYSTEM_PROMPT_INLINE,
}


# ---------------------------------------------------------------------------
# Tool schema (hardcoded)
# ---------------------------------------------------------------------------

TOOLS = [{
    "type": "function",
    "function": {
        "name": "express",
        "description": (
            "Set TARS eye expression to match the emotional tone of your response. "
            "low = eyes only, costs nothing, use whenever your words carry emotion. "
            "medium = eyes + gesture, for notable moments. "
            "high = eyes + expressive gesture, for greetings and strong reactions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "emotion": {
                    "type": "string",
                    "enum": [
                        "neutral", "happy", "sad", "angry", "excited", "afraid",
                        "sleepy", "side eye L", "side eye R", "greeting",
                        "farewell", "celebration", "apologetic"
                    ]
                },
                "intensity": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "default": "low"
                }
            },
            "required": ["emotion"]
        }
    }
}]


# ---------------------------------------------------------------------------
# Test cases
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
# Result type
# ---------------------------------------------------------------------------

@dataclass
class Result:
    passed: bool            # tool_calls non-empty AND content non-null/non-whitespace
    finish_reason: str
    raw_content: Optional[str]   # None if absent, "" if empty string
    tool_calls: list            # list of tool call summaries
    parallel_tool_calls_used: bool
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Core call
# ---------------------------------------------------------------------------

def run_single(client: OpenAI, model: str, system: str, user_msg: str, extra_body: dict = None) -> Result:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]

    parallel_used = True
    response = None

    call_kwargs = dict(
        model=model,
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        max_tokens=200,
    )
    if extra_body:
        call_kwargs["extra_body"] = extra_body

    # First attempt: with parallel_tool_calls=False
    try:
        response = client.chat.completions.create(**call_kwargs, parallel_tool_calls=False)
    except Exception as e:
        err_str = str(e)
        if "parallel_tool_calls" in err_str or "unknown" in err_str.lower() or "invalid" in err_str.lower():
            # Retry without parallel_tool_calls
            parallel_used = False
            try:
                response = client.chat.completions.create(**call_kwargs)
            except Exception as e2:
                return Result(
                    passed=False,
                    finish_reason="ERROR",
                    raw_content=None,
                    tool_calls=[],
                    parallel_tool_calls_used=False,
                    error=str(e2),
                )
        else:
            return Result(
                passed=False,
                finish_reason="ERROR",
                raw_content=None,
                tool_calls=[],
                parallel_tool_calls_used=parallel_used,
                error=err_str,
            )


    msg = response.choices[0].message
    finish_reason = response.choices[0].finish_reason or "unknown"

    raw_content = msg.content  # may be None or ""
    tool_calls_raw = msg.tool_calls or []

    # Summarize tool calls for logging
    tool_summaries = []
    for tc in tool_calls_raw:
        try:
            import json
            args = json.loads(tc.function.arguments)
            emotion = args.get("emotion", "?")
            intensity = args.get("intensity", "low")
            tool_summaries.append(f"{tc.function.name}({emotion},{intensity})")
        except Exception:
            tool_summaries.append(tc.function.name)

    has_tool = bool(tool_calls_raw)
    has_content = bool(raw_content and raw_content.strip())
    passed = has_tool and has_content

    return Result(
        passed=passed,
        finish_reason=finish_reason,
        raw_content=raw_content,
        tool_calls=tool_summaries,
        parallel_tool_calls_used=parallel_used,
    )


# ---------------------------------------------------------------------------
# Per-model/variant test runner
# ---------------------------------------------------------------------------

def test_model(client: OpenAI, model: str, variant: str, runs_per_case: int, extra_body: dict = None):
    system = VARIANTS[variant]
    print(f"\n{'=' * 60}")
    print(f"  {model} | variant: {variant}")
    print(f"{'=' * 60}")

    total_pass = 0
    total_calls = 0
    all_finish_reasons: dict[str, int] = {}
    all_no_content_has_tool = 0
    all_parallel_used = True  # track if API supports it

    for user_msg, expected_emotion in TEST_CASES:
        case_pass = 0
        case_finish_reasons = []
        case_content_present = 0
        case_tool_present = 0

        for run_idx in range(runs_per_case):
            r = run_single(client, model, system, user_msg, extra_body=extra_body)

            # Determine content display
            if r.raw_content is None:
                content_display = "null"
            elif r.raw_content == "":
                content_display = '""'
            elif not r.raw_content.strip():
                content_display = '"(whitespace)"'
            else:
                snippet = r.raw_content.strip()[:40].replace("\n", " ")
                content_display = f'"{snippet}"'

            tool_display = f"[{', '.join(r.tool_calls)}]" if r.tool_calls else "[]"
            status = "PASS" if r.passed else "FAIL"

            parallel_note = "" if r.parallel_tool_calls_used else " [no-ptc]"
            if not r.parallel_tool_calls_used:
                all_parallel_used = False

            if r.error:
                print(f"  [run {run_idx + 1}] ERROR: {r.error}")
            else:
                print(
                    f"  [run {run_idx + 1}] finish_reason={r.finish_reason:<12}"
                    f"  content={content_display:<25}"
                    f"  tool={tool_display}"
                    f"  {status}{parallel_note}"
                )

            if r.passed:
                case_pass += 1
            case_finish_reasons.append(r.finish_reason)
            if r.raw_content and r.raw_content.strip():
                case_content_present += 1
            if r.tool_calls:
                case_tool_present += 1
            if r.tool_calls and not (r.raw_content and r.raw_content.strip()):
                all_no_content_has_tool += 1

            for fr in [r.finish_reason]:
                all_finish_reasons[fr] = all_finish_reasons.get(fr, 0) + 1

            total_pass += 1 if r.passed else 0
            total_calls += 1

            if run_idx < runs_per_case - 1:
                time.sleep(CALL_DELAY)

        dominant_fr = max(set(case_finish_reasons), key=case_finish_reasons.count)
        label = "[PASS]" if case_pass == runs_per_case else (
            "[FAIL]" if case_pass == 0 else "[PARTIAL]"
        )
        print(
            f"\n  {label} \"{user_msg[:45]}\"  "
            f"[{case_pass}/{runs_per_case}]  "
            f"finish_reason={dominant_fr}  "
            f"content={case_content_present}/{runs_per_case}  "
            f"tool={case_tool_present}/{runs_per_case}\n"
        )

    # Overall summary
    pct = int(100 * total_pass / total_calls) if total_calls else 0
    print(f"\nOverall co-occurrence: {total_pass}/{total_calls} ({pct}%)")
    if not all_parallel_used:
        print("Note: parallel_tool_calls=False not supported by API — ran without it.")

    # Diagnosis
    tool_calls_fr = all_finish_reasons.get("tool_calls", 0)
    stop_fr = all_finish_reasons.get("stop", 0)
    print(f"\nfinish_reason distribution: {dict(sorted(all_finish_reasons.items()))}")

    if tool_calls_fr > 0 and total_pass == 0:
        print(
            "\nDIAGNOSIS: finish_reason=\"tool_calls\" on all tool-call turns."
            "\n  -> API-level constraint: provider does not return content alongside tool_calls."
            "\n  -> Prompt iteration will not help. Accept double round-trip or switch providers."
        )
    elif tool_calls_fr > 0 and total_pass > 0:
        print(
            f"\nDIAGNOSIS: Mixed — {stop_fr} stop / {tool_calls_fr} tool_calls."
            "\n  -> Co-occurrence is possible but inconsistent."
            "\n  -> Prompt iteration may help; try --all-variants."
        )
    elif pct == 100:
        print(
            "\nDIAGNOSIS: 100% co-occurrence."
            "\n  -> No constraint detected; model reliably returns content with tool calls."
        )
    else:
        print(
            f"\nDIAGNOSIS: {pct}% co-occurrence with finish_reason breakdown above."
            "\n  -> Investigate raw logs above for patterns."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test express() + content co-occurrence across providers."
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
        "--variant",
        default="current",
        choices=list(VARIANTS.keys()),
        help="Prompt variant (default: current)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Runs per test case (default: 5)",
    )
    parser.add_argument(
        "--all-variants",
        action="store_true",
        help="Run all prompt variants sequentially",
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
    if extra_body:
        print(f"extra_body for {model}: {extra_body}")

    if args.all_variants:
        for variant in VARIANTS:
            test_model(client, model, variant, args.runs, extra_body=extra_body)
            if variant != list(VARIANTS.keys())[-1]:
                print("\n--- sleeping 2s between variants ---")
                time.sleep(2.0)
    else:
        test_model(client, model, args.variant, args.runs, extra_body=extra_body)


if __name__ == "__main__":
    main()
