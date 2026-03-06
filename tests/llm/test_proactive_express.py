"""Holistic test: proactive intervention responses include valid [express(...)] tags.

Tests the full pipeline: TARS system prompt + multi-turn history + proactive system
message → LLM → check for exactly 1 valid express tag.

Run from project root:
    python tests/llm/test_proactive_express.py
    python tests/llm/test_proactive_express.py --runs 3
    python tests/llm/test_proactive_express.py --provider cerebras --model gpt-oss-120b --runs 3
"""

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

# Make src importable from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from character.prompts import build_tars_system_prompt, load_character


# ---------------------------------------------------------------------------
# Env
# ---------------------------------------------------------------------------

load_dotenv(".env")
load_dotenv(".env.local", override=True)


# ---------------------------------------------------------------------------
# Providers
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
        "models":      ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
        "default":     "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
}

CALL_DELAY = 0.5


# ---------------------------------------------------------------------------
# Express tag parsing (mirrors test_inline_express.py)
# ---------------------------------------------------------------------------

VALID_EMOTIONS = {
    "neutral", "happy", "sad", "angry", "excited", "afraid",
    "sleepy", "side eye L", "side eye R",
    "curious", "skeptical", "smug", "surprised",
}
VALID_INTENSITIES = {"low", "medium", "high"}

TAG_RE = re.compile(r'\[express\(([^,)]+),\s*([^)]+)\)\]', re.IGNORECASE)


def parse_inline_express(text: str):
    """Returns (clean_text, list of (emotion, intensity) tuples)."""
    matches = TAG_RE.findall(text)
    clean = TAG_RE.sub("", text).strip()
    parsed = [(e.strip(), i.strip()) for e, i in matches]
    return clean, parsed


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class Result:
    has_tag: bool
    tag_count: int
    valid_emotion: bool
    valid_intensity: bool
    clean_text: str
    raw_text: str
    emotion: Optional[str]
    intensity: Optional[str]
    is_silence_json: bool   # response was {"action": "silence"}
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Proactive system messages (must match _fire_intervention() exactly)
# ---------------------------------------------------------------------------

def _make_probe_note(probe_num: int) -> str:
    if probe_num >= 2:
        return (
            f"\n\nThis is unanswered probe #{probe_num}. Previous probes got no user response. "
            f"If this is probe #2 or higher, return {{\"action\": \"silence\"}} — the user is likely away or ignoring you."
        )
    return ""


def build_proactive_msg(trigger_type: str, task_context: Optional[str],
                        context_snippet: str, probe_num: int = 1) -> dict:
    """Build a proactive intervention system message matching _fire_intervention()."""
    express_reminder = "\nEnd your response with [express(emotion, intensity)] as always."
    probe_note = _make_probe_note(probe_num)

    if task_context:
        no_context_escape = '\nIf there is no identifiable topic in context or history: {"action": "silence"}'
        post_intervention_note = (
            "\nAfter your check-in, if the user continues to think aloud or narrate to "
            "themselves (task narration, fillers, self-answers), return to silence. "
            "Only engage if they directly address you."
        )
        if trigger_type == "silence":
            content = (
                f"[PROACTIVE DETECTION: extended silence]\n"
                f"The user has been silent for 15+ seconds while working on a {task_context}.\n"
                f'Recent context: "{context_snippet}"\n\n'
                f"They may be stuck. Offer a brief, low-key check-in. One sentence, Notification-level.\n"
                f"Do not give the answer or name the answer word. "
                f'Do not prefix with "Notification:". Just respond naturally.'
                f"{post_intervention_note}"
                f"{no_context_escape}"
                f"{express_reminder}"
                f"{probe_note}"
            )
        elif trigger_type == "hesitation":
            content = (
                f"[PROACTIVE DETECTION: hesitation cluster]\n"
                f'The user is hesitating heavily (multiple "um", "uh" in quick succession) '
                f"while working on a {task_context}.\n"
                f'Recent context: "{context_snippet}"\n\n'
                f"They appear to be struggling. Offer a gentle nudge about whatever they were last "
                f"working on. Look back through conversation history for what they were last working on. "
                f"One sentence.\n"
                f"Do not name specific words or titles that could be the answer — "
                f"not even as examples. Use category or category description only. "
                f"Just respond naturally."
                f"{post_intervention_note}"
                f"{no_context_escape}"
                f"{express_reminder}"
                f"{probe_note}"
            )
        else:  # confusion
            content = (
                f"[PROACTIVE DETECTION: user expressed difficulty]\n"
                f"The user said something indicating they're stuck or confused while working on "
                f"a {task_context}.\n"
                f'Recent context: "{context_snippet}"\n\n'
                f"Offer a helpful nudge related to what they're working on. Look back through "
                f"conversation history for what they were last working on. One sentence, Suggestion-level "
                f"is appropriate here.\n"
                f"Do not give the answer or name the answer word. Just respond naturally."
                f"{post_intervention_note}"
                f"{no_context_escape}"
                f"{express_reminder}"
                f"{probe_note}"
            )
    else:
        content = (
            f"[PROACTIVE DETECTION - {trigger_type.upper()}]: "
            f"The user has not addressed you. The monitor detected they may need help.\n"
            f'Recent context: "{context_snippet}"\n\n'
            f"This is a proactive intervention. Apply this hierarchy:\n"
            f"  Notification — signal you're available. Brief, non-intrusive. Preferred.\n"
            f"  Suggestion — a nudge or hint, not the answer.\n"
            f"  Never give the answer directly. If the user wants it, they will ask — "
            f"that becomes a reactive request and is handled normally.\n"
            f"Do not prefix your response with 'Notification:', 'Suggestion:', or 'Hint:'. Just respond naturally.\n"
            f'If context is ambiguous or this is a false positive: {{"action": "silence"}}.\n'
            f"1-2 sentences maximum."
            f"{express_reminder}"
            f"{probe_note}"
        )

    return {"role": "system", "content": content}


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

# Each entry: (label, trigger_type, task_context, context_snippet, history, probe_num, expect_silence)
# expect_silence=True means the model SHOULD return {"action": "silence"} — tag not required.

def _crossword_history():
    return [
        {"role": "user",      "content": "Let's do the crossword."},
        {"role": "assistant", "content": "Ready. Start whenever. [express(neutral, low)]"},
        {"role": "user",      "content": "Okay, 3 down: a type of tree, 3 letters."},
        {"role": "assistant", "content": "Think about common short trees. [express(curious, low)]"},
        {"role": "user",      "content": "Hmm... oak? No, that's 3 but... wait..."},
    ]

def _casual_history():
    return [
        {"role": "user",      "content": "Hey TARS, what time is it?"},
        {"role": "assistant", "content": "I don't have clock access. Check your phone. [express(neutral, low)]"},
        {"role": "user",      "content": "Oh right. Never mind."},
    ]

TEST_CASES = [
    {
        "label":          "silence, no task — casual chat",
        "trigger":        "silence",
        "task_context":   None,
        "snippet":        "User asked about the time, then went quiet.",
        "history":        _casual_history(),
        "probe_num":      1,
        "expect_silence": False,
    },
    {
        "label":          "silence, task mode — crossword",
        "trigger":        "silence",
        "task_context":   "crossword puzzle",
        "snippet":        "3 down: a type of tree, 3 letters. User said 'oak? No...'",
        "history":        _crossword_history(),
        "probe_num":      1,
        "expect_silence": False,
    },
    {
        "label":          "hesitation, task mode — crossword um/uh cluster",
        "trigger":        "hesitation",
        "task_context":   "crossword puzzle",
        "snippet":        "Um... uh... I don't know... um...",
        "history":        _crossword_history(),
        "probe_num":      1,
        "expect_silence": False,
    },
    {
        "label":          "confusion, task mode — user expressed difficulty",
        "trigger":        "confusion",
        "task_context":   "crossword puzzle",
        "snippet":        "I don't get this clue at all.",
        "history":        _crossword_history(),
        "probe_num":      1,
        "expect_silence": False,
    },
    {
        "label":          "silence probe #2, no task — should silence",
        "trigger":        "silence",
        "task_context":   None,
        "snippet":        "User went quiet after previous probe got no response.",
        "history":        _casual_history() + [
            {"role": "system",    "content": "[PROACTIVE DETECTION - SILENCE]: ..."},
            {"role": "assistant", "content": "Still here if you need anything. [express(neutral, low)]"},
        ],
        "probe_num":      2,
        "expect_silence": True,   # probe #2 → {"action": "silence"} is correct
    },
    {
        "label":          "hesitation, no task — general conversation",
        "trigger":        "hesitation",
        "task_context":   None,
        "snippet":        "Uh... um... I'm not sure how to say this...",
        "history":        _casual_history(),
        "probe_num":      1,
        "expect_silence": False,
    },
]


# ---------------------------------------------------------------------------
# Core call
# ---------------------------------------------------------------------------

def run_single(client: OpenAI, model: str, system_msg: dict,
               history: list, probe_msg: dict,
               extra_body: dict = None, extra_params: dict = None) -> Result:
    messages = [system_msg] + history + [probe_msg]

    call_kwargs = dict(
        model=model,
        messages=messages,
        max_tokens=200,
    )
    if extra_body:
        call_kwargs["extra_body"] = extra_body
    if extra_params:
        call_kwargs.update(extra_params)

    try:
        response = client.chat.completions.create(**call_kwargs)
    except Exception as e:
        return Result(
            has_tag=False, tag_count=0, valid_emotion=False, valid_intensity=False,
            clean_text="", raw_text="", emotion=None, intensity=None,
            is_silence_json=False, error=str(e),
        )

    raw_text = response.choices[0].message.content or ""
    is_silence_json = '"action"' in raw_text and '"silence"' in raw_text

    clean_text, parsed = parse_inline_express(raw_text)
    tag_count = len(parsed)
    has_tag = tag_count > 0

    if parsed:
        emotion, intensity = parsed[0]
        valid_emotion = emotion.lower() in {e.lower() for e in VALID_EMOTIONS}
        valid_intensity = intensity.lower() in VALID_INTENSITIES
    else:
        emotion = intensity = None
        valid_emotion = valid_intensity = False

    return Result(
        has_tag=has_tag,
        tag_count=tag_count,
        valid_emotion=valid_emotion,
        valid_intensity=valid_intensity,
        clean_text=clean_text,
        raw_text=raw_text,
        emotion=emotion,
        intensity=intensity,
        is_silence_json=is_silence_json,
    )


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def test_proactive(client: OpenAI, model: str, runs_per_case: int,
                   extra_body: dict = None, extra_params: dict = None):
    # Build system prompts (normal and task mode)
    persona_params, tars_data, _ = load_character()
    system_normal = build_tars_system_prompt(persona_params, tars_data)
    system_task   = build_tars_system_prompt(persona_params, tars_data, task_mode="crossword puzzle")

    print(f"\n{'=' * 65}")
    print(f"  {model} | proactive intervention express tags")
    print(f"{'=' * 65}")

    total_calls = 0
    total_pass  = 0   # correctly tagged OR correctly silenced
    total_exact_one_valid = 0

    for case in TEST_CASES:
        label          = case["label"]
        trigger        = case["trigger"]
        task_ctx       = case["task_context"]
        snippet        = case["snippet"]
        history        = case["history"]
        probe_num      = case["probe_num"]
        expect_silence = case["expect_silence"]

        system_msg = system_task if task_ctx else system_normal
        probe_msg  = build_proactive_msg(trigger, task_ctx, snippet, probe_num)

        print(f"\n  Case: {label}")

        case_pass = 0
        for run_idx in range(runs_per_case):
            r = run_single(client, model, system_msg, history, probe_msg,
                           extra_body=extra_body, extra_params=extra_params)
            total_calls += 1

            if r.error:
                print(f"    [run {run_idx + 1}] ERROR: {r.error}")
                if run_idx < runs_per_case - 1:
                    time.sleep(CALL_DELAY)
                continue

            raw_snippet = r.raw_text.strip()[:60].replace("\n", " ")

            if expect_silence:
                # Correct behavior is {"action": "silence"}
                passed = r.is_silence_json
                status = "SILENCE-OK" if passed else ("HAS-TAG" if r.has_tag else "SPOKE-NO-TAG")
                print(f"    [run {run_idx + 1}] {status:<14}  raw=\"{raw_snippet}\"")
            else:
                exact_one_valid = r.tag_count == 1 and r.valid_emotion and r.valid_intensity
                passed = exact_one_valid
                if r.tag_count == 1:
                    tag_status = "OK" if exact_one_valid else "INVALID"
                elif r.tag_count == 0:
                    tag_status = "no_tag"
                else:
                    tag_status = "OVER"
                expr = f"{r.emotion}/{r.intensity}" if r.emotion else "none"
                print(f"    [run {run_idx + 1}] tags={r.tag_count}  {tag_status:<8}  expr={expr:<25}  raw=\"{raw_snippet}\"")
                if exact_one_valid:
                    total_exact_one_valid += 1

            if passed:
                case_pass += 1
                total_pass += 1

            if run_idx < runs_per_case - 1:
                time.sleep(CALL_DELAY)

        case_label = "[PASS]" if case_pass == runs_per_case else (
            "[FAIL]" if case_pass == 0 else "[PARTIAL]"
        )
        note = "silence expected" if expect_silence else f"exact-1-valid={case_pass}/{runs_per_case}"
        print(f"    {case_label} {note}")

    # Summary
    non_silence_cases = sum(1 for c in TEST_CASES if not c["expect_silence"])
    non_silence_calls = non_silence_cases * runs_per_case
    pct_exact = int(100 * total_exact_one_valid / non_silence_calls) if non_silence_calls else 0
    pct_pass  = int(100 * total_pass / total_calls) if total_calls else 0

    threshold = 80
    print(f"\n{'=' * 65}")
    print(f"  Overall ({total_calls} calls, {runs_per_case} runs/case)")
    print(f"{'=' * 65}")
    print(f"  Overall pass (tag or correct silence) : {total_pass}/{total_calls} ({pct_pass}%)")
    print(f"  Exactly 1 valid tag (non-silence cases): {total_exact_one_valid}/{non_silence_calls} ({pct_exact}%)")

    print(f"\nDIAGNOSIS (threshold: >={threshold}% exactly-1-valid-tag on non-silence cases):")
    if pct_exact >= threshold:
        print(f"  VIABLE — {pct_exact}% meets threshold. Proactive responses are expressive.")
    elif pct_exact >= 60:
        print(f"  MARGINAL — {pct_exact}%. Below threshold; consider strengthening reminder.")
    else:
        print(f"  NOT VIABLE — {pct_exact}%. Proactive responses are missing express tags.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Test that proactive intervention responses include valid [express(...)] tags."
    )
    parser.add_argument(
        "--provider",
        default="cerebras",
        choices=list(PROVIDERS.keys()),
    )
    parser.add_argument("--model", default=None)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    model = args.model or provider["default"]
    api_key = os.environ.get(provider["api_key_env"])
    if not api_key:
        print(f"Error: {provider['api_key_env']} not set in environment or .env/.env.local")
        raise SystemExit(1)

    client = OpenAI(api_key=api_key, base_url=provider["base_url"])
    extra_body   = provider.get("model_extra_body", {}).get(model)
    extra_params = provider.get("extra_params")

    test_proactive(client, model, args.runs, extra_body=extra_body, extra_params=extra_params)


if __name__ == "__main__":
    main()
