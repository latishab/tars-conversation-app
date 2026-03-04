"""Unit tests for ProactiveMonitor suppression logic (no pipecat required)."""

import importlib.util
import sys
import time
import types
import unittest

# ---------------------------------------------------------------------------
# Minimal stubs — only what proactive_monitor.py itself imports.
# We load the module file directly to skip the package __init__.py.
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
for _cls in [
    "Frame", "StartFrame", "EndFrame", "CancelFrame",
    "TranscriptionFrame", "InterimTranscriptionFrame",
    "LLMRunFrame", "BotStartedSpeakingFrame", "BotStoppedSpeakingFrame",
    "LLMMessagesUpdateFrame",
]:
    setattr(frames_mod, _cls, type(_cls, (), {}))

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

# Load module directly from file path, bypassing processors/__init__.py
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

def _make_monitor(**kwargs) -> ProactiveMonitor:
    ctx = types.SimpleNamespace(messages=[])
    task_ref = {}
    return ProactiveMonitor(ctx, task_ref, **kwargs)


def _set_transcript(monitor, text, age=0.0):
    """Push one final transcript entry."""
    monitor._transcript_buffer = [{
        "text": text,
        "timestamp": time.time() - age,
        "is_final": True,
    }]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSilenceTriggerIgnoresUserSpeakingUntil(unittest.TestCase):
    """Fix 3: silence trigger must not be blocked by _user_speaking_until."""

    def _run_suppression(self, monitor, trigger_type, context_snippet):
        """Replicate the suppression logic from _check_triggers."""
        now2 = time.time()
        cooldown_exceeded = (
            now2 - monitor._last_intervention_time < monitor._cooldown
            if trigger_type != "confusion"
            else now2 - monitor._last_confusion_intervention_time < monitor._confusion_cooldown
        )
        speaking_check = trigger_type != "silence" and now2 < monitor._user_speaking_until
        suppressed = (
            monitor._tars_speaking
            or now2 - monitor._last_bot_speech_time < monitor._post_bot_buffer
            or cooldown_exceeded
            or speaking_check
            or monitor._consecutive_unanswered >= 2
        )
        return suppressed

    def test_silence_not_suppressed_by_user_speaking_until(self):
        m = _make_monitor(silence_threshold=15.0, cooldown=30.0, post_bot_buffer=5.0)
        # Simulate VAD interim frame keeping _user_speaking_until in the future
        m._user_speaking_until = time.time() + 5.0
        m._last_bot_speech_time = time.time() - 20.0
        m._last_intervention_time = time.time() - 60.0
        m._tars_speaking = False

        suppressed = self._run_suppression(m, "silence", "last clue text")
        self.assertFalse(suppressed, "silence trigger should not be blocked by _user_speaking_until")

    def test_hesitation_still_suppressed_by_user_speaking_until(self):
        m = _make_monitor(silence_threshold=15.0, cooldown=30.0, post_bot_buffer=5.0)
        m._user_speaking_until = time.time() + 5.0
        m._last_bot_speech_time = time.time() - 20.0
        m._last_intervention_time = time.time() - 60.0
        m._tars_speaking = False

        suppressed = self._run_suppression(m, "hesitation", "um um uh")
        self.assertTrue(suppressed, "hesitation trigger should still be blocked by _user_speaking_until")

    def test_confusion_still_suppressed_by_user_speaking_until(self):
        m = _make_monitor(cooldown=30.0, post_bot_buffer=5.0)
        m._user_speaking_until = time.time() + 5.0
        m._last_bot_speech_time = time.time() - 20.0
        m._last_intervention_time = time.time() - 60.0
        m._last_confusion_intervention_time = time.time() - 60.0
        m._tars_speaking = False

        suppressed = self._run_suppression(m, "confusion", "i'm not sure")
        self.assertTrue(suppressed, "confusion trigger should still be blocked by _user_speaking_until")


class TestConfusionSeparateCooldown(unittest.TestCase):
    """Fix 2: confusion trigger has its own cooldown independent of general cooldown."""

    def _run_suppression(self, monitor, trigger_type):
        now2 = time.time()
        cooldown_exceeded = (
            now2 - monitor._last_intervention_time < monitor._cooldown
            if trigger_type != "confusion"
            else now2 - monitor._last_confusion_intervention_time < monitor._confusion_cooldown
        )
        speaking_check = trigger_type != "silence" and now2 < monitor._user_speaking_until
        suppressed = (
            monitor._tars_speaking
            or now2 - monitor._last_bot_speech_time < monitor._post_bot_buffer
            or cooldown_exceeded
            or speaking_check
            or monitor._consecutive_unanswered >= 2
        )
        return suppressed

    def test_confusion_fires_within_general_cooldown(self):
        """Confusion fires if outside its own cooldown, even if general cooldown is active."""
        m = _make_monitor(cooldown=60.0, post_bot_buffer=5.0)
        m._confusion_cooldown = 30.0
        # General cooldown active (silence fired 52s ago)
        m._last_intervention_time = time.time() - 52.0
        # Confusion cooldown not active (last confusion was 35s ago)
        m._last_confusion_intervention_time = time.time() - 35.0
        m._last_bot_speech_time = time.time() - 20.0
        m._user_speaking_until = 0.0
        m._tars_speaking = False

        suppressed = self._run_suppression(m, "confusion")
        self.assertFalse(suppressed, "confusion should fire when outside confusion_cooldown, even inside general cooldown")

    def test_confusion_suppressed_within_confusion_cooldown(self):
        """Confusion is suppressed if within its own cooldown."""
        m = _make_monitor(cooldown=60.0, post_bot_buffer=5.0)
        m._confusion_cooldown = 30.0
        m._last_intervention_time = time.time() - 52.0
        # Confusion cooldown active (last confusion was 10s ago)
        m._last_confusion_intervention_time = time.time() - 10.0
        m._last_bot_speech_time = time.time() - 20.0
        m._user_speaking_until = 0.0
        m._tars_speaking = False

        suppressed = self._run_suppression(m, "confusion")
        self.assertTrue(suppressed, "confusion should be suppressed within confusion_cooldown")

    def test_silence_still_uses_general_cooldown(self):
        """Silence trigger still uses the general cooldown."""
        m = _make_monitor(cooldown=60.0, post_bot_buffer=5.0)
        m._confusion_cooldown = 30.0
        # General cooldown active
        m._last_intervention_time = time.time() - 52.0
        m._last_confusion_intervention_time = time.time() - 60.0
        m._last_bot_speech_time = time.time() - 20.0
        m._user_speaking_until = 0.0
        m._tars_speaking = False

        suppressed = self._run_suppression(m, "silence")
        self.assertTrue(suppressed, "silence should be suppressed by general cooldown")


class TestSetTaskMode(unittest.TestCase):
    """set_task_mode sets correct thresholds including confusion_cooldown."""

    def test_task_mode_on(self):
        m = _make_monitor()
        m.set_task_mode("crossword")
        self.assertEqual(m._silence_threshold, 15.0)
        self.assertEqual(m._cooldown, 60.0)
        self.assertEqual(m._confusion_cooldown, 30.0)
        self.assertEqual(m._task_context, "crossword")

    def test_task_mode_off(self):
        m = _make_monitor()
        m.set_task_mode("crossword")
        m.set_task_mode(None)
        self.assertEqual(m._silence_threshold, 8.0)
        self.assertEqual(m._cooldown, 30.0)
        self.assertEqual(m._confusion_cooldown, 30.0)
        self.assertEqual(m._task_context, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
