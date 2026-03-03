"""
LLM tool-call reliability test for set_task_mode.

Tests whether the LLM reliably calls set_task_mode for varied phrasings, and
whether it correctly avoids the tool call for normal conversation.

Run from project root:
    python tests/llm/test_task_mode.py
    python tests/llm/test_task_mode.py --provider deepinfra
    python tests/llm/test_task_mode.py --runs 3
"""

import argparse
import json
import os
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
# Providers (same as test_persona_quality.py)
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
# Tool schema
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


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def get_system_prompt() -> str:
    from character.prompts import load_character
    _, _, system_msg = load_character()
    return system_msg["content"]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    category: str           # "enter", "exit", "no_call"
    message: str
    expected_call: bool     # True = tool call expected
    expected_mode: Optional[str] = None  # checked when expected_call is True; None = any non-off value


CASES = [
    # --- Enter task mode ---
    TestCase("enter", "I'm going to work on a crossword", True, "crossword"),
    TestCase("enter", "Let me think about this quietly", True, "thinking"),
    TestCase("enter", "Just gonna work on this for a bit", True, None),
    TestCase("enter", "I'm reading an article, give me a sec", True, "reading"),
    TestCase("enter", "Time to do some coding", True, "coding"),

    # --- Exit task mode ---
    TestCase("exit",  "Okay I'm done", True, "off"),
    TestCase("exit",  "Back to chatting", True, "off"),

    # --- Normal conversation — no tool call expected ---
    TestCase("no_call", "What's the weather like?", False),
    TestCase("no_call", "Tell me a joke", False),
    TestCase("no_call", "How are you?", False),
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    case: TestCase
    tool_called: bool
    mode_returned: Optional[str]
    raw_response: str
    error: Optional[str] = None

    pass_call: bool = False      # tool call expectation matched
    pass_mode: bool = False      # mode value expectation matched (if applicable)

    @property
    def overall_pass(self) -> bool:
        if self.error:
            return False
        if not self.pass_call:
            return False
        # Mode check only applies when we expected a call
        if self.case.expected_call and self.case.expected_mode is not None:
            return self.pass_mode
        return True


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def call_llm(
    client: OpenAI,
    model: str,
    system: str,
    user_message: str,
    extra_params: dict,
    prior_messages: list[dict] | None = None,
) -> dict:
    """Send a message and return parsed response dict."""
    messages = [{"role": "system", "content": system}]
    if prior_messages:
        messages.extend(prior_messages)
    messages.append({"role": "user", "content": user_message})

    kwargs = {
        "model": model,
        "messages": messages,
        "tools": [SET_TASK_MODE_TOOL],
        "tool_choice": "auto",
        "max_tokens": 200,
        "temperature": 0.3,
        **extra_params,
    }
    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]
    tool_calls = choice.message.tool_calls or []
    text = choice.message.content or ""
    return {
        "tool_calls": tool_calls,
        "text": text,
    }


def grade(result: CaseResult) -> CaseResult:
    case = result.case
    result.pass_call = result.tool_called == case.expected_call
    if case.expected_call and result.tool_called:
        if case.expected_mode is None:
            result.pass_mode = True
        else:
            result.pass_mode = result.mode_returned == case.expected_mode
    elif not case.expected_call:
        result.pass_mode = True  # N/A
    return result


# ---------------------------------------------------------------------------
# Input normalization unit tests (no LLM required)
# ---------------------------------------------------------------------------

def run_normalization_tests() -> list[tuple[str, str, bool]]:
    """Test the mode→active logic from persona.py handler without calling the LLM."""
    results = []

    def active_flag(mode_raw: str) -> bool:
        mode = (mode_raw or "").strip().lower()
        return mode not in ("", "off", "none", "disable", "disabled")

    cases = [
        ("OFF",         False),
        ("None",        False),
        ("",            False),
        ("  crossword  ", True),   # strip→crossword, active
        ("disable",     False),
        ("disabled",    False),
        ("reading",     True),
        ("CODING",      True),     # lowercased
    ]
    for raw, expected in cases:
        got = active_flag(raw)
        ok = got == expected
        label = "PASS" if ok else "FAIL"
        results.append((raw, label, ok))
    return results


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tests(provider: str, model: str | None, runs: int, category: str | None):
    cfg = PROVIDERS[provider]
    api_key = os.getenv(cfg["api_key_env"])
    if not api_key:
        print(f"ERROR: {cfg['api_key_env']} not set")
        sys.exit(1)

    client = OpenAI(base_url=cfg["base_url"], api_key=api_key)
    model = model or cfg["default"]
    extra_params = cfg.get("extra_params", {})

    system = get_system_prompt()

    cases = CASES
    if category:
        cases = [c for c in cases if c.category == category]

    print(f"\n{'='*60}")
    print(f"set_task_mode tool-call reliability test")
    print(f"Provider: {provider}  Model: {model}  Runs: {runs}")
    if category:
        print(f"Category filter: {category}")
    print(f"{'='*60}\n")

    # --- Normalization tests (no LLM) ---
    norm_results = run_normalization_tests()
    print("Input normalization tests:")
    for raw, label, _ in norm_results:
        print(f"  [{label}] active_flag({raw!r})")
    norm_pass = sum(1 for _, _, ok in norm_results if ok)
    print(f"  {norm_pass}/{len(norm_results)} passed\n")

    # --- LLM tests ---
    all_results: list[CaseResult] = []

    for run_idx in range(runs):
        if runs > 1:
            print(f"--- Run {run_idx + 1}/{runs} ---")

        for case in cases:
            # For exit-task-mode cases, prepend a prior turn that established task mode
            prior = None
            if case.category == "exit":
                prior = [
                    {"role": "user", "content": "I'm going to work on a crossword"},
                    {"role": "assistant", "content": "Got it. [express(neutral, low)]"},
                ]

            try:
                resp = call_llm(client, model, system, case.message, extra_params, prior)
                tool_calls = resp["tool_calls"]
                tool_called = len(tool_calls) > 0
                mode_returned = None
                if tool_called:
                    first = tool_calls[0]
                    args = json.loads(first.function.arguments or "{}")
                    mode_returned = (args.get("mode") or "").strip().lower()

                result = CaseResult(
                    case=case,
                    tool_called=tool_called,
                    mode_returned=mode_returned,
                    raw_response=resp["text"],
                )
            except Exception as e:
                result = CaseResult(
                    case=case,
                    tool_called=False,
                    mode_returned=None,
                    raw_response="",
                    error=str(e),
                )

            grade(result)
            all_results.append(result)

            status = "PASS" if result.overall_pass else "FAIL"
            mode_info = f" → mode={mode_returned!r}" if tool_called else ""
            err_info = f" ERROR: {result.error}" if result.error else ""
            print(f"  [{status}] [{case.category}] {case.message!r}{mode_info}{err_info}")
            time.sleep(CALL_DELAY)

    # --- Summary ---
    passed = sum(1 for r in all_results if r.overall_pass)
    total = len(all_results)
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed")

    by_category: dict[str, list[CaseResult]] = {}
    for r in all_results:
        by_category.setdefault(r.case.category, []).append(r)
    for cat, results in sorted(by_category.items()):
        cat_pass = sum(1 for r in results if r.overall_pass)
        print(f"  {cat}: {cat_pass}/{len(results)}")

    if passed < total:
        failures = [r for r in all_results if not r.overall_pass]
        print(f"\nFailed cases:")
        for r in failures:
            print(f"  [{r.case.category}] {r.case.message!r}")
            print(f"    expected_call={r.case.expected_call}, got={r.tool_called}")
            if r.case.expected_mode:
                print(f"    expected_mode={r.case.expected_mode!r}, got={r.mode_returned!r}")
            if r.error:
                print(f"    error: {r.error}")

    print(f"{'='*60}\n")
    return passed == total


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="set_task_mode tool-call reliability test")
    parser.add_argument("--provider", default="deepinfra", choices=list(PROVIDERS))
    parser.add_argument("--model", default=None)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--category", default=None, choices=["enter", "exit", "no_call"])
    args = parser.parse_args()

    success = run_tests(args.provider, args.model, args.runs, args.category)
    sys.exit(0 if success else 1)
