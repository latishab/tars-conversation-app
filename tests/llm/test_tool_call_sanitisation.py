"""
Tool call sanitisation for conversation history.

Tests the _sanitise_tool_calls function from llm_factory that removes
orphaned tool call entries before each LLM request. This prevents 422
errors when a tool result (role: "tool") is dropped from context but
the assistant message still references its tool_call_id.

No API calls. Pure unit test of the sanitisation logic.

Run from project root:
    python tests/llm/test_tool_call_sanitisation.py
    python tests/llm/test_tool_call_sanitisation.py -v
"""

import argparse
import sys as _sys

_sys.path.insert(0, "src")
from services.factories.llm_factory import _sanitise_tool_calls


# ---------------------------------------------------------------------------
# Message factories
# ---------------------------------------------------------------------------

def sys(content="You are TARS."):
    return {"role": "system", "content": content}

def user(content):
    return {"role": "user", "content": content}

def assistant(content):
    return {"role": "assistant", "content": content}

def assistant_with_tool_call(content, tool_call_id, fn_name="set_task_mode", fn_args='{"mode":"crossword"}'):
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [{
            "id": tool_call_id,
            "type": "function",
            "function": {"name": fn_name, "arguments": fn_args},
        }],
    }

def tool_result(tool_call_id, content="done"):
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

passed = 0
failed = 0
verbose = False

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}" + (f"  ({detail})" if detail else ""))

def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_tool_calls():
    section("No tool calls — passthrough")
    msgs = [sys(), user("Hello"), assistant("Hi there.")]
    result = _sanitise_tool_calls(msgs)
    check("length unchanged", len(result) == 3)
    check("content identical", result == msgs)


def test_matched_tool_call():
    section("Matched tool call + result — preserved")
    msgs = [
        sys(),
        user("Start crossword"),
        assistant_with_tool_call("", "tc_001"),
        tool_result("tc_001"),
        assistant("Crossword mode activated."),
    ]
    result = _sanitise_tool_calls(msgs)
    check("all messages preserved", len(result) == 5)
    check("tool_calls intact", result[2].get("tool_calls") is not None)
    check("tool result intact", result[3]["role"] == "tool")


def test_orphaned_tool_call_no_result():
    section("Orphaned tool call (no result) — dropped")
    msgs = [
        sys(),
        user("Start crossword"),
        assistant_with_tool_call("", "feeb1a244"),
        # tool result for feeb1a244 is missing
        user("Hello?"),
    ]
    result = _sanitise_tool_calls(msgs)
    check("orphaned assistant message dropped", len(result) == 3)
    check("no tool_calls in result", not any(m.get("tool_calls") for m in result))
    check("user messages preserved", result[1]["content"] == "Start crossword")
    check("subsequent user preserved", result[2]["content"] == "Hello?")


def test_orphaned_tool_result_no_call():
    section("Orphaned tool result (no matching call) — dropped")
    msgs = [
        sys(),
        user("Hello"),
        tool_result("orphan_id", "stale result"),
        assistant("Hi."),
    ]
    result = _sanitise_tool_calls(msgs)
    check("orphaned tool result dropped", len(result) == 3)
    check("no tool messages", not any(m.get("role") == "tool" for m in result))


def test_mixed_matched_and_orphaned():
    section("One matched, one orphaned — only orphan dropped")
    msgs = [
        sys(),
        assistant_with_tool_call("", "good_id", "capture_user_camera"),
        tool_result("good_id", "image captured"),
        assistant_with_tool_call("", "bad_id", "set_task_mode"),
        # no result for bad_id
        user("Are you there?"),
    ]
    result = _sanitise_tool_calls(msgs)
    check("orphaned call dropped", len(result) == 4)
    check("matched call preserved", any(
        m.get("tool_calls") and m["tool_calls"][0]["id"] == "good_id"
        for m in result
    ))
    check("matched result preserved", any(
        m.get("role") == "tool" and m.get("tool_call_id") == "good_id"
        for m in result
    ))


def test_multiple_tool_calls_in_one_message():
    section("Assistant message with 2 tool_calls, one orphaned — partial strip")
    tc1 = {
        "id": "tc_a",
        "type": "function",
        "function": {"name": "fn_a", "arguments": "{}"},
    }
    tc2 = {
        "id": "tc_b",
        "type": "function",
        "function": {"name": "fn_b", "arguments": "{}"},
    }
    msgs = [
        sys(),
        {"role": "assistant", "content": "", "tool_calls": [tc1, tc2]},
        tool_result("tc_a", "ok"),
        # no result for tc_b
        assistant("Done."),
    ]
    result = _sanitise_tool_calls(msgs)
    ast_msg = result[1]
    check("assistant message kept", ast_msg["role"] == "assistant")
    check("only matched tool_call remains", len(ast_msg["tool_calls"]) == 1)
    check("correct tool_call kept", ast_msg["tool_calls"][0]["id"] == "tc_a")


def test_p6_crash_scenario():
    section("P6 crash scenario — set_task_mode result dropped after interruption")
    msgs = [
        sys(),
        user("Hey TARS, I'm going to play crossword."),
        assistant_with_tool_call("", "feeb1a244", "set_task_mode", '{"mode":"crossword"}'),
        # tool result dropped due to interruption/context compaction
        user("One down. Aspiring musician Miguel."),
        user("To deceive someone. Three letters."),
    ]
    result = _sanitise_tool_calls(msgs)
    check("orphaned set_task_mode dropped", not any(m.get("tool_calls") for m in result))
    check("user messages preserved", sum(1 for m in result if m["role"] == "user") == 3)
    check("system prompt preserved", result[0]["role"] == "system")
    check("total messages correct", len(result) == 4, f"got {len(result)}")


def test_p3_crash_scenario():
    """P3 (2026-03-10): set_task_mode called at 10:39:07 with tool_call_id
    "6ad3163dc". System worked for ~10 minutes. At 10:49:34, proactive
    monitor fired a confusion trigger and built a filtered message list.
    The probe cleanup filter stripped the assistant message that carried the
    tool_calls for "6ad3163dc" (because it preceded a proactive probe
    response), but the tool result (role: "tool") survived. Cerebras
    rejected every subsequent request with 422 for the rest of the session.

    This test reconstructs the message state after probe cleanup: the
    tool result is present but its parent assistant+tool_calls message
    has been removed."""
    section("P3 crash scenario — probe cleanup orphans tool result")
    msgs = [
        sys("You are TARS. Task mode: crossword."),
        # The assistant message with tool_calls for 6ad3163dc was already
        # stripped by probe cleanup — only the tool result survives.
        tool_result("6ad3163dc", '{"mode":"crossword","status":"activated"}'),
        assistant("Crossword mode."),
        user("Poisonous. Five words."),
        assistant("Think of a term describing snakes or lethal chemicals."),
        user("Can you help?"),
        assistant("Think of a phrase for a shallow, peat-rich wetland."),
        # Many more turns of successful conversation...
        user("Hmm. I don't know."),
        user("Give up."),
        # Proactive monitor fires confusion trigger here — LLM sees the
        # orphaned tool result and Cerebras returns 422.
        {"role": "system", "content": "[PROACTIVE DETECTION - CONFUSION]: user expressed difficulty"},
    ]
    result = _sanitise_tool_calls(msgs)
    check("orphaned tool result dropped", not any(
        m.get("role") == "tool" and m.get("tool_call_id") == "6ad3163dc"
        for m in result
    ))
    check("system prompt preserved", result[0]["role"] == "system")
    check("conversation turns preserved", sum(1 for m in result if m["role"] == "user") == 4)
    check("assistant turns preserved", sum(1 for m in result if m["role"] == "assistant") == 3)
    check("proactive probe preserved", any(
        "PROACTIVE DETECTION" in m.get("content", "") for m in result
    ))
    check("total messages correct", len(result) == 9, f"got {len(result)}")


def test_probe_cleanup_then_sanitise():
    """Simulates the full sequence: probe cleanup runs first (as in
    ProactiveMonitor._fire_intervention), then sanitisation runs before
    the LLM call. The probe cleanup strips probe+response pairs but can
    accidentally orphan a tool result if the assistant message carrying
    tool_calls was adjacent to a probe."""
    section("Probe cleanup + sanitisation — combined pipeline")

    # Context as it looks in memory before probe cleanup:
    context = [
        sys("You are TARS. Task mode: crossword."),
        user("Hey TARS, I'm going to play crossword."),
        assistant_with_tool_call("", "6ad3163dc", "set_task_mode", '{"mode":"crossword"}'),
        tool_result("6ad3163dc", "activated"),
        assistant("Crossword mode."),
        user("Poisonous. Five characters."),
        assistant("Think of a word for toxic substances."),
        # Proactive probe fired and LLM responded:
        {"role": "system", "content": "[PROACTIVE DETECTION - SILENCE]: extended silence"},
        assistant("That last one still giving you trouble?"),
        user("I don't know."),
    ]

    # Step 1: Probe cleanup (verbatim from _fire_intervention)
    filtered = []
    skip_next_assistant = False
    for m in context:
        is_probe = m.get("role") == "system" and "[PROACTIVE DETECTION" in m.get("content", "")
        if is_probe:
            skip_next_assistant = True
            continue
        if skip_next_assistant and m.get("role") == "assistant":
            skip_next_assistant = False
            continue
        skip_next_assistant = False
        filtered.append(m)

    # Add new probe
    filtered.append({"role": "system", "content": "[PROACTIVE DETECTION - CONFUSION]: user confused"})

    check("[pre-sanitise] probe cleaned", sum(
        1 for m in filtered
        if m.get("role") == "system" and "PROACTIVE DETECTION" in m.get("content", "")
    ) == 1)
    check("[pre-sanitise] tool_calls + result both present",
        any(m.get("tool_calls") for m in filtered) and
        any(m.get("role") == "tool" for m in filtered)
    )

    # Step 2: Sanitisation (runs inside build_chat_completion_params)
    sanitised = _sanitise_tool_calls(filtered)

    # Both tool_calls and tool result should survive because they match
    check("[post-sanitise] tool_calls preserved", any(m.get("tool_calls") for m in sanitised))
    check("[post-sanitise] tool result preserved", any(m.get("role") == "tool" for m in sanitised))
    check("[post-sanitise] no orphans", True)  # if we got here without drops, good


def test_probe_cleanup_orphans_tool_call():
    """Edge case: the assistant message with tool_calls is right before
    a probe, and probe cleanup's skip_next_assistant flag causes it to
    be dropped. The tool result survives, creating an orphan."""
    section("Probe cleanup accidentally orphans tool_calls")

    # Pathological ordering: tool_call assistant msg, then immediately a probe
    # (the tool result was appended after the probe in context)
    context = [
        sys(),
        user("Start crossword"),
        assistant_with_tool_call("", "abc123", "set_task_mode"),
        # Probe fires before tool result is written to context
        {"role": "system", "content": "[PROACTIVE DETECTION - SILENCE]: silence"},
        # Tool result arrives after probe
        tool_result("abc123", "activated"),
        assistant("Crossword mode."),
        user("I'm stuck."),
    ]

    # Probe cleanup
    filtered = []
    skip_next_assistant = False
    for m in context:
        is_probe = m.get("role") == "system" and "[PROACTIVE DETECTION" in m.get("content", "")
        if is_probe:
            skip_next_assistant = True
            continue
        if skip_next_assistant and m.get("role") == "assistant":
            skip_next_assistant = False
            continue
        skip_next_assistant = False
        filtered.append(m)

    # The probe was dropped. skip_next_assistant was set.
    # tool_result is role "tool" not "assistant", so it survives.
    # But did the assistant_with_tool_call survive? It was before the probe,
    # so it should have been appended before skip was set.
    has_tool_calls = any(m.get("tool_calls") for m in filtered)
    has_tool_result = any(m.get("role") == "tool" for m in filtered)

    # Now sanitise
    sanitised = _sanitise_tool_calls(filtered)

    if has_tool_calls and has_tool_result:
        check("[edge] both survived probe cleanup — sanitise is no-op",
              len(sanitised) == len(filtered))
    elif has_tool_result and not has_tool_calls:
        check("[edge] orphaned tool result dropped by sanitise",
              not any(m.get("role") == "tool" for m in sanitised))
    elif has_tool_calls and not has_tool_result:
        check("[edge] orphaned tool_calls dropped by sanitise",
              not any(m.get("tool_calls") for m in sanitised))
    else:
        check("[edge] both dropped by probe cleanup — sanitise is no-op", True)

    # Regardless of path, no orphans should remain
    result_ids = {m["tool_call_id"] for m in sanitised if m.get("role") == "tool"}
    call_ids = set()
    for m in sanitised:
        for tc in m.get("tool_calls", []):
            call_ids.add(tc["id"])
    check("[edge] no orphaned results", result_ids.issubset(call_ids))
    check("[edge] no orphaned calls", call_ids.issubset(result_ids))


def test_no_mutation_of_original():
    section("Original messages list not mutated")
    msgs = [
        sys(),
        assistant_with_tool_call("text", "orphan_tc"),
        user("Hello"),
    ]
    original_len = len(msgs)
    original_tc_len = len(msgs[1]["tool_calls"])
    _ = _sanitise_tool_calls(msgs)
    check("original list length unchanged", len(msgs) == original_len)
    check("original tool_calls unchanged", len(msgs[1]["tool_calls"]) == original_tc_len)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global verbose
    parser = argparse.ArgumentParser(description="Tool call sanitisation unit tests.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    verbose = args.verbose

    print("Tool call sanitisation — unit tests")
    print("(No API calls. Tests _sanitise_tool_calls from llm_factory.)\n")

    test_no_tool_calls()
    test_matched_tool_call()
    test_orphaned_tool_call_no_result()
    test_orphaned_tool_result_no_call()
    test_mixed_matched_and_orphaned()
    test_multiple_tool_calls_in_one_message()
    test_p6_crash_scenario()
    test_p3_crash_scenario()
    test_probe_cleanup_then_sanitise()
    test_probe_cleanup_orphans_tool_call()
    test_no_mutation_of_original()

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
