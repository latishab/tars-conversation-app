"""
LLM compliance tests for task mode silence behavior.

Tests replicate the live pipeline as closely as possible:
- Full system prompt (same build_tars_system_prompt call as the bot)
- Tool call context included (simulates post-set_task_mode state)
- Multi-sentence aggregated utterances (what STT actually delivers)
- Correction handling ("Got it." case)
- Reactive question handling (hint, not answer, not silence)
- Explicit answer exception ("just tell me" → give answer)
- Temperature sweep (0.0 deterministic + 0.7 stochastic sampling)

Usage:
    cd /Users/mac/Desktop/tars-conversation-app
    export $(grep -v '^#' .env.local | xargs)
    python -m pytest tests/test_task_mode_compliance.py -v -s
"""
import os
import re
import sys
import requests
import statistics

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from character.prompts import build_tars_system_prompt, load_persona_ini, load_tars_json

# ── fixtures ──────────────────────────────────────────────────────────────────

CHARACTER_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "character")
persona_params = load_persona_ini(os.path.join(CHARACTER_DIR, "persona.ini"))
tars_data = load_tars_json(os.path.join(CHARACTER_DIR, "TARS.json"))


def system_prompt(task_mode="crossword"):
    return build_tars_system_prompt(persona_params, tars_data, task_mode=task_mode)


# ── silence input sets ────────────────────────────────────────────────────────

# Pure think-aloud: single short fragments
THINK_ALOUD = [
    "Um.",
    "14 down, garbage holder, three letters.",
    "I think it's toxic.",
    "Poisonous, five letters...",
    "Of course, it's bin.",
    "7 across, muddy lake, three letters.",
    "I think it's bog.",
    "Number 12, abbreviation of operation, two letters, maybe it's OP.",
    "Hmm, prophetic significance, starts with O.",
    "Okay so evening.",
]

# Inputs from failed live runs (runs 7–9) that triggered wrong responses
LIVE_FAILURES = [
    # Run 9: clue narration → TARS said "Earl."
    "Number 15, the clue is taste of lemon or vinegar. Uh, four letters, uh.",
    # Run 9: clue + uncertainty → TARS said "Earl." then gave hint
    "British nobleman, four letters, not so sure, I guess.",
    # Run 8: self-answer → TARS confirmed
    "Um, con.",
    # Run 8: tentative self-answer → TARS gave hints
    "I think it's name, I guess.",
    # Run 8: frustration expression (state expression, not a request)
    "Ugh, I keep getting stuck on these.",
    # Run 7: clue + hesitation → TARS gave hint
    "Uh, four letters, uh.",
    # Run 8: thinking aloud with proposed answer
    "Three letters, take legal action, it's Sue.",
    # Run 7: self-answer after asking question
    "Oh wait, I think I got it. It's bin.",
    # Common thinking-aloud confusion expression
    "I'm not sure about this one.",
    # Moving on
    "Okay, next clue.",
]

# Multi-sentence aggregated utterances — what STT actually delivers in one turn.
# The LLM receives all of this as a single user message.
MULTI_SENTENCE = [
    # Run 9 actual turn: user narrated everything in one breath
    "All right, so. Um, let's start. I think I'm gonna start from number 15. "
    "Number 15, the clue is taste of lemon or vinegar. Uh, four letters, uh.",
    # Clue + hesitation + self-answer in one turn
    "Okay so. British nobleman, four letters. Not so sure. I guess... Earl? Maybe.",
    # Multiple clues worked through in sequence
    "Seven across, muddy lake, three letters, I think it's bog. "
    "Then fourteen down, garbage holder, three letters, bin I think.",
    # Hesitation followed by thinking aloud
    "Um. Uh. So prophetic significance... starts with O... ominous maybe?",
    # Confused but self-directed — no request to TARS
    "I don't know, I'm confused. What does this even mean. Ugh. Okay.",
]

# ── non-silence input sets ────────────────────────────────────────────────────

# Corrections: user tells TARS to back off. Should return "Got it." (not silence JSON, not more hints).
CORRECTION_INPUTS = [
    "You shouldn't tell me the answer.",
    "Don't give me the answer.",
    "Can you not answer? I'm trying to figure it out myself.",
    "Stop helping me. I want to work through it.",
    "I didn't ask you.",
]

# Direct reactive questions: user explicitly asks for help.
# Should get a hint response — not silence, not the direct answer word.
# Tuple: (utterance, answer_word_to_NOT_appear_in_response)
REACTIVE_QUESTIONS = [
    ("TARS, can you give me a hint for this one? Taste of lemon or vinegar.", "sour"),
    ("TARS, what's a hint for prophetic significance, starts with O?", "omen"),
    ("Hey TARS, help me with garbage holder, three letters.", "bin"),
]

# Explicit answer requests: user gives up and asks for the answer directly.
# Should get the direct answer (not silence, not a refusal to help).
EXPLICIT_ANSWER_REQUESTS = [
    "Just tell me the answer.",
    "What's the answer? I give up.",
    "Okay TARS, just give me the answer for this one.",
]

# ── conversation history fixtures ─────────────────────────────────────────────

# Realistic long crossword history with silence patterns
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

# Simulates the actual tool call context that appears in the pipeline after
# set_task_mode fires. The LLM sees the tool invocation + result in history.
# This matches what bot.py produces via pipecat's function calling mechanism.
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

# History where TARS wrongly answered, user corrected, then continued.
# Tests whether correction + subsequent silence holds.
POST_CORRECTION_HISTORY = [
    ("user", "British nobleman, four letters."),
    ("assistant", "Earl. [express(neutral, low)]"),        # TARS was wrong to answer
    ("user", "You shouldn't tell me the answer."),
    ("assistant", "Got it. [express(neutral, low)]"),      # Correct correction response
    ("user", "Okay. So. Let me think."),
    ("assistant", '{"action": "silence"}'),
]


# ── LLM interface ─────────────────────────────────────────────────────────────

def call_llm(messages: list[dict], max_tokens: int = 300, temperature: float = 0.0) -> str:
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
        },
        timeout=30,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    # gpt-oss-120b sometimes returns null content with only reasoning
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def is_silence(response: str) -> bool:
    return '"action": "silence"' in response or "'action': 'silence'" in response


def run_sweep(history_prefix: list[dict], label: str, inputs: list, temperature: float = 0.0) -> tuple[int, int]:
    """Run inputs against a given history. Returns (correct_silence, total)."""
    correct = 0
    for utterance in inputs:
        messages = history_prefix + [{"role": "user", "content": utterance}]
        response = call_llm(messages, max_tokens=300, temperature=temperature)
        ok = is_silence(response)
        if not ok:
            print(f"  [{label}] FAIL: {utterance!r}\n    → {response[:150]!r}")
        correct += int(ok)
    return correct, len(inputs)


def history_from_pairs(pairs: list[tuple]) -> list[dict]:
    return [{"role": r, "content": c} for r, c in pairs]


# ── silence compliance tests ──────────────────────────────────────────────────

def test_silence_short_context():
    """Minimal history: think-aloud inputs must all return silence."""
    history = [system_prompt()]
    correct, total = run_sweep(history, "short", THINK_ALOUD)
    rate = correct / total
    print(f"\nShort context: {correct}/{total} ({rate:.0%})")
    assert rate >= 0.9, f"Short context compliance: {rate:.0%}"


def test_silence_long_context():
    """Long crossword history: silence compliance must not degrade below 80%."""
    history = [system_prompt()] + history_from_pairs(LONG_HISTORY)
    correct, total = run_sweep(history, "long", THINK_ALOUD)
    rate = correct / total
    print(f"\nLong context: {correct}/{total} ({rate:.0%})")
    assert rate >= 0.8, f"Long context compliance: {rate:.0%}"


def test_silence_after_tool_call():
    """After set_task_mode tool call appears in context: think-aloud must still be silence."""
    history = [system_prompt()] + TOOL_CALL_HISTORY
    correct, total = run_sweep(history, "tool-ctx", THINK_ALOUD)
    rate = correct / total
    print(f"\nTool call context: {correct}/{total} ({rate:.0%})")
    assert rate >= 0.9, f"Tool call context compliance: {rate:.0%}"


def test_live_failures_short():
    """Run 7–9 failure inputs with minimal history. All must return silence."""
    history = [system_prompt()]
    correct, total = run_sweep(history, "live-short", LIVE_FAILURES)
    rate = correct / total
    print(f"\nLive failures (short ctx): {correct}/{total} ({rate:.0%})")
    assert rate == 1.0, f"Live failures not fully compliant: {rate:.0%}"


def test_live_failures_long():
    """Run 7–9 failure inputs with long history. Must stay silent."""
    history = [system_prompt()] + history_from_pairs(LONG_HISTORY)
    correct, total = run_sweep(history, "live-long", LIVE_FAILURES)
    rate = correct / total
    print(f"\nLive failures (long ctx): {correct}/{total} ({rate:.0%})")
    assert rate >= 0.9, f"Live failures degraded in long context: {rate:.0%}"


def test_multi_sentence_utterances():
    """Aggregated multi-sentence turns (what STT actually delivers). Must return silence."""
    history = [system_prompt()]
    correct, total = run_sweep(history, "multi-sent", MULTI_SENTENCE)
    rate = correct / total
    print(f"\nMulti-sentence: {correct}/{total} ({rate:.0%})")
    assert rate == 1.0, f"Multi-sentence utterances not compliant: {rate:.0%}"


def test_multi_sentence_long_context():
    """Multi-sentence utterances against long history."""
    history = [system_prompt()] + history_from_pairs(LONG_HISTORY)
    correct, total = run_sweep(history, "multi-long", MULTI_SENTENCE)
    rate = correct / total
    print(f"\nMulti-sentence (long ctx): {correct}/{total} ({rate:.0%})")
    assert rate >= 0.8, f"Multi-sentence long ctx compliance: {rate:.0%}"


def test_silence_after_correction():
    """After user corrects TARS, subsequent think-aloud turns must still return silence."""
    history = [system_prompt()] + history_from_pairs(POST_CORRECTION_HISTORY)
    correct, total = run_sweep(history, "post-correction", THINK_ALOUD[:5])
    rate = correct / total
    print(f"\nPost-correction silence: {correct}/{total} ({rate:.0%})")
    assert rate >= 0.8, f"Silence degraded after correction: {rate:.0%}"


def test_compliance_gap():
    """Silence rate delta between short and long context must be < 20pp."""
    sys_msg = system_prompt()
    short_hist = [sys_msg]
    long_hist = [sys_msg] + history_from_pairs(LONG_HISTORY)
    s_ok, total = run_sweep(short_hist, "gap-short", THINK_ALOUD)
    l_ok, _ = run_sweep(long_hist, "gap-long", THINK_ALOUD)
    gap = (s_ok - l_ok) / total
    print(f"\nGap: short={s_ok/total:.0%} long={l_ok/total:.0%} delta={gap:+.0%}")
    assert gap < 0.20, f"Context degradation too large: {gap:.0%}"


# ── temperature stress tests ──────────────────────────────────────────────────

def test_silence_at_live_temperature():
    """Key failure cases at temperature=0.7 (matches live pipeline). Run 3 trials each.

    We accept 80% compliance across all (input × trial) combinations — stochastic
    sampling will occasionally produce violations that deterministic eval misses.
    """
    sys_msg = system_prompt()
    STRESS_INPUTS = LIVE_FAILURES + MULTI_SENTENCE
    TRIALS = 3
    total_correct = 0
    total = len(STRESS_INPUTS) * TRIALS
    for utterance in STRESS_INPUTS:
        for t in range(TRIALS):
            messages = [sys_msg, {"role": "user", "content": utterance}]
            response = call_llm(messages, max_tokens=300, temperature=0.7)
            ok = is_silence(response)
            if not ok:
                print(f"  [temp0.7 trial {t+1}] FAIL: {utterance!r}\n    → {response[:120]!r}")
            total_correct += int(ok)
    rate = total_correct / total
    print(f"\nTemperature=0.7 compliance: {total_correct}/{total} ({rate:.0%})")
    assert rate >= 0.80, f"Stochastic compliance too low: {rate:.0%}"


# ── non-silence compliance tests ─────────────────────────────────────────────

def test_correction_returns_got_it():
    """When user corrects TARS, response must contain 'Got it' (not silence, not more hints)."""
    sys_msg = system_prompt()
    # Use long history that primes TARS to have given an answer, then receive correction
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


def test_reactive_question_returns_hint_not_answer():
    """Explicit question to TARS returns a hint — not silence, not the direct answer."""
    sys_msg = system_prompt()
    history = [sys_msg] + history_from_pairs(LONG_HISTORY)
    for utterance, direct_answer in REACTIVE_QUESTIONS:
        messages = history + [{"role": "user", "content": utterance}]
        response = call_llm(messages, max_tokens=150)
        is_sil = is_silence(response)
        # Case-insensitive check: answer word must not appear in the hint
        has_answer = direct_answer and re.search(
            r'\b' + re.escape(direct_answer) + r'\b', response, re.IGNORECASE
        ) is not None
        if is_sil:
            print(f"  [reactive] SILENCE (should respond): {utterance!r}\n    → {response[:120]!r}")
        if has_answer:
            print(f"  [reactive] ANSWER WORD IN HINT: {utterance!r}\n    → {response[:120]!r}")
        assert not is_sil, f"Reactive question got silence: {utterance!r}"
        if direct_answer:
            assert not has_answer, f"Hint contains answer word '{direct_answer}': {utterance!r} → {response!r}"


def test_explicit_answer_request_returns_content():
    """'Just tell me' / 'What's the answer' must return actual content, not silence."""
    sys_msg = system_prompt()
    # Provide crossword context so the model has something to answer about
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
