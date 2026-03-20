"""
Context cleanup verification for ProactiveMonitor._fire_intervention.

Tests the filter that strips previous probe+response pairs so they
don't accumulate over multiple proactive cycles.

The filter (reproduced verbatim from _fire_intervention):
  - Drops any system message containing "[PROACTIVE DETECTION"
  - Drops the assistant message immediately following such a system message
  - Preserves all other messages in their original order

No API calls. Pure unit test of the filter logic.

Run from project root:
    python tests/llm/test_context_cleanup.py
    python tests/llm/test_context_cleanup.py -v     # verbose: print all filtered outputs
"""

import argparse
import sys as _sys


# ---------------------------------------------------------------------------
# Filter logic — verbatim copy from _fire_intervention
# ---------------------------------------------------------------------------

def _filter_messages(messages: list[dict]) -> list[dict]:
    filtered = []
    skip_next_assistant = False
    for m in messages:
        is_probe = (
            m.get("role") == "system"
            and "[PROACTIVE DETECTION" in m.get("content", "")
        )
        if is_probe:
            skip_next_assistant = True
            continue
        if skip_next_assistant and m.get("role") == "assistant":
            skip_next_assistant = False
            continue
        skip_next_assistant = False
        filtered.append(m)
    return filtered


def _count_probes(messages: list[dict]) -> int:
    return sum(
        1 for m in messages
        if m.get("role") == "system"
        and "[PROACTIVE DETECTION" in m.get("content", "")
    )


# ---------------------------------------------------------------------------
# Message factories
# ---------------------------------------------------------------------------

def sys(content="You are TARS."):
    return {"role": "system", "content": content}

def user(content):
    return {"role": "user", "content": content}

def assistant(content):
    return {"role": "assistant", "content": content}

def probe(n=1, trigger="SILENCE"):
    return {"role": "system", "content": f"[PROACTIVE DETECTION - {trigger}]: probe #{n}"}

def probe_response(n=1):
    return {"role": "assistant", "content": f"That's a tricky one — probe response #{n}. [express(curious, low)]"}


def simulate_cycle(context: list[dict], probe_n: int, new_probe_trigger="SILENCE") -> list[dict]:
    """Apply filter and append new probe — what _fire_intervention sends to LLM."""
    filtered = _filter_messages(context)
    filtered.append(probe(probe_n, new_probe_trigger))
    return filtered


def simulate_llm_response(sent_messages: list[dict], probe_n: int) -> list[dict]:
    """After LLM responds, context = sent_messages + probe_response.
    This is what self._context.messages looks like after the cycle completes."""
    return list(sent_messages) + [probe_response(probe_n)]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

passed = 0
failed = 0
verbose = False

def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))


def section(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def dump(label: str, messages: list[dict]):
    if verbose:
        print(f"\n  [{label}]")
        for i, m in enumerate(messages):
            content_snip = m['content'][:60].replace('\n', ' ')
            print(f"    [{i}] {m['role']:<12}  {content_snip}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_probes():
    section("No probes in context — passthrough")
    ctx = [sys(), user("Hello"), assistant("Here. [express(happy, high)]")]
    filtered = _filter_messages(ctx)
    dump("filtered", filtered)
    check("length unchanged", len(filtered) == len(ctx), f"{len(filtered)} != {len(ctx)}")
    check("no probes in output", _count_probes(filtered) == 0)
    check("content identical", filtered == ctx)


def test_probe_at_end_no_response():
    section("Probe at end with no LLM response yet — probe dropped")
    ctx = [
        sys(), user("Hello"), assistant("Here."),
        probe(1),
    ]
    filtered = _filter_messages(ctx)
    dump("filtered", filtered)
    check("probe removed", _count_probes(filtered) == 0)
    check("3 messages remain", len(filtered) == 3)
    check("base messages intact", filtered[0]["role"] == "system"
          and filtered[1]["role"] == "user"
          and filtered[2]["role"] == "assistant")


def test_probe_with_response():
    section("Probe + response in context — both dropped")
    ctx = [
        sys(), user("Hello"), assistant("Here."),
        probe(1), probe_response(1),
    ]
    filtered = _filter_messages(ctx)
    dump("filtered", filtered)
    check("probe removed", _count_probes(filtered) == 0)
    check("probe response removed", not any("probe response" in m.get("content","") for m in filtered))
    check("3 base messages remain", len(filtered) == 3)


def test_three_consecutive_cycles():
    section("Three consecutive probe cycles — no accumulation")
    base = [sys(), user("I'm stuck on something"), assistant("What's the issue?")]

    # Cycle 1: fire probe, LLM responds
    sent1 = simulate_cycle(base, probe_n=1)
    ctx1  = simulate_llm_response(sent1, probe_n=1)
    check("[C1] exactly 1 probe sent",  _count_probes(sent1) == 1)
    check("[C1] context has probe+resp", _count_probes(ctx1) == 1 and len(ctx1) == 5)

    dump("cycle 1 context", ctx1)

    # Cycle 2: fire probe, LLM responds
    sent2 = simulate_cycle(ctx1, probe_n=2)
    ctx2  = simulate_llm_response(sent2, probe_n=2)
    check("[C2] old probe stripped from sent", _count_probes(sent2) == 1, f"got {_count_probes(sent2)}")
    check("[C2] only new probe in sent", sent2[-1]["content"].startswith("[PROACTIVE DETECTION"))
    check("[C2] exactly 1 probe in context", _count_probes(ctx2) == 1)
    check("[C2] no cycle-1 response in context",
          not any("probe response #1" in m.get("content","") for m in ctx2))

    dump("cycle 2 context", ctx2)

    # Cycle 3: fire probe, LLM responds
    sent3 = simulate_cycle(ctx2, probe_n=3)
    ctx3  = simulate_llm_response(sent3, probe_n=3)
    check("[C3] only 1 probe in sent", _count_probes(sent3) == 1)
    check("[C3] exactly 1 probe in context", _count_probes(ctx3) == 1)
    check("[C3] no cycle-1 remnants",
          not any("probe response #1" in m.get("content","") for m in ctx3))
    check("[C3] no cycle-2 remnants",
          not any("probe response #2" in m.get("content","") for m in ctx3))
    check("[C3] base messages preserved",
          ctx3[0] == base[0] and ctx3[1] == base[1] and ctx3[2] == base[2])
    check("[C3] total context size bounded",
          len(ctx3) == len(base) + 2,  # base + new_probe + new_response
          f"got {len(ctx3)}, expected {len(base) + 2}")

    dump("cycle 3 context", ctx3)


def test_user_message_between_cycles():
    section("User speaks between cycles — user message preserved, old probe stripped")
    base = [sys(), user("I'm stuck"), assistant("Walk me through it.")]

    # Probe fires, LLM responds
    sent1 = simulate_cycle(base, probe_n=1)
    ctx1  = simulate_llm_response(sent1, probe_n=1)

    # User speaks after the probe response
    ctx1_with_user = ctx1 + [user("Actually, I figured it out!")]

    # Next probe fires
    sent2 = simulate_cycle(ctx1_with_user, probe_n=2)

    dump("after user speaks", ctx1_with_user)
    dump("sent for cycle 2", sent2)

    check("old probe stripped", not any("probe response #1" in m.get("content","") for m in sent2))
    check("user message preserved", any("figured it out" in m.get("content","") for m in sent2))
    check("new probe present", _count_probes(sent2) == 1)
    check("new probe at end", sent2[-1]["content"].startswith("[PROACTIVE DETECTION"))


def test_multiple_probes_in_context():
    section("Multiple probes in context (degenerate) — all stripped")
    # This shouldn't happen in normal flow but tests filter robustness
    ctx = [
        sys(), user("Hello"), assistant("Here."),
        probe(1), probe_response(1),
        probe(2), probe_response(2),
        probe(3), probe_response(3),
    ]
    filtered = _filter_messages(ctx)
    dump("filtered", filtered)
    check("all probes removed", _count_probes(filtered) == 0)
    check("all probe responses removed",
          not any("probe response" in m.get("content","") for m in filtered))
    check("base messages intact", len(filtered) == 3)


def test_probe_followed_by_user_before_response():
    section("Edge case: probe → user message → probe response (no immediate response)")
    # In normal pipecat flow this sequence doesn't occur because the LLM responds
    # before user messages are written to context. Documented here as known behavior.
    ctx = [
        sys(), user("Hello"), assistant("Here."),
        probe(1),
        user("Wait, never mind."),   # user spoke before LLM responded to probe
        probe_response(1),           # LLM response after user message
    ]
    filtered = _filter_messages(ctx)
    dump("filtered (edge case)", filtered)

    # Known behavior: skip_next_assistant flag is reset by the user message,
    # so probe_response(1) is NOT dropped. The probe itself IS dropped.
    check("[edge] probe system message dropped", _count_probes(filtered) == 0)
    check("[edge] user message preserved",
          any("never mind" in m.get("content","") for m in filtered))
    # Document the known behavior: probe_response is NOT dropped here
    probe_resp_present = any("probe response #1" in m.get("content","") for m in filtered)
    check("[edge] probe response kept (expected, reset by user message)",
          probe_resp_present,
          "probe response was unexpectedly dropped")
    print("  NOTE: This sequence doesn't occur in normal pipecat flow.")
    print("        The LLM always responds before user messages reach context.")


def test_total_context_growth():
    section("Context growth over 5 cycles stays constant")
    base = [sys(), user("I'm working on a crossword"), assistant("Let me know if you need help.")]

    ctx = list(base)
    for cycle in range(1, 6):
        sent = simulate_cycle(ctx, probe_n=cycle)
        ctx  = simulate_llm_response(sent, probe_n=cycle)

    dump("final context (5 cycles)", ctx)
    expected_len = len(base) + 2  # base + latest_probe + latest_response
    check(
        f"context size after 5 cycles == {expected_len} (base + 1 probe + 1 response)",
        len(ctx) == expected_len,
        f"got {len(ctx)} messages",
    )
    check("exactly 1 probe in final context", _count_probes(ctx) == 1)
    # Verify no stale probe responses for cycles 1-4
    for stale_n in range(1, 5):
        check(
            f"cycle {stale_n} response not in final context",
            not any(f"probe response #{stale_n}" in m.get("content","") for m in ctx),
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global verbose
    parser = argparse.ArgumentParser(description="ProactiveMonitor context cleanup unit tests.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print filtered message lists")
    args = parser.parse_args()
    verbose = args.verbose

    print("ProactiveMonitor context cleanup — unit tests")
    print("(No API calls. Tests filter logic from _fire_intervention.)\n")

    test_no_probes()
    test_probe_at_end_no_response()
    test_probe_with_response()
    test_three_consecutive_cycles()
    test_user_message_between_cycles()
    test_multiple_probes_in_context()
    test_probe_followed_by_user_before_response()
    test_total_context_growth()

    print(f"\n{'=' * 60}")
    print(f"  TOTAL: {passed + failed} checks  |  PASS: {passed}  FAIL: {failed}")
    if failed == 0:
        print("  RESULT: ALL PASS")
    else:
        print(f"  RESULT: {failed} failing — see above")
    print(f"{'=' * 60}")

    _sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
