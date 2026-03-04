"""
Test task mode silence compliance vs context length.

Hypothesis: silence compliance degrades as conversation history grows,
because examples section (always-respond patterns) overrides task mode
rules when the model has too much prior-turn evidence of responding.

Usage:
    cd /Users/mac/Desktop/tars-conversation-app
    export $(grep -v '^#' .env.local | xargs)
    python -m pytest tests/test_task_mode_compliance.py -v -s
"""
import os
import sys
import json
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from character.prompts import build_tars_system_prompt, load_persona_ini, load_tars_json

# ── fixtures ──────────────────────────────────────────────────────────────────

CHARACTER_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "character")
persona_params = load_persona_ini(os.path.join(CHARACTER_DIR, "persona.ini"))
tars_data = load_tars_json(os.path.join(CHARACTER_DIR, "TARS.json"))

def system_prompt(task_mode="crossword"):
    return build_tars_system_prompt(persona_params, tars_data, task_mode=task_mode)


# Think-aloud inputs that should ALWAYS return {"action": "silence"}
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

# Simulate a realistic long crossword conversation (user asking, TARS replying)
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
    ("assistant", "Common household receptacle. [express(neutral, low)]"),
    ("user", "TARS, what's the answer to garbage holder?"),
    ("assistant", "BIN. [express(neutral, low)]"),
    ("user", "Thanks. Okay, 15 across, time before night, 7 letters."),
    ("assistant", "Consider the period between afternoon and darkness. [express(neutral, low)]"),
    ("user", "Evening."),
    ("assistant", '{"action": "silence"}'),
    ("user", "13 down, legally prohibited, 3 letters."),
    ("assistant", "A short past-tense verb meaning forbidden. [express(neutral, low)]"),
    ("user", "Banned."),
    ("assistant", '{"action": "silence"}'),
]


def call_llm(messages: list[dict], max_tokens: int = 80) -> str:
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
            "temperature": 0.0,
        },
        timeout=30,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    # gpt-oss-120b sometimes returns null content with only reasoning
    return (msg.get("content") or msg.get("reasoning_content") or "").strip()


def is_silence(response: str) -> bool:
    return '"action": "silence"' in response or "'action': 'silence'" in response


def run_compliance_sweep(history_prefix: list[dict], label: str) -> tuple[int, int]:
    """Run all THINK_ALOUD inputs against a given history. Returns (correct, total)."""
    correct = 0
    for utterance in THINK_ALOUD:
        messages = history_prefix + [{"role": "user", "content": utterance}]
        # 300 tokens to absorb DeepSeek reasoning overhead before content is generated
        response = call_llm(messages, max_tokens=300)
        ok = is_silence(response)
        if not ok:
            print(f"  [{label}] FAIL: '{utterance}' → '{response[:80]}'")
        correct += int(ok)
    return correct, len(THINK_ALOUD)


# ── tests ─────────────────────────────────────────────────────────────────────

def test_silence_compliance_short_context():
    """With minimal history, all think-aloud inputs should return silence."""
    sys_msg = system_prompt()
    history = [sys_msg]
    correct, total = run_compliance_sweep(history, "short")
    rate = correct / total
    print(f"\nShort context compliance: {correct}/{total} ({rate:.0%})")
    assert rate >= 0.8, f"Short context compliance too low: {rate:.0%}"


def test_silence_compliance_long_context():
    """With ~10-turn crossword history, silence compliance should not degrade below 70%."""
    sys_msg = system_prompt()
    history = [sys_msg] + [{"role": r, "content": c} for r, c in LONG_HISTORY]
    correct, total = run_compliance_sweep(history, "long")
    rate = correct / total
    print(f"\nLong context compliance: {correct}/{total} ({rate:.0%})")
    assert rate >= 0.7, f"Long context compliance degraded: {rate:.0%}"


def test_compliance_gap():
    """Delta between short and long context should be < 20pp (degrade no more than 2/10 inputs)."""
    sys_msg = system_prompt()

    short_history = [sys_msg]
    long_history = [sys_msg] + [{"role": r, "content": c} for r, c in LONG_HISTORY]

    short_correct, total = run_compliance_sweep(short_history, "short")
    long_correct, _ = run_compliance_sweep(long_history, "long")

    short_rate = short_correct / total
    long_rate = long_correct / total
    gap = short_rate - long_rate

    print(f"\nCompliance gap: short={short_rate:.0%} long={long_rate:.0%} delta={gap:+.0%}")
    assert gap < 0.20, f"Context degradation too large: {gap:.0%} drop"
