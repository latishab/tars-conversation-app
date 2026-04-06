"""Tests for proactive intervention system message content and context cleanup.

Covers:
- Notification/Suggestion/No-Answer hierarchy present in both task and non-task probes
- Direct answer prohibition in both paths
- Reactive exception ("will ask") stated explicitly
- Context cleanup: old probe/response pairs stripped before each new fire
- Large context: cleanup scales correctly, non-probe messages preserved
"""

import asyncio
import importlib.util
import sys
import time
import types
import unittest


# ---------------------------------------------------------------------------
# Minimal stubs — must register before loading proactive_monitor.py
# ---------------------------------------------------------------------------

def _make_stub_module(name):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


for _pkg in [
    "pipecat", "pipecat.frames", "pipecat.frames.frames",
    "pipecat.processors", "pipecat.processors.frame_processor",
]:
    if _pkg not in sys.modules:
        _make_stub_module(_pkg)

frames_mod = sys.modules["pipecat.frames.frames"]

# Give LLMMessagesUpdateFrame a real __init__ so we can inspect messages.
class _LLMMessagesUpdateFrame:
    def __init__(self, messages=None, run_llm=True):
        self.messages = messages or []
        self.run_llm = run_llm

for _cls in [
    "Frame", "StartFrame", "EndFrame", "CancelFrame",
    "TranscriptionFrame", "InterimTranscriptionFrame",
    "LLMRunFrame", "BotStartedSpeakingFrame", "BotStoppedSpeakingFrame",
]:
    if not hasattr(frames_mod, _cls):
        setattr(frames_mod, _cls, type(_cls, (), {}))

frames_mod.LLMMessagesUpdateFrame = _LLMMessagesUpdateFrame

proc_mod = sys.modules["pipecat.processors.frame_processor"]

class _FP:
    def __init__(self):
        pass
    async def process_frame(self, frame, direction):
        pass
    def create_task(self, coro, name=""):
        pass
    async def push_frame(self, frame, direction):
        pass

proc_mod.FrameProcessor = _FP
proc_mod.FrameDirection = type("FrameDirection", (), {})

_spec = importlib.util.spec_from_file_location(
    "proactive_monitor",
    "/Users/mac/Desktop/tars-conversation-app/src/processors/proactive_monitor.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
ProactiveMonitor = _mod.ProactiveMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockTask:
    """Captures frames queued by _fire_intervention."""
    def __init__(self):
        self.queued_frames = []

    async def queue_frames(self, frames):
        self.queued_frames.extend(frames)


def _make_monitor(task_context="", **kwargs) -> ProactiveMonitor:
    ctx = types.SimpleNamespace(messages=[])
    task_ref = {}
    m = ProactiveMonitor(ctx, task_ref, **kwargs)
    if task_context:
        m.set_task_mode(task_context)
    return m


def _wire_task(monitor) -> _MockTask:
    mock = _MockTask()
    monitor._task_ref["task"] = mock
    return mock


def _get_update_frame(mock_task) -> _LLMMessagesUpdateFrame:
    """Return the LLMMessagesUpdateFrame from the most recent queue_frames call."""
    for frame in mock_task.queued_frames:
        if isinstance(frame, _LLMMessagesUpdateFrame):
            return frame
    raise AssertionError("No LLMMessagesUpdateFrame found in queued frames")


def _probe_system_msg(content: str) -> dict:
    return {"role": "system", "content": f"[PROACTIVE DETECTION - SILENCE]: {content}"}


def _assistant_msg(content: str) -> dict:
    return {"role": "assistant", "content": content}


def _user_msg(content: str) -> dict:
    return {"role": "user", "content": content}


# ---------------------------------------------------------------------------
# 1. System message content — hierarchy language
# ---------------------------------------------------------------------------

class TestProbeSystemMessageContent(unittest.IsolatedAsyncioTestCase):
    """_fire_intervention must embed the Notification/Suggestion/No-Answer hierarchy."""

    async def _fire_and_get_probe(self, monitor) -> str:
        mock = _wire_task(monitor)
        await monitor._fire_intervention("silence", "test clue about something")
        frame = _get_update_frame(mock)
        probe_msg = frame.messages[-1]
        self.assertEqual(probe_msg["role"], "system")
        self.assertIn("[PROACTIVE DETECTION", probe_msg["content"])
        return probe_msg["content"]

    # --- Non-task path ---

    async def test_non_task_probe_contains_notification(self):
        m = _make_monitor()
        content = await self._fire_and_get_probe(m)
        self.assertIn("Notification", content)

    async def test_non_task_probe_contains_suggestion(self):
        m = _make_monitor()
        content = await self._fire_and_get_probe(m)
        self.assertIn("Suggestion", content)

    async def test_non_task_probe_prohibits_direct_answer(self):
        m = _make_monitor()
        content = await self._fire_and_get_probe(m)
        # Must explicitly say not to give the answer directly
        self.assertIn("Never give the answer directly", content)

    async def test_non_task_probe_acknowledges_reactive_exception(self):
        """Must state that giving the answer on explicit request is fine (reactive path)."""
        m = _make_monitor()
        content = await self._fire_and_get_probe(m)
        # "they will ask" or "reactive" or "will ask" signals the exception
        has_exception = "will ask" in content or "reactive" in content
        self.assertTrue(has_exception,
            "Probe must acknowledge that direct answers are fine when explicitly requested")

    async def test_non_task_probe_silence_on_false_positive(self):
        m = _make_monitor()
        content = await self._fire_and_get_probe(m)
        self.assertIn('{"action": "silence"}', content)

    # --- Task mode path ---

    async def test_task_mode_probe_contains_notification(self):
        m = _make_monitor(task_context="crossword")
        content = await self._fire_and_get_probe(m)
        self.assertIn("Notification", content)

    async def test_task_mode_probe_contains_suggestion(self):
        # Confusion trigger uses Suggestion-level; silence uses Notification-level
        m = _make_monitor(task_context="crossword")
        mock = _wire_task(m)
        await m._fire_intervention("confusion", "test clue about something")
        frame = _get_update_frame(mock)
        content = frame.messages[-1]["content"]
        self.assertIn("Suggestion", content)

    async def test_task_mode_probe_prohibits_direct_answer(self):
        m = _make_monitor(task_context="crossword")
        content = await self._fire_and_get_probe(m)
        # Probe must prohibit giving the direct answer (phrased as "not the answer")
        self.assertIn("not the answer", content)

    async def test_task_mode_probe_acknowledges_reactive_exception(self):
        # Task mode directs the model to re-engage only when directly addressed
        m = _make_monitor(task_context="crossword")
        content = await self._fire_and_get_probe(m)
        self.assertIn("directly address you", content)

    async def test_task_mode_probe_defaults_to_silence(self):
        m = _make_monitor(task_context="crossword")
        content = await self._fire_and_get_probe(m)
        self.assertIn('{"action": "silence"}', content)

    async def test_task_mode_probe_includes_task_context_name(self):
        m = _make_monitor(task_context="crossword")
        content = await self._fire_and_get_probe(m)
        self.assertIn("crossword", content)

    async def test_probe_includes_context_snippet(self):
        m = _make_monitor()
        mock = _wire_task(m)
        snippet = "14 down, garbage holder, three letters"
        await monitor._fire_intervention("silence", snippet) if False else None
        mock2 = _wire_task(m)
        await m._fire_intervention("silence", snippet)
        frame = _get_update_frame(mock2)
        probe_content = frame.messages[-1]["content"]
        self.assertIn(snippet, probe_content)

    # --- Unanswered probe note ---

    async def test_second_probe_includes_unanswered_note(self):
        m = _make_monitor()
        mock = _wire_task(m)
        # First fire
        await m._fire_intervention("silence", "ctx")
        mock.queued_frames.clear()
        # Second fire (consecutive_unanswered is now 1 from first fire)
        await m._fire_intervention("silence", "ctx")
        frame = _get_update_frame(mock)
        probe_content = frame.messages[-1]["content"]
        self.assertIn("unanswered probe", probe_content)


# ---------------------------------------------------------------------------
# 2. Context cleanup — old probe/response pairs stripped
# ---------------------------------------------------------------------------

class TestProbeContextCleanup(unittest.IsolatedAsyncioTestCase):
    """_fire_intervention strips prior [PROACTIVE DETECTION] messages before firing."""

    async def _fire_and_get_messages(self, monitor) -> list:
        mock = _wire_task(monitor)
        await monitor._fire_intervention("silence", "some context")
        frame = _get_update_frame(mock)
        return frame.messages

    async def test_previous_probe_stripped(self):
        """A single prior probe + its assistant reply are removed."""
        m = _make_monitor()
        m._context.messages = [
            _user_msg("I'm working on this"),
            _probe_system_msg("Previous probe content"),
            _assistant_msg("Stuck on something?"),
            _user_msg("yeah a bit"),
        ]
        msgs = await self._fire_and_get_messages(m)
        probe_msgs = [x for x in msgs if "[PROACTIVE DETECTION" in x.get("content", "")]
        # Only the new probe should remain (the last message)
        self.assertEqual(len(probe_msgs), 1)
        # The new probe is the last message
        self.assertEqual(msgs[-1]["role"], "system")
        self.assertIn("[PROACTIVE DETECTION", msgs[-1]["content"])

    async def test_previous_probe_assistant_reply_stripped(self):
        """The assistant reply immediately after a probe is also stripped."""
        m = _make_monitor()
        old_assistant_reply = "Let me know if you need a nudge."
        m._context.messages = [
            _probe_system_msg("Old probe"),
            _assistant_msg(old_assistant_reply),
        ]
        msgs = await self._fire_and_get_messages(m)
        contents = [x.get("content", "") for x in msgs]
        self.assertNotIn(old_assistant_reply, contents)

    async def test_non_probe_messages_preserved(self):
        """Regular user/assistant messages are not stripped."""
        m = _make_monitor()
        m._context.messages = [
            _user_msg("Hello"),
            _assistant_msg("Hey."),
            _user_msg("I'm working on a crossword"),
        ]
        msgs = await self._fire_and_get_messages(m)
        # All three originals should survive, plus the new probe
        self.assertEqual(len(msgs), 4)
        self.assertEqual(msgs[0]["content"], "Hello")
        self.assertEqual(msgs[1]["content"], "Hey.")
        self.assertEqual(msgs[2]["content"], "I'm working on a crossword")

    async def test_large_context_stripped_correctly(self):
        """With many accumulated probe/response pairs, cleanup leaves only non-probe messages + new probe."""
        m = _make_monitor()
        # Build a large context: 5 regular turns + 10 probe/response pairs interleaved
        messages = []
        for i in range(5):
            messages.append(_user_msg(f"user turn {i}"))
            messages.append(_assistant_msg(f"tars turn {i}"))
        for i in range(10):
            messages.append(_probe_system_msg(f"probe {i}"))
            messages.append(_assistant_msg(f"probe response {i}"))
        m._context.messages = messages

        msgs = await self._fire_and_get_messages(m)

        # Non-probe messages: 5 user + 5 assistant = 10
        # Plus the new probe at the end = 11 total
        non_probe = [x for x in msgs if "[PROACTIVE DETECTION" not in x.get("content", "")]
        probe_msgs = [x for x in msgs if "[PROACTIVE DETECTION" in x.get("content", "")]

        self.assertEqual(len(non_probe), 10, "All 10 regular messages should be preserved")
        self.assertEqual(len(probe_msgs), 1, "Only the new probe message should remain")

    async def test_large_context_probe_assistant_replies_stripped(self):
        """Probe-associated assistant replies (the 10 'probe response N') are all removed."""
        m = _make_monitor()
        messages = []
        for i in range(10):
            messages.append(_probe_system_msg(f"probe {i}"))
            messages.append(_assistant_msg(f"probe response {i}"))
        m._context.messages = messages

        msgs = await self._fire_and_get_messages(m)

        # Only the new probe should exist — all old probe+reply pairs gone
        self.assertEqual(len(msgs), 1)
        self.assertIn("[PROACTIVE DETECTION", msgs[0]["content"])

    async def test_new_probe_is_last_message(self):
        """The newly injected probe message is always the final message in the list."""
        m = _make_monitor()
        m._context.messages = [
            _user_msg("some prior turn"),
            _probe_system_msg("old probe"),
            _assistant_msg("old response"),
        ]
        msgs = await self._fire_and_get_messages(m)
        self.assertEqual(msgs[-1]["role"], "system")
        self.assertIn("[PROACTIVE DETECTION", msgs[-1]["content"])

    async def test_context_with_only_regular_messages(self):
        """Clean context (no prior probes) passes through unchanged plus new probe."""
        m = _make_monitor()
        m._context.messages = [
            _user_msg("Hi"),
            _assistant_msg("Hey."),
        ]
        msgs = await self._fire_and_get_messages(m)
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[0]["content"], "Hi")
        self.assertEqual(msgs[1]["content"], "Hey.")
        self.assertIn("[PROACTIVE DETECTION", msgs[2]["content"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
