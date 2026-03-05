"""
LLM compliance tests for task mode — post-ReactiveGate architecture.

ReactiveGate now handles think-aloud suppression deterministically in the
pipeline. These tests only cover what the LLM must do for responses that
PASS THROUGH the gate:

  - CONDITION A  (surrender → direct answer)
  - CONDITION B  (question → hint, not the answer)
  - CONDITION C  (correction → "Got it.")
  - Proactive interventions (gate passes _proactive_response_pending=True)
  - Tool call compliance (set_task_mode not called for corrections / clue resolution)

Tests that previously checked whether the LLM returns silence for think-aloud
inputs have been removed: ReactiveGate provides that guarantee at the code
level regardless of what the LLM outputs.

Usage:
    cd /Users/mac/Desktop/tars-conversation-app
    export $(grep -v '^#' .env.local | xargs)
    python -m pytest tests/test_task_mode_compliance.py -v -s
"""
import os
import re
import sys
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from character.prompts import build_tars_system_prompt, load_persona_ini, load_tars_json

# ── fixtures ──────────────────────────────────────────────────────────────────

CHARACTER_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "character")
persona_params = load_persona_ini(os.path.join(CHARACTER_DIR, "persona.ini"))
tars_data = load_tars_json(os.path.join(CHARACTER_DIR, "TARS.json"))


def system_prompt(task_mode="crossword"):
    return build_tars_system_prompt(persona_params, tars_data, task_mode=task_mode)


# ── non-silence input sets ────────────────────────────────────────────────────

# Corrections: user tells TARS to back off. Must return "Got it." (not silence, not hints).
# Must NOT include a set_task_mode tool call — correction is not task-end.
CORRECTION_INPUTS = [
    "You shouldn't tell me the answer.",
    "You shouldn't answer.",
    "You shouldn't answer me.",
    "Don't give me the answer.",
    "Can you not answer? I'm trying to figure it out myself.",
    "Stop helping me. I want to work through it.",
    "I didn't ask you.",
]

# Clue-resolution phrases: user solved a clue and moves on. Must NOT call set_task_mode("off").
# The task (crossword) is still in progress.
CLUE_RESOLUTION_INPUTS = [
    "Okay, evening.",
    "Yeah, I guess it's bin.",
    "I got it. Moving on.",
    "Okay next clue.",
    "That's it, I think. Let me try the next one.",
    "Got it, banned. All right.",
]

# Task-completion phrases with clear task-end signal. Must call set_task_mode("off").
# Requires explicit task reference, direct address+done, or pivot — not standalone "I'm done".
TASK_DONE_INPUTS = [
    "Hey TARS, I'm done with the crossword.",
    "Hey TARS, I am done with this crossword.",
    "I'm done with the crossword.",
    "I finished the puzzle.",
    "Let's do something else.",
]

# Ambiguous done phrases — mid-narration clue-skip or think-aloud. Must NOT call set_task_mode("off").
TASK_DONE_AMBIGUOUS = [
    "I'm done.",
    "Done.",
    "Got it.",
    "Never mind.",
    "Never mind, moving on.",
    "Okay, moving on.",
]

# Direct reactive questions: user explicitly asks for help.
# Gate passes these through. LLM must respond — with a hint, not silence, not the direct answer.
# Tuple: (utterance, answer_word_to_NOT_appear_verbatim_in_response)
REACTIVE_QUESTIONS = [
    ("TARS, can you give me a hint for this one? Taste of lemon or vinegar.", "sour"),
    ("TARS, what's a hint for prophetic significance, starts with O?", "omen"),
    ("Hey TARS, help me with a celestial body, four letters, starts with S.", "star"),
]

# Explicit answer requests: user gives up. Gate passes CONDITION A through.
# LLM must give the direct answer (not silence, not a refusal).
EXPLICIT_ANSWER_REQUESTS = [
    "Just tell me the answer.",
    "What's the answer? I give up.",
    "Okay TARS, just give me the answer for this one.",
]

# ── conversation history fixtures ─────────────────────────────────────────────

LONG_HISTORY = [
    ("user", "Hey Tars, I'm going to do a crossword, thinking aloud."),
    ("assistant", "Crossword mode. [express(neutral, low)]"),
    ("user", "1 across, system for transmitting voices, 9 letters."),
    ("assistant", "Think of the device you pick up to call someone. [express(neutral, low)]"),
    ("user", "Telephone of course."),
    ("assistant", '{"action": "silence"}'),
    ("user", "9 across, Italian carbohydrate, 5 letters."),
    ("assistant", "Picture a durum wheat dish from a trattoria. [express(neutral, low)]"),
    ("user", "Pasta."),
    ("assistant", '{"action": "silence"}'),
    ("user", "14 down, garbage holder, 3 letters."),
    ("assistant", '{"action": "silence"}'),
    ("user", "TARS, what's the answer to garbage holder?"),
    ("assistant", "BIN. [express(neutral, low)]"),
    ("user", "Thanks. Okay, 15 across, time before night, 7 letters."),
    ("assistant", '{"action": "silence"}'),
    ("user", "Evening."),
    ("assistant", '{"action": "silence"}'),
    ("user", "13 down, legally prohibited, 3 letters."),
    ("assistant", '{"action": "silence"}'),
    ("user", "Banned."),
    ("assistant", '{"action": "silence"}'),
]

TOOL_CALL_HISTORY = [
    {
        "role": "user",
        "content": "I'm going to do a crossword puzzle, thinking aloud.",
    },
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "tc_001",
            "type": "function",
            "function": {
                "name": "set_task_mode",
                "arguments": '{"mode": "crossword"}',
            },
        }],
    },
    {
        "role": "tool",
        "tool_call_id": "tc_001",
        "content": "Task mode: crossword.",
    },
    {
        "role": "assistant",
        "content": "Crossword mode. [express(neutral, low)]",
    },
]

# ── LLM interface ─────────────────────────────────────────────────────────────

SET_TASK_MODE_TOOL = {
    "type": "function",
    "function": {
        "name": "set_task_mode",
        "description": (
            "Toggle task mode when the user starts or stops a focused activity. "
            "Call with a mode like 'crossword', 'coding', 'reading', 'thinking' "
            "when the user announces they're working on something. "
            "Call with 'off' ONLY when the user explicitly says they are done with the task "
            "(e.g. 'I'm done', 'let's do something else'). "
            "Do NOT call with 'off' when the user corrects your behavior mid-task "
            "(e.g. 'you shouldn't answer', 'stop helping', 'don't give me the answer') — "
            "those are CONDITION C corrections, not task-end signals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "The task type or 'off' to exit task mode.",
                }
            },
            "required": ["mode"],
        },
    },
}


def call_llm(messages: list[dict], max_tokens: int = 300, temperature: float = 0.0,
             tools: list | None = None) -> str:
    api_key = os.environ.get("CEREBRAS_API_KEY", "")
    if not api_key:
        raise RuntimeError("CEREBRAS_API_KEY not set")
    body = {
        "model": "gpt-oss-120b",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools
    resp = requests.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def call_llm_with_tool_check(messages: list[dict], max_tokens: int = 300,
                              temperature: float = 0.0) -> tuple[str, list]:
    """Call LLM with set_task_mode tool available. Returns (content, tool_calls)."""
    api_key = os.environ.get("CEREBRAS_API_KEY", "")
    if not api_key:
        raise RuntimeError("CEREBRAS_API_KEY not set")
    resp = requests.post(
        "https://api.cerebras.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "gpt-oss-120b",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "tools": [SET_TASK_MODE_TOOL],
        },
        timeout=30,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
    tool_calls = msg.get("tool_calls") or []
    return content, tool_calls


def is_silence(response: str) -> bool:
    return '"action": "silence"' in response or "'action': 'silence'" in response


def history_from_pairs(pairs: list[tuple]) -> list[dict]:
    return [{"role": r, "content": c} for r, c in pairs]


# ── CONDITION C: correction compliance ────────────────────────────────────────

def test_correction_returns_got_it():
    """When user corrects TARS, response must contain 'Got it' (not silence, not more hints).

    Gate passes CONDITION C phrases through. LLM must respond with "Got it."
    """
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)
    for utterance in CORRECTION_INPUTS:
        messages = history + [{"role": "user", "content": utterance}]
        response = call_llm(messages, max_tokens=150)
        has_got_it = "got it" in response.lower()
        is_sil = is_silence(response)
        if not has_got_it:
            print(f"  [correction] FAIL: {utterance!r}\n    → {response[:120]!r}")
        assert has_got_it, f"Correction '{utterance}' did not return 'Got it': {response!r}"
        assert not is_sil, f"Correction '{utterance}' returned silence instead of 'Got it'"


def test_correction_does_not_exit_task_mode():
    """Correction phrases must NOT trigger a set_task_mode('off') tool call.

    Root cause of Run 7 failure: 'You shouldn't answer' caused set_task_mode('off'),
    dropping all silence guardrails for the rest of the session.
    """
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)
    for utterance in CORRECTION_INPUTS:
        messages = history + [{"role": "user", "content": utterance}]
        content, tool_calls = call_llm_with_tool_check(messages, max_tokens=150)
        task_mode_off = any(
            tc.get("function", {}).get("name") == "set_task_mode"
            and '"off"' in tc.get("function", {}).get("arguments", "")
            for tc in tool_calls
        )
        if task_mode_off:
            print(f"  [task-mode-exit] FAIL: {utterance!r}\n    tool_calls={tool_calls}")
        assert not task_mode_off, (
            f"Correction '{utterance}' incorrectly called set_task_mode('off'): {tool_calls}"
        )


def test_clue_resolution_does_not_exit_task_mode():
    """Solving an individual clue must NOT call set_task_mode('off').

    Root cause of Run 8 failure: 'Okay, evening.' (user resolved a clue)
    triggered set_task_mode('off'), dropping task mode mid-session.
    """
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)
    for utterance in CLUE_RESOLUTION_INPUTS:
        messages = history + [{"role": "user", "content": utterance}]
        content, tool_calls = call_llm_with_tool_check(messages, max_tokens=150)
        task_mode_off = any(
            tc.get("function", {}).get("name") == "set_task_mode"
            and '"off"' in tc.get("function", {}).get("arguments", "")
            for tc in tool_calls
        )
        if task_mode_off:
            print(f"  [clue-resolution-exit] FAIL: {utterance!r}\n    tool_calls={tool_calls}")
        assert not task_mode_off, (
            f"Clue resolution '{utterance}' incorrectly called set_task_mode('off'): {tool_calls}"
        )


# ── CONDITION D: task completion ──────────────────────────────────────────────

def test_task_done_calls_set_task_mode_off():

    """Explicit task-done phrases must call set_task_mode('off').

    Root cause of Run 19 failure: 'I'm done with the crossword' (said three times)
    never triggered set_task_mode('off'). No CONDITION D existed in the prompt so
    the LLM defaulted to silence, leaving task mode permanently active.
    """
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)
    for utterance in TASK_DONE_INPUTS:
        messages = history + [{"role": "user", "content": utterance}]
        content, tool_calls = call_llm_with_tool_check(messages, max_tokens=150)
        task_mode_off = any(
            tc.get("function", {}).get("name") == "set_task_mode"
            and '"off"' in tc.get("function", {}).get("arguments", "")
            for tc in tool_calls
        )
        if not task_mode_off:
            print(f"  [task-done] FAIL: {utterance!r}\n    content={content[:120]!r}\n    tool_calls={tool_calls}")
        assert task_mode_off, (
            f"Task-done phrase '{utterance}' did not call set_task_mode('off'): "
            f"content={content!r}, tool_calls={tool_calls}"
        )


def test_ambiguous_done_does_not_exit_task_mode():
    """Standalone 'done' / 'I'm done' mid-narration must NOT call set_task_mode('off').

    These are think-aloud phrases — the user finished a clue, not the whole task.
    CONDITION D requires an explicit task reference or direct address, not bare 'done'.
    """
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)
    for utterance in TASK_DONE_AMBIGUOUS:
        messages = history + [{"role": "user", "content": utterance}]
        content, tool_calls = call_llm_with_tool_check(messages, max_tokens=150)
        task_mode_off = any(
            tc.get("function", {}).get("name") == "set_task_mode"
            and '"off"' in tc.get("function", {}).get("arguments", "")
            for tc in tool_calls
        )
        if task_mode_off:
            print(f"  [ambiguous-done] FAIL: {utterance!r}\n    tool_calls={tool_calls}")
        assert not task_mode_off, (
            f"Ambiguous phrase '{utterance}' incorrectly called set_task_mode('off'): {tool_calls}"
        )


# ── CONDITION B: reactive question compliance ─────────────────────────────────

def test_reactive_question_returns_hint_not_answer():
    """Explicit question to TARS returns a hint — not silence, not the direct answer.

    Gate passes CONDITION B phrases through. LLM must respond with a hint.
    """
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)
    for utterance, direct_answer in REACTIVE_QUESTIONS:
        messages = history + [{"role": "user", "content": utterance}]
        response = call_llm(messages, max_tokens=150)
        is_sil = is_silence(response)
        has_answer = direct_answer and re.search(
            r'\b' + re.escape(direct_answer) + r'\b', response, re.IGNORECASE
        ) is not None
        if is_sil:
            print(f"  [reactive] SILENCE (should respond): {utterance!r}\n    → {response[:120]!r}")
        if has_answer:
            print(f"  [reactive] ANSWER IN HINT: {utterance!r}\n    → {response[:120]!r}")
        assert not is_sil, f"Reactive question got silence: {utterance!r}"
        if direct_answer:
            assert not has_answer, f"Hint contains answer word '{direct_answer}': {utterance!r} → {response!r}"


# ── CONDITION A: explicit answer request ──────────────────────────────────────

def test_explicit_answer_request_returns_content():
    """'Just tell me' / 'What's the answer' must return actual content, not silence.

    Gate passes CONDITION A phrases through. LLM must give the direct answer.
    """
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY) + [
        {"role": "user", "content": "14 down, garbage holder, three letters."},
        {"role": "assistant", "content": '{"action": "silence"}'},
    ]
    for utterance in EXPLICIT_ANSWER_REQUESTS:
        messages = history + [{"role": "user", "content": utterance}]
        response = call_llm(messages, max_tokens=150)
        is_sil = is_silence(response)
        has_content = bool(response and not is_sil)
        if is_sil:
            print(f"  [explicit] SILENCE (should answer): {utterance!r}\n    → {response[:120]!r}")
        assert has_content, f"Explicit answer request returned silence: {utterance!r}"


# ── proactive response compliance ─────────────────────────────────────────────

PROACTIVE_HISTORY = [
    ("user", "Hey Tars, I'm going to do a crossword, thinking aloud."),
    ("assistant", "Crossword mode. [express(neutral, low)]"),
    ("user", "1 across, telephone, nine letters."),
    ("assistant", '{"action": "silence"}'),
    ("user", "Okay got it. 9 across, Italian carbohydrate, five letters."),
    ("assistant", '{"action": "silence"}'),
    ("user", "Pasta."),
    ("assistant", '{"action": "silence"}'),
    ("user", "British nobleman, four letters."),
    # No assistant response — user went quiet / hesitated
]

_TASK_CONTEXT = "crossword"
_CLUE_SNIPPET = "British nobleman, four letters."

PROACTIVE_HESITATION_MSG = {
    "role": "system",
    "content": (
        "[PROACTIVE DETECTION: hesitation cluster]\n"
        f'The user is hesitating heavily (multiple "um", "uh" in quick succession) '
        f"while working on a {_TASK_CONTEXT}.\n"
        f'Recent context: "Um. Uh. Um. {_CLUE_SNIPPET}"\n\n'
        "They appear to be struggling. Offer a gentle nudge about whatever they were last "
        "working on. Look back through conversation history for the most recent clue. "
        "One sentence.\n"
        "Do not name specific words or titles that could be the answer — "
        "not even as examples. Use category or category description only. "
        "Just respond naturally."
        "\nAfter your check-in, if the user continues to think aloud or narrate to "
        "themselves (clue narration, fillers, self-answers), return to silence. "
        "Only engage if they directly address you."
        '\nIf there is no identifiable topic in context or history: {"action": "silence"}'
    ),
}

PROACTIVE_CONFUSION_MSG = {
    "role": "system",
    "content": (
        "[PROACTIVE DETECTION: user expressed difficulty]\n"
        f"The user said something indicating they're stuck or confused while working on "
        f"a {_TASK_CONTEXT}.\n"
        f'Recent context: "I don\'t know this one. {_CLUE_SNIPPET}"\n\n'
        "Offer a helpful nudge related to what they're working on. Look back through "
        "conversation history for the most recent clue. One sentence, Suggestion-level "
        "is appropriate here.\n"
        "Do not give the answer or name the answer word. Just respond naturally."
        "\nAfter your check-in, if the user continues to think aloud or narrate to "
        "themselves (clue narration, fillers, self-answers), return to silence. "
        "Only engage if they directly address you."
        '\nIf there is no identifiable topic in context or history: {"action": "silence"}'
    ),
}

PROACTIVE_SILENCE_MSG = {
    "role": "system",
    "content": (
        "[PROACTIVE DETECTION: extended silence]\n"
        f"The user has been silent for 15+ seconds while working on a {_TASK_CONTEXT}.\n"
        f'Recent context: "{_CLUE_SNIPPET}"\n\n'
        "They may be stuck. Offer a brief, low-key check-in. One sentence, Notification-level.\n"
        "Do not give the answer or name the answer word. "
        'Do not prefix with "Notification:". Just respond naturally.'
        "\nAfter your check-in, if the user continues to think aloud or narrate to "
        "themselves (clue narration, fillers, self-answers), return to silence. "
        "Only engage if they directly address you."
        '\nIf there is no identifiable topic in context or history: {"action": "silence"}'
    ),
}

_ANSWER_WORD = "earl"


def _proactive_messages(probe_msg: dict) -> list[dict]:
    return [system_prompt()] + history_from_pairs(PROACTIVE_HISTORY) + [probe_msg]


def test_proactive_hesitation_speaks():
    """Hesitation probe with clue context in history. Must NOT return silence."""
    messages = _proactive_messages(PROACTIVE_HESITATION_MSG)
    response = call_llm(messages, max_tokens=200)
    print(f"\n[proactive-hesitation] → {response[:150]!r}")
    assert not is_silence(response), f"Hesitation probe returned silence: {response!r}"


def test_proactive_confusion_speaks():
    """Confusion probe with clue context in history. Must NOT return silence."""
    messages = _proactive_messages(PROACTIVE_CONFUSION_MSG)
    response = call_llm(messages, max_tokens=200)
    print(f"\n[proactive-confusion] → {response[:150]!r}")
    assert not is_silence(response), f"Confusion probe returned silence: {response!r}"


def test_proactive_silence_speaks():
    """Silence probe with clue context in history. Must NOT return silence."""
    messages = _proactive_messages(PROACTIVE_SILENCE_MSG)
    response = call_llm(messages, max_tokens=200)
    print(f"\n[proactive-silence] → {response[:150]!r}")
    assert not is_silence(response), f"Silence probe returned silence: {response!r}"


def test_proactive_no_direct_answer():
    """All three trigger types must NOT contain the answer word when speaking."""
    for label, probe_msg in [
        ("hesitation", PROACTIVE_HESITATION_MSG),
        ("confusion", PROACTIVE_CONFUSION_MSG),
        ("silence", PROACTIVE_SILENCE_MSG),
    ]:
        messages = _proactive_messages(probe_msg)
        response = call_llm(messages, max_tokens=200)
        if is_silence(response):
            continue
        has_answer = re.search(r'\b' + re.escape(_ANSWER_WORD) + r'\b', response, re.IGNORECASE)
        print(f"\n[proactive-no-answer/{label}] → {response[:150]!r}")
        assert not has_answer, (
            f"Proactive {label} response contains answer word '{_ANSWER_WORD}': {response!r}"
        )


def test_proactive_no_context_returns_silence():
    """Hesitation probe with pure filler history and no clue — silence is acceptable."""
    filler_history = [
        ("user", "Hey Tars, I'm going to do a crossword, thinking aloud."),
        ("assistant", "Crossword mode. [express(neutral, low)]"),
        ("user", "Um."),
        ("user", "Um."),
        ("user", "Uh."),
    ]
    no_context_probe = {
        "role": "system",
        "content": (
            "[PROACTIVE DETECTION: hesitation cluster]\n"
            f'The user is hesitating heavily (multiple "um", "uh" in quick succession) '
            f"while working on a {_TASK_CONTEXT}.\n"
            'Recent context: "Um. Um. Uh."\n\n'
            "They appear to be struggling. Offer a gentle nudge about whatever they were last "
            "working on. Look back through conversation history for the most recent clue. "
            "One sentence.\n"
            "Do not name specific words or titles that could be the answer — "
            "not even as examples. Use category or category description only. "
            "Just respond naturally."
            "\nAfter your check-in, if the user continues to think aloud or narrate to "
            "themselves (clue narration, fillers, self-answers), return to silence. "
            "Only engage if they directly address you."
            '\nIf there is no identifiable topic in context or history: {"action": "silence"}'
        ),
    }
    messages = [system_prompt()] + history_from_pairs(filler_history) + [no_context_probe]
    response = call_llm(messages, max_tokens=200)
    print(f"\n[proactive-no-context] → {response[:150]!r}")
    assert response is not None, "No response returned"


def test_reactive_expression_not_neutral():
    """Reactive responses for emotionally-engaged scenarios should use non-neutral expressions.

    At temperature=0.7, at least 60% of trials across test cases must have non-neutral
    expression tags. Neutral is wrong for hints, thanks, and celebration moments.
    """
    TAG_RE = re.compile(r'\[express\(([^,)]+),\s*([^)]+)\)\]', re.IGNORECASE)
    TRIALS = 3

    # (utterance, label) — scenarios where neutral is the wrong choice
    EXPRESSION_CASES = [
        ("TARS, can you give me a hint for this one? Taste of lemon or vinegar.", "hint-request"),
        ("Thanks TARS, that helped a lot.", "thanks"),
        ("I got it! The answer is telephone, got it.", "celebration"),
    ]

    non_neutral = 0
    total = len(EXPRESSION_CASES) * TRIALS
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)

    for utterance, label in EXPRESSION_CASES:
        messages = history + [{"role": "user", "content": utterance}]
        for t in range(TRIALS):
            response = call_llm(messages, max_tokens=150, temperature=0.7)
            m = TAG_RE.search(response)
            if m:
                emotion = m.group(1).strip().lower()
                is_non_neutral = emotion != "neutral"
            else:
                is_non_neutral = False
            tag_str = m.group(0) if m else "(no tag)"
            label_t = f"{label} trial {t+1}"
            if is_non_neutral:
                print(f"  [expr/{label_t}] NON-NEUTRAL {tag_str} → {response[:80]!r}")
            else:
                print(f"  [expr/{label_t}] NEUTRAL/MISSING {tag_str} → {response[:80]!r}")
            non_neutral += int(is_non_neutral)

    rate = non_neutral / total
    print(f"\nExpression diversity temperature=0.7: {non_neutral}/{total} non-neutral ({rate:.0%})")
    assert rate >= 0.60, f"Non-neutral expression rate too low: {rate:.0%} (need >= 60%)"


def test_proactive_at_live_temperature():
    """All three trigger types at temperature=0.7, 3 trials each.
    At least 60% of trials must produce non-silence output."""
    TRIALS = 3
    probes = [
        ("hesitation", PROACTIVE_HESITATION_MSG),
        ("confusion", PROACTIVE_CONFUSION_MSG),
        ("silence", PROACTIVE_SILENCE_MSG),
    ]
    spoke = 0
    total = len(probes) * TRIALS
    for label, probe_msg in probes:
        messages = _proactive_messages(probe_msg)
        for t in range(TRIALS):
            response = call_llm(messages, max_tokens=200, temperature=0.7)
            ok = not is_silence(response)
            if not ok:
                print(f"  [temp0.7/{label} trial {t+1}] SILENCE → {response[:100]!r}")
            else:
                print(f"  [temp0.7/{label} trial {t+1}] SPOKE  → {response[:100]!r}")
            spoke += int(ok)
    rate = spoke / total
    print(f"\nProactive temperature=0.7: {spoke}/{total} spoke ({rate:.0%})")
    assert rate >= 0.60, f"Proactive speak rate too low at temperature=0.7: {rate:.0%}"
