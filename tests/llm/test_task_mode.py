"""
Task mode integration test.

Tests the full task mode pipeline: tool-call trigger, silence compliance
while in task mode, correct response to direct questions, and proactive
probe behavior in task mode context.

Categories
----------
  normalization       Unit tests — no LLM. Validates active_flag logic.
  tool_trigger        LLM calls set_task_mode at right times (no tool call on normal chat).
  silence_compliance  With task mode system prompt active, think-aloud → silence.
  direct_questions    With task mode active, direct "TARS + question" → real response.
  proactive_task      Proactive probe in task mode context → default to silence.

The silence_compliance category tests the real failure observed in logs:
  - "Um, five words. Poisonous." → should return {"action": "silence"}
  - "Yeah, it's ink, I guess." → silence (user arrived at answer alone)
  - "I think it's luck." → silence

Run from project root:
    python tests/llm/test_task_mode.py
    python tests/llm/test_task_mode.py --category silence_compliance
    python tests/llm/test_task_mode.py --runs 3
    python tests/llm/test_task_mode.py --provider cerebras
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

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

EXPRESS_TAG_RE = re.compile(r'\[express\([^)]+\)\]', re.IGNORECASE)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

def get_system_prompt(task_mode: Optional[str] = None) -> str:
    """Build system prompt, optionally with task mode section active."""
    from character.prompts import load_character, build_tars_system_prompt, load_persona_ini, load_tars_json
    import os as _os
    char_dir = _os.path.join(_os.path.dirname(__file__), "..", "..", "src", "character")
    if task_mode is None:
        _, _, system_msg = load_character(char_dir)
        return system_msg["content"]
    else:
        from character.prompts import load_persona_ini as _lp, load_tars_json as _lt
        persona_params = _lp(_os.path.join(char_dir, "persona.ini"))
        tars_data = _lt(_os.path.join(char_dir, "TARS.json"))
        msg = build_tars_system_prompt(persona_params, tars_data, task_mode=task_mode)
        return msg["content"]


# ---------------------------------------------------------------------------
# Tool schema for set_task_mode
# ---------------------------------------------------------------------------

SET_TASK_MODE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_task_mode",
        "description": (
            "Toggle task mode when the user starts or stops a focused activity. "
            "Call with a mode like 'crossword', 'coding', 'reading', 'thinking' "
            "when the user announces they're working on something. "
            "Call with 'off' when they're done."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": (
                        "The task type (e.g. 'crossword', 'coding', 'reading', 'thinking') "
                        "or 'off' to exit task mode."
                    ),
                },
            },
            "required": ["mode"],
        },
    },
}

# Prior conversation establishing task mode context (used in silence/direct/proactive tests)
TASK_MODE_PRIOR = [
    {
        "role": "user",
        "content": "Hey TARS, I'm going to work on a crossword and think aloud, I want you to just listen.",
    },
    {
        "role": "assistant",
        "content": "Task mode: crossword. [express(neutral, low)]",
    },
]


# ---------------------------------------------------------------------------
# LLM call helpers
# ---------------------------------------------------------------------------

def _call_text(client, model, messages, extra_params) -> tuple[str, Optional[str]]:
    """Returns (response_text, error_string).

    max_tokens=1000: gpt-oss-120b (DeepSeek) has internal reasoning that
    consumes tokens before the visible response. 200 causes finish_reason=length
    with content=None on any response that requires thinking.
    """
    kwargs = dict(model=model, messages=messages, max_tokens=1000, temperature=0.3)
    if extra_params:
        kwargs.update(extra_params)
    try:
        resp = client.chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
        return raw, None
    except Exception as e:
        return "", str(e)


def _call_with_tools(client, model, messages, extra_params) -> tuple[list, str, Optional[str]]:
    """Returns (tool_calls, response_text, error_string)."""
    kwargs = dict(
        model=model, messages=messages,
        tools=[SET_TASK_MODE_TOOL], tool_choice="auto",
        max_tokens=1000, temperature=0.3,
    )
    if extra_params:
        kwargs.update(extra_params)
    try:
        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        return (choice.message.tool_calls or []), (choice.message.content or ""), None
    except Exception as e:
        return [], "", str(e)


def is_silence_response(text: str) -> bool:
    """True if the text is (or contains) {"action": "silence"}."""
    stripped = EXPRESS_TAG_RE.sub("", text).strip()
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict) and obj.get("action") == "silence":
            return True
    except json.JSONDecodeError:
        pass
    return '"action"' in stripped and '"silence"' in stripped


def strip_express_tag(text: str) -> str:
    return EXPRESS_TAG_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# 1. Normalization — unit tests, no LLM
# ---------------------------------------------------------------------------

def run_normalization() -> tuple[int, int, int, int]:
    """Test the active_flag logic from the set_task_mode handler."""
    print(f"\n{'=' * 70}")
    print("  CATEGORY: NORMALIZATION (no LLM)")
    print(f"{'=' * 70}")

    def active_flag(mode_raw: str) -> bool:
        mode = (mode_raw or "").strip().lower()
        return mode not in ("", "off", "none", "disable", "disabled")

    cases = [
        ("OFF",            False),
        ("off",            False),
        ("None",           False),
        ("none",           False),
        ("",               False),
        ("disable",        False),
        ("disabled",       False),
        ("  crossword  ",  True),
        ("reading",        True),
        ("CODING",         True),
        ("thinking",       True),
    ]

    passed = failed = 0
    for raw, expected in cases:
        got = active_flag(raw)
        ok = got == expected
        label = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{label}]  active_flag({raw!r}) == {expected}  (got {got})")

    total = passed + failed
    print(f"\n  --- NORMALIZATION SUMMARY ---")
    print(f"  Cases: {total}  |  PASS: {passed}  FAIL: {failed}")
    return passed, 0, failed, total


# ---------------------------------------------------------------------------
# 2. Tool trigger — does the LLM call set_task_mode correctly?
# ---------------------------------------------------------------------------

@dataclass
class TriggerCase:
    description: str
    message: str
    prior: Optional[list]         # None = no prior history
    expect_call: bool             # True = tool call expected
    expect_mode: Optional[str]    # exact value expected, None = any non-off

TRIGGER_CASES: list[TriggerCase] = [
    TriggerCase(
        "crossword announcement → set_task_mode(crossword)",
        "I'm going to work on a crossword",
        None, True, "crossword",
    ),
    TriggerCase(
        "thinking aloud announcement → set_task_mode(thinking)",
        "Let me think about this quietly",
        None, True, "thinking",
    ),
    TriggerCase(
        "reading announcement → set_task_mode(reading)",
        "I'm reading an article, give me a sec",
        None, True, "reading",
    ),
    TriggerCase(
        "done after task → set_task_mode(off)",
        "Okay I'm done",
        [
            {"role": "user", "content": "I'm going to work on a crossword"},
            {"role": "assistant", "content": "Task mode: crossword. [express(neutral, low)]"},
        ],
        True, "off",
    ),
    TriggerCase(
        "weather question → no tool call",
        "What's the weather like?",
        None, False, None,
    ),
    TriggerCase(
        "joke request → no tool call",
        "Tell me a joke",
        None, False, None,
    ),
    TriggerCase(
        "how are you → no tool call",
        "How are you?",
        None, False, None,
    ),
]


def run_tool_trigger(client, model, system_normal: str, runs: int, extra_params) -> tuple[int, int, int, int]:
    print(f"\n{'=' * 70}")
    print("  CATEGORY: TOOL TRIGGER")
    print(f"{'=' * 70}")

    passed = partial = failed = 0

    for case in TRIGGER_CASES:
        print(f"\n  [{case.description}]")
        print(f"  User: \"{case.message}\"")

        case_pass = 0
        for run_idx in range(runs):
            msgs = [{"role": "system", "content": system_normal}]
            if case.prior:
                msgs.extend(case.prior)
            msgs.append({"role": "user", "content": case.message})

            tool_calls, text, err = _call_with_tools(client, model, msgs, extra_params)
            if err:
                print(f"    run {run_idx+1}: ERROR {err}")
                time.sleep(CALL_DELAY)
                continue

            tool_called = len(tool_calls) > 0
            mode_got = None
            if tool_called:
                args = json.loads(tool_calls[0].function.arguments or "{}")
                mode_got = (args.get("mode") or "").strip().lower()

            call_ok = tool_called == case.expect_call
            mode_ok = True
            if case.expect_call and tool_called and case.expect_mode is not None:
                mode_ok = mode_got == case.expect_mode

            ok = call_ok and mode_ok
            if ok:
                case_pass += 1

            call_info = f"called={tool_called} mode={mode_got!r}" if tool_called else "no call"
            status = "OK  " if ok else "FAIL"
            fail_parts = []
            if not call_ok:
                fail_parts.append(f"expected_call={case.expect_call}")
            if not mode_ok:
                fail_parts.append(f"expected_mode={case.expect_mode!r}")
            fail_str = "  !! " + " | ".join(fail_parts) if fail_parts else ""
            print(f"    run {run_idx+1}: [{status}]  {call_info}{fail_str}")
            time.sleep(CALL_DELAY)

        if case_pass == runs:
            verdict, passed = "[PASS]", passed + 1
        elif case_pass == 0:
            verdict, failed = "[FAIL]", failed + 1
        else:
            verdict, partial = f"[PARTIAL {case_pass}/{runs}]", partial + 1
        print(f"  {verdict} {case_pass}/{runs}")

    total = passed + partial + failed
    print(f"\n  --- TOOL TRIGGER SUMMARY ---")
    print(f"  Cases: {total}  |  PASS: {passed}  PARTIAL: {partial}  FAIL: {failed}")
    return passed, partial, failed, total


# ---------------------------------------------------------------------------
# 3. Silence compliance — with task mode system prompt, fragments → silence
#    These are the actual cases that failed in production.
# ---------------------------------------------------------------------------

@dataclass
class SilenceCase:
    description: str
    message: str

SILENCE_CASES: list[SilenceCase] = [
    # Real failures from production log (2026-03-03)
    SilenceCase("fragment: clue + single word",          "Um, five words. Poisonous."),
    SilenceCase("fragment: partial sentence",             "So basically."),
    SilenceCase("fragment: incomplete thought",           "Uh, there's."),
    SilenceCase("fragment: user reached answer alone",   "Yeah, it's ink, I guess."),
    SilenceCase("fragment: user thinking through answer","I think it's luck."),
    SilenceCase("fragment: user proposing answer",       "Maybe it's bin."),
    # Additional edge cases
    SilenceCase("fragment: acknowledgement + filler",    "Okay, um."),
    SilenceCase("fragment: pure hesitation",             "Hmm."),
    SilenceCase("fragment: partial self-talk",           "Let me think..."),
    SilenceCase("fragment: number + direction",          "Down, number 5."),
    SilenceCase("fragment: user muttering a word",       "Toxic."),
    SilenceCase("fragment: user checking own answer",    "I don't know. I don't know."),
]


def run_silence_compliance(client, model, system_task: str, runs: int, extra_params) -> tuple[int, int, int, int]:
    print(f"\n{'=' * 70}")
    print("  CATEGORY: SILENCE COMPLIANCE (task mode active)")
    print("  All messages are think-aloud fragments. Expected: {\"action\": \"silence\"}")
    print(f"{'=' * 70}")

    passed = partial = failed = 0

    for case in SILENCE_CASES:
        print(f"\n  [{case.description}]")
        print(f"  User: \"{case.message}\"")

        case_pass = 0
        for run_idx in range(runs):
            msgs = [{"role": "system", "content": system_task}]
            msgs.extend(TASK_MODE_PRIOR)
            msgs.append({"role": "user", "content": case.message})

            raw, err = _call_text(client, model, msgs, extra_params)
            if err:
                print(f"    run {run_idx+1}: ERROR {err}")
                time.sleep(CALL_DELAY)
                continue

            spoken = strip_express_tag(raw)
            is_silent = is_silence_response(raw)
            ok = is_silent
            if ok:
                case_pass += 1

            status = "OK  " if ok else "FAIL"
            snip = spoken[:60].replace("\n", " ") if not is_silent else '{"action": "silence"}'
            fail_str = '  !! SPOKE INSTEAD OF SILENCE' if not ok else ""
            print(f"    run {run_idx+1}: [{status}]  \"{snip}\"{fail_str}")
            time.sleep(CALL_DELAY)

        if case_pass == runs:
            verdict, passed = "[PASS]", passed + 1
        elif case_pass == 0:
            verdict, failed = "[FAIL]", failed + 1
        else:
            verdict, partial = f"[PARTIAL {case_pass}/{runs}]", partial + 1
        print(f"  {verdict} {case_pass}/{runs}")

    total = passed + partial + failed
    print(f"\n  --- SILENCE COMPLIANCE SUMMARY ---")
    print(f"  Cases: {total}  |  PASS: {passed}  PARTIAL: {partial}  FAIL: {failed}")
    return passed, partial, failed, total


# ---------------------------------------------------------------------------
# 4. Direct questions — with task mode active, direct "TARS + question" → respond
# ---------------------------------------------------------------------------

@dataclass
class DirectCase:
    description: str
    message: str

DIRECT_CASES: list[DirectCase] = [
    DirectCase(
        "explicit ask with name",
        "TARS, what's a five-letter word for poisonous?",
    ),
    DirectCase(
        "explicit give up",
        "I give up, TARS, what's the answer for 3 down?",
    ),
    DirectCase(
        "direct help request with name and specific clue",
        "TARS, what's a seven-letter word meaning 'opposite of war'?",
    ),
]


def run_direct_questions(client, model, system_task: str, runs: int, extra_params) -> tuple[int, int, int, int]:
    print(f"\n{'=' * 70}")
    print("  CATEGORY: DIRECT QUESTIONS (task mode active)")
    print("  User explicitly asks TARS. Expected: real response, NOT silence.")
    print(f"{'=' * 70}")

    passed = partial = failed = 0

    for case in DIRECT_CASES:
        print(f"\n  [{case.description}]")
        print(f"  User: \"{case.message}\"")

        case_pass = 0
        for run_idx in range(runs):
            msgs = [{"role": "system", "content": system_task}]
            msgs.extend(TASK_MODE_PRIOR)
            msgs.append({"role": "user", "content": case.message})

            raw, err = _call_text(client, model, msgs, extra_params)
            if err:
                print(f"    run {run_idx+1}: ERROR {err}")
                time.sleep(CALL_DELAY)
                continue

            is_silent = is_silence_response(raw)
            spoken = strip_express_tag(raw)
            wc = len(spoken.split())
            # Pass = NOT silence AND has actual content (1+ word — single-word answers are valid)
            ok = not is_silent and wc >= 1
            if ok:
                case_pass += 1

            status = "OK  " if ok else "FAIL"
            snip = spoken[:60].replace("\n", " ") if spoken else "(empty)"
            fail_note = "  !! STAYED SILENT" if is_silent else ("  !! EMPTY" if wc < 1 else "")
            print(f"    run {run_idx+1}: [{status}]  ({wc}w) \"{snip}\"{fail_note}")
            time.sleep(CALL_DELAY)

        if case_pass == runs:
            verdict, passed = "[PASS]", passed + 1
        elif case_pass == 0:
            verdict, failed = "[FAIL]", failed + 1
        else:
            verdict, partial = f"[PARTIAL {case_pass}/{runs}]", partial + 1
        print(f"  {verdict} {case_pass}/{runs}")

    total = passed + partial + failed
    print(f"\n  --- DIRECT QUESTIONS SUMMARY ---")
    print(f"  Cases: {total}  |  PASS: {passed}  PARTIAL: {partial}  FAIL: {failed}")
    return passed, partial, failed, total


# ---------------------------------------------------------------------------
# 5. Proactive task silence — proactive probe in task mode → default to silence
# ---------------------------------------------------------------------------

def build_proactive_task_injection(trigger_type: str, context_snippet: str,
                                    task_context: str, probe_num: int = 1) -> str:
    """Reproduce the task-mode branch of _fire_intervention."""
    probe_note = (
        f"\n\nThis is unanswered probe #{probe_num}. Previous probes got no user response. "
        f"If this is probe #2 or higher, return {{\"action\": \"silence\"}} — "
        f"the user is likely away or ignoring you."
        if probe_num >= 2
        else ""
    )
    return (
        f"[PROACTIVE DETECTION - {trigger_type.upper()}]: "
        f"The user is in task mode ({task_context}) and has been silent. "
        f'Recent context: "{context_snippet}"\n\n'
        f"Task mode rule: default to {{\"action\": \"silence\"}}. "
        f"Only speak if the recent context contains a direct, unresolved question "
        f"the user cannot answer. "
        f"Thinking aloud, fragments, and partial progress are NOT requests for help. "
        f"If in any doubt, return exactly {{\"action\": \"silence\"}}."
        f"{probe_note}"
    )


@dataclass
class ProactiveTaskCase:
    description: str
    trigger_type: str
    context_snippet: str
    expect_silence: bool   # True = must be silence, False = may speak (brief)

PROACTIVE_TASK_CASES: list[ProactiveTaskCase] = [
    ProactiveTaskCase(
        "silence after think-aloud fragments → silence",
        "silence",
        "Um, five words. Poisonous. Uh, I think...",
        expect_silence=True,
    ),
    ProactiveTaskCase(
        "silence after user got an answer → silence",
        "silence",
        "Yeah, it's ink, I guess.",
        expect_silence=True,
    ),
    ProactiveTaskCase(
        "probe #2 after task-mode silence → always silence",
        "silence",
        "I think it might be... hmm.",
        expect_silence=True,
    ),
    ProactiveTaskCase(
        "hesitation fragments in task mode → silence",
        "hesitation",
        "um... uh... hmm... I'm not sure...",
        expect_silence=True,
    ),
]


def run_proactive_task(client, model, system_task: str, runs: int, extra_params) -> tuple[int, int, int, int]:
    print(f"\n{'=' * 70}")
    print("  CATEGORY: PROACTIVE TASK SILENCE")
    print("  Proactive probe fired while in task mode. Expected: silence.")
    print(f"{'=' * 70}")

    passed = partial = failed = 0

    for i, case in enumerate(PROACTIVE_TASK_CASES):
        probe_num = 2 if i == 2 else 1
        print(f"\n  [{case.description}]")

        injection = build_proactive_task_injection(
            case.trigger_type, case.context_snippet, "crossword", probe_num
        )

        case_pass = 0
        for run_idx in range(runs):
            msgs = [{"role": "system", "content": system_task}]
            msgs.extend(TASK_MODE_PRIOR)
            # Add a couple of prior think-aloud turns to make context realistic
            msgs.append({"role": "user", "content": case.context_snippet})
            msgs.append({"role": "assistant", "content": '{"action": "silence"}'})
            msgs.append({"role": "system", "content": injection})

            raw, err = _call_text(client, model, msgs, extra_params)
            if err:
                print(f"    run {run_idx+1}: ERROR {err}")
                time.sleep(CALL_DELAY)
                continue

            is_silent = is_silence_response(raw)
            spoken = strip_express_tag(raw)
            wc = len(spoken.split()) if not is_silent else 0

            if case.expect_silence:
                ok = is_silent
            else:
                ok = wc <= 20  # brief is fine

            if ok:
                case_pass += 1

            status = "OK  " if ok else "FAIL"
            snip = '{"action": "silence"}' if is_silent else spoken[:60].replace("\n", " ")
            fail_note = "  !! SPOKE INSTEAD OF SILENCE" if (case.expect_silence and not is_silent) else ""
            print(f"    run {run_idx+1}: [{status}]  \"{snip}\"{fail_note}")
            time.sleep(CALL_DELAY)

        if case_pass == runs:
            verdict, passed = "[PASS]", passed + 1
        elif case_pass == 0:
            verdict, failed = "[FAIL]", failed + 1
        else:
            verdict, partial = f"[PARTIAL {case_pass}/{runs}]", partial + 1
        print(f"  {verdict} {case_pass}/{runs}")

    total = passed + partial + failed
    print(f"\n  --- PROACTIVE TASK SUMMARY ---")
    print(f"  Cases: {total}  |  PASS: {passed}  PARTIAL: {partial}  FAIL: {failed}")
    return passed, partial, failed, total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_CATEGORIES = {
    "normalization":      None,            # no LLM
    "tool_trigger":       run_tool_trigger,
    "silence_compliance": run_silence_compliance,
    "direct_questions":   run_direct_questions,
    "proactive_task":     run_proactive_task,
}


def main():
    parser = argparse.ArgumentParser(description="Task mode integration test.")
    parser.add_argument("--provider",  default="cerebras", choices=list(PROVIDERS))
    parser.add_argument("--model",     default=None)
    parser.add_argument("--runs",      type=int, default=2)
    parser.add_argument("--category",  choices=list(ALL_CATEGORIES.keys()) + ["all"], default="all")
    args = parser.parse_args()

    cats_to_run = (
        list(ALL_CATEGORIES.keys())
        if args.category == "all"
        else [args.category]
    )

    # Normalization never needs LLM — run it first regardless
    grand_pass = grand_partial = grand_fail = grand_total = 0

    if "normalization" in cats_to_run:
        p, pt, f, t = run_normalization()
        grand_pass += p; grand_partial += pt; grand_fail += f; grand_total += t

    # Remaining categories need LLM
    llm_cats = [c for c in cats_to_run if c != "normalization"]
    if not llm_cats:
        print(f"\n{'=' * 70}")
        _print_grand(grand_pass, grand_partial, grand_fail, grand_total)
        return

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

    system_normal = get_system_prompt(task_mode=None)
    system_task   = get_system_prompt(task_mode="crossword")
    print(f"Prompt (normal): {len(system_normal)} chars")
    print(f"Prompt (task):   {len(system_task)} chars")

    runners = {
        "tool_trigger":       (run_tool_trigger,       system_normal),
        "silence_compliance": (run_silence_compliance, system_task),
        "direct_questions":   (run_direct_questions,   system_task),
        "proactive_task":     (run_proactive_task,     system_task),
    }

    for cat in llm_cats:
        runner_fn, system = runners[cat]
        p, pt, f, t = runner_fn(client, model, system, args.runs, extra_params)
        grand_pass += p; grand_partial += pt; grand_fail += f; grand_total += t

    print(f"\n{'=' * 70}")
    _print_grand(grand_pass, grand_partial, grand_fail, grand_total)


def _print_grand(p: int, pt: int, f: int, t: int):
    print("  GRAND TOTAL")
    print(f"{'=' * 70}")
    pct = int(100 * p / t) if t else 0
    print(f"  Cases  : {t}")
    print(f"  PASS   : {p}  ({pct}%)")
    print(f"  PARTIAL: {pt}")
    print(f"  FAIL   : {f}")
    if f == 0 and pt == 0:
        print("\n  RESULT: ALL PASS")
    elif f == 0:
        print("\n  RESULT: PASS with partials — review above")
    else:
        print(f"\n  RESULT: {f} case(s) failing — see details above")


if __name__ == "__main__":
    main()
