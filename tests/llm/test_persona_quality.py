"""
TARS persona response quality test.

Tests two problem areas identified during evaluation prep:

  1. casual_deflection — conversational questions should get dry wit,
     NOT system-status lists ("power core stable, sensors calibrated, ...")

  2. proactive_quality — proactive injection responses should be:
     - task-relevant when task_context is set
     - brief (one sentence)
     - {"action": "silence"} on probe #2

Graded per response:
  - brevity:    spoken text ≤ 25 words (casual), ≤ 15 words (proactive)
  - no_enum:    no comma-separated list of 3+ technical terms
  - no_jargon:  none of the known space-robot filler phrases
  - task_match: (proactive only) response mentions task when task_context provided
  - silence:    (proactive probe #2 only) returns {"action": "silence"}

Run from project root:
    python tests/llm/test_persona_quality.py
    python tests/llm/test_persona_quality.py --category casual
    python tests/llm/test_persona_quality.py --category proactive
    python tests/llm/test_persona_quality.py --runs 3
    python tests/llm/test_persona_quality.py --provider google
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


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def get_system_prompt() -> str:
    from character.prompts import load_character
    _, _, system_msg = load_character()
    return system_msg["content"]


# ---------------------------------------------------------------------------
# Anti-pattern detectors
# ---------------------------------------------------------------------------

EXPRESS_TAG_RE = re.compile(r'\[express\([^)]+\)\]', re.IGNORECASE)

# 3+ items joined by commas, each 1-3 words — typical system-enumeration pattern
ENUM_RE = re.compile(
    r'(?:\w[\w\s]{0,20},\s*){2,}\w[\w\s]{0,20}(?:stable|linked|functional|calibrated|nominal|operational|active|online|ready)',
    re.IGNORECASE,
)

# Known space-robot filler phrases that should not appear in casual responses
JARGON_PHRASES = [
    "systems nominal",
    "power core",
    "locomotion functional",
    "sensors calibrated",
    "processing at full capacity",
    "communications linked",
    "navigation directive",
    "vacuum",
    "microgravity",
    "atmospheric",
    "terrestrial",
    "sensor scan",
    "movement command",
    "locomotion",
    "colonization protocol",
]


def strip_express_tag(text: str) -> str:
    return EXPRESS_TAG_RE.sub("", text).strip()


def word_count(text: str) -> int:
    return len(text.split())


def find_jargon(text: str) -> list[str]:
    lower = text.lower()
    return [p for p in JARGON_PHRASES if p in lower]


def has_enum(text: str) -> bool:
    return bool(ENUM_RE.search(text))


def is_silence_response(text: str) -> bool:
    """True if the response is (or contains) {"action": "silence"}."""
    stripped = text.strip()
    try:
        obj = json.loads(stripped)
        if isinstance(obj, dict) and obj.get("action") == "silence":
            return True
    except json.JSONDecodeError:
        pass
    return '"action"' in stripped and '"silence"' in stripped


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class QualityResult:
    raw_text: str
    spoken: str          # after stripping express tag
    wc: int
    jargon_found: list[str]
    enum_found: bool
    is_silence: bool
    error: Optional[str] = None

    # Per-check flags (populated by grader)
    brevity_ok: bool = False
    no_enum_ok: bool = False
    no_jargon_ok: bool = False

    def overall_pass(self, checks: list[str]) -> bool:
        return all(getattr(self, c + "_ok") for c in checks)


# ---------------------------------------------------------------------------
# Single LLM call
# ---------------------------------------------------------------------------

def _call(client, model, messages, extra_params) -> QualityResult:
    kwargs = dict(model=model, messages=messages, max_tokens=200)
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
        return QualityResult(
            raw_text="", spoken="", wc=0,
            jargon_found=[], enum_found=False, is_silence=False,
            error=str(e),
        )

    raw = (resp.choices[0].message.content or "").strip()
    spoken = strip_express_tag(raw)
    return QualityResult(
        raw_text=raw,
        spoken=spoken,
        wc=word_count(spoken),
        jargon_found=find_jargon(spoken),
        enum_found=has_enum(spoken),
        is_silence=is_silence_response(spoken),
    )


# ---------------------------------------------------------------------------
# Test case definitions
# ---------------------------------------------------------------------------

@dataclass
class CasualCase:
    user_msg: str
    description: str
    max_words: int = 25


@dataclass
class ProactiveCase:
    description: str
    trigger_type: str       # silence / hesitation / confusion
    context_snippet: str
    task_context: str       # "" means no task
    probe_num: int          # 1 or 2
    expect_silence: bool    # True if probe_num >= 2
    task_keywords: list[str] = field(default_factory=list)  # words expected in response when task_context set
    max_words: int = 15


CASUAL_CASES: list[CasualCase] = [
    CasualCase(
        "How are you doing?",
        "status greeting — should NOT say 'all systems nominal'",
    ),
    CasualCase(
        "What do you do here at the desk?",
        "desk question — should deflect with wit, NOT list workstation tasks",
    ),
    CasualCase(
        "What can you do?",
        "capabilities question — should NOT enumerate systems or functions",
    ),
    CasualCase(
        "Tell me about yourself.",
        "self-description — should be brief and dry, NOT spec-sheet",
        max_words=30,
    ),
    CasualCase(
        "Are you ready?",
        "readiness check — should NOT list subsystem statuses",
    ),
]


def build_proactive_injection(trigger_type: str, context_snippet: str,
                               task_context: str = "", probe_num: int = 1) -> str:
    """Reproduce the exact system message from _fire_intervention."""
    task_line = f"\nTask context: {task_context}" if task_context else ""
    probe_note = (
        f"\n\nThis is unanswered probe #{probe_num}. Previous probes got no user response. "
        f"If this is probe #2 or higher, return {{\"action\": \"silence\"}} — "
        f"the user is likely away or ignoring you."
        if probe_num >= 2
        else ""
    )
    return (
        f"[PROACTIVE DETECTION - {trigger_type.upper()}]: "
        f"The user has not directly addressed you, but the proactive monitor "
        f"has detected signs they may need help."
        f"{task_line}\n"
        f'Recent context: "{context_snippet}"\n\n'
        f"You have three options:\n"
        f"1. Offer a gentle Notification relevant to what the user is doing\n"
        f"2. Offer a Suggestion if the user has been struggling for a while\n"
        f"3. Return exactly {{\"action\": \"silence\"}} if this seems like a false positive\n\n"
        f"Default to Notification (option 1). Never give the answer directly."
        f"{probe_note}"
    )


PROACTIVE_CASES: list[ProactiveCase] = [
    ProactiveCase(
        description="silence, no task context — neutral check-in, brief",
        trigger_type="silence",
        context_snippet="Yeah, I mean, like... um...",
        task_context="",
        probe_num=1,
        expect_silence=False,
        task_keywords=[],
        max_words=20,
    ),
    ProactiveCase(
        # Response should be inferred from transcript ("rivers"/"seven letters"),
        # NOT generic "want a hint?" or "tricky one" language.
        # task_keywords intentionally empty: Issue A removes hard-coded task labels.
        description="silence, crossword transcript — infer from transcript, no 'hint'/'tricky' language",
        trigger_type="silence",
        context_snippet="Seven letters, something about rivers...",
        task_context="",
        probe_num=1,
        expect_silence=False,
        task_keywords=[],
        max_words=20,
    ),
    ProactiveCase(
        description="hesitation, crossword transcript — brief, relevant, inferred from context",
        trigger_type="hesitation",
        context_snippet="um... uh... hmm, I'm not sure about this one",
        task_context="",
        probe_num=1,
        expect_silence=False,
        task_keywords=[],
        max_words=20,
    ),
    ProactiveCase(
        description="probe #2 — must return silence",
        trigger_type="silence",
        context_snippet="Seven letters, something about rivers...",
        task_context="",
        probe_num=2,
        expect_silence=True,
        task_keywords=[],
    ),
    ProactiveCase(
        description="confusion, no task context — generic one-sentence offer",
        trigger_type="confusion",
        context_snippet="I'm so confused about this",
        task_context="",
        probe_num=1,
        expect_silence=False,
        task_keywords=[],
    ),
]


# ---------------------------------------------------------------------------
# Grade a casual result
# ---------------------------------------------------------------------------

def grade_casual(r: QualityResult, max_words: int) -> list[str]:
    """Returns list of failure descriptions (empty = pass)."""
    failures = []
    if r.wc > max_words:
        failures.append(f"TOO_LONG({r.wc}>{max_words}w)")
    if r.enum_found:
        failures.append("ENUM_LIST")
    if r.jargon_found:
        failures.append(f"JARGON({', '.join(r.jargon_found)})")
    return failures


# ---------------------------------------------------------------------------
# Grade a proactive result
# ---------------------------------------------------------------------------

# Generic phrases that should no longer appear in proactive responses (Issue A).
PROACTIVE_BANNED = ["tricky one", "want a hint", "need a hint", "would you like a hint"]


def grade_proactive(r: QualityResult, case: ProactiveCase) -> list[str]:
    failures = []
    if case.expect_silence:
        if not r.is_silence:
            failures.append(f'EXPECTED_SILENCE(got: "{r.spoken[:50]}")')
    else:
        # Empty non-silence response: model returned only an express tag or null.
        # In production this is caught by SilenceFilter. Flagged here as a
        # reliability issue, not a prompt issue.
        if r.wc == 0 and not r.is_silence:
            failures.append("EMPTY_RESPONSE(model reliability)")
        if r.wc > case.max_words:
            failures.append(f"TOO_LONG({r.wc}>{case.max_words}w)")
        if case.task_keywords:
            matched = any(kw.lower() in r.spoken.lower() for kw in case.task_keywords)
            if not matched and not r.is_silence:
                failures.append(f"NO_TASK_MATCH(expected one of: {case.task_keywords})")
        banned_hit = [p for p in PROACTIVE_BANNED if p in r.spoken.lower()]
        if banned_hit:
            failures.append(f"BANNED_PHRASE({banned_hit})")
    return failures


# ---------------------------------------------------------------------------
# Run categories
# ---------------------------------------------------------------------------

def run_casual(client, model, system, runs, extra_params):
    print(f"\n{'=' * 70}")
    print("  CATEGORY: CASUAL DEFLECTION")
    print(f"{'=' * 70}")

    passed = partial = failed = 0

    for case in CASUAL_CASES:
        print(f"\n  [{case.description}]")
        print(f"  User: \"{case.user_msg}\"")
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": case.user_msg},
        ]
        case_pass = 0

        for run_idx in range(runs):
            r = _call(client, model, messages, extra_params)
            if r.error:
                print(f"    run {run_idx+1}: ERROR {r.error}")
                time.sleep(CALL_DELAY)
                continue

            failures = grade_casual(r, case.max_words)
            ok = len(failures) == 0
            if ok:
                case_pass += 1

            spoken_snip = r.spoken[:70].replace("\n", " ")
            status = "OK  " if ok else "FAIL"
            fail_str = "  !! " + " | ".join(failures) if failures else ""
            print(f"    run {run_idx+1}: [{status}]  ({r.wc}w)  \"{spoken_snip}\"{fail_str}")

            if run_idx < runs - 1:
                time.sleep(CALL_DELAY)

        if case_pass == runs:
            verdict, passed = "[PASS]", passed + 1
        elif case_pass == 0:
            verdict, failed = "[FAIL]", failed + 1
        else:
            verdict, partial = f"[PARTIAL {case_pass}/{runs}]", partial + 1
        print(f"  {verdict} {case_pass}/{runs}")

    print(f"\n  --- CASUAL SUMMARY ---")
    print(f"  Cases: {passed+partial+failed}  |  PASS: {passed}  PARTIAL: {partial}  FAIL: {failed}")
    return passed, partial, failed, passed + partial + failed


def run_proactive(client, model, system, runs, extra_params):
    print(f"\n{'=' * 70}")
    print("  CATEGORY: PROACTIVE QUALITY")
    print(f"{'=' * 70}")

    passed = partial = failed = 0

    for case in PROACTIVE_CASES:
        print(f"\n  [{case.description}]")
        if case.task_context:
            print(f"  task_context: \"{case.task_context[:60]}...\"")
        print(f"  probe_num: {case.probe_num}  expect_silence: {case.expect_silence}")

        injection = build_proactive_injection(
            case.trigger_type, case.context_snippet,
            case.task_context, case.probe_num,
        )

        # Simulate a brief prior conversation so context makes sense
        prior_user = case.context_snippet
        prior_assistant = "Noted. [express(neutral, low)]"

        messages = [
            {"role": "system",    "content": system},
            {"role": "user",      "content": prior_user},
            {"role": "assistant", "content": prior_assistant},
            {"role": "system",    "content": injection},
        ]
        case_pass = 0

        for run_idx in range(runs):
            r = _call(client, model, messages, extra_params)
            if r.error:
                print(f"    run {run_idx+1}: ERROR {r.error}")
                time.sleep(CALL_DELAY)
                continue

            failures = grade_proactive(r, case)
            ok = len(failures) == 0
            if ok:
                case_pass += 1

            spoken_snip = r.spoken[:70].replace("\n", " ")
            silence_flag = " [SILENCE]" if r.is_silence else ""
            status = "OK  " if ok else "FAIL"
            fail_str = "  !! " + " | ".join(failures) if failures else ""
            print(
                f"    run {run_idx+1}: [{status}]  ({r.wc}w){silence_flag}"
                f"  \"{spoken_snip}\"{fail_str}"
            )

            if run_idx < runs - 1:
                time.sleep(CALL_DELAY)

        if case_pass == runs:
            verdict, passed = "[PASS]", passed + 1
        elif case_pass == 0:
            verdict, failed = "[FAIL]", failed + 1
        else:
            verdict, partial = f"[PARTIAL {case_pass}/{runs}]", partial + 1
        print(f"  {verdict} {case_pass}/{runs}")

    print(f"\n  --- PROACTIVE SUMMARY ---")
    print(f"  Cases: {passed+partial+failed}  |  PASS: {passed}  PARTIAL: {partial}  FAIL: {failed}")
    return passed, partial, failed, passed + partial + failed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_CATEGORIES = {
    "casual":    run_casual,
    "proactive": run_proactive,
}


def main():
    parser = argparse.ArgumentParser(
        description="TARS persona response quality diagnostic."
    )
    parser.add_argument("--provider", default="cerebras", choices=list(PROVIDERS))
    parser.add_argument("--model",    default=None)
    parser.add_argument("--runs",     type=int, default=2, help="Runs per case (default: 2)")
    parser.add_argument("--category", choices=list(ALL_CATEGORIES.keys()) + ["all"], default="all")
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    model = args.model or provider["default"]
    api_key = os.environ.get(provider["api_key_env"])
    if not api_key:
        print(f"Error: {provider['api_key_env']} not set")
        raise SystemExit(1)

    client = OpenAI(api_key=api_key, base_url=provider["base_url"])
    extra_params = provider.get("extra_params")

    system = get_system_prompt()

    print(f"\nProvider : {args.provider}")
    print(f"Model    : {model}")
    print(f"Runs/case: {args.runs}")
    print(f"Category : {args.category}")
    print(f"Prompt   : {len(system)} chars")
    if extra_params:
        print(f"Extra    : {extra_params}")

    cats = (
        list(ALL_CATEGORIES.items())
        if args.category == "all"
        else [(args.category, ALL_CATEGORIES[args.category])]
    )

    grand_pass = grand_partial = grand_fail = grand_total = 0
    for cat_name, runner in cats:
        p, pt, f, t = runner(client, model, system, args.runs, extra_params)
        grand_pass  += p
        grand_partial += pt
        grand_fail  += f
        grand_total += t

    if len(cats) > 1:
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
            print(f"\n  RESULT: {grand_fail} case(s) failing — see details above")


if __name__ == "__main__":
    main()
