"""Unit tests for the code-level set_task_mode('off') guard in persona.py."""

import asyncio
import importlib.util
import sys
import types
import unittest

# ---------------------------------------------------------------------------
# Minimal stubs for pipecat dependencies
# ---------------------------------------------------------------------------

def _make_stub(name):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod

for _pkg in [
    "pipecat", "pipecat.adapters", "pipecat.adapters.schemas",
    "pipecat.adapters.schemas.function_schema",
    "pipecat.services", "pipecat.services.llm_service",
]:
    if _pkg not in sys.modules:
        _make_stub(_pkg)

# FunctionSchema stub
class _FunctionSchema:
    def __init__(self, **kwargs):
        pass

sys.modules["pipecat.adapters.schemas.function_schema"].FunctionSchema = _FunctionSchema

# FunctionCallParams stub
class _FunctionCallParams:
    def __init__(self, arguments, result_cb):
        self.arguments = arguments
        self._result_cb = result_cb

    async def result_callback(self, msg):
        await self._result_cb(msg)

sys.modules["pipecat.services.llm_service"].FunctionCallParams = _FunctionCallParams

# Load persona module
import os
_persona_path = os.path.join(os.path.dirname(__file__), "..", "src", "tools", "persona.py")
spec = importlib.util.spec_from_file_location("persona", _persona_path)
persona_mod = importlib.util.module_from_spec(spec)

# Stub character.prompts before loading
_char_prompts = _make_stub("character")
_char_prompts_sub = _make_stub("character.prompts")
_char_prompts_sub.build_tars_system_prompt = lambda *a, **kw: {"role": "system", "content": "stub"}
spec.loader.exec_module(persona_mod)

set_task_mode = persona_mod.set_task_mode
_storage = persona_mod.get_persona_storage()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeContext:
    def __init__(self, messages):
        self.messages = messages


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_params(mode, last_user_text):
    result = []
    ctx = _FakeContext([
        {"role": "system", "content": "stub"},
        {"role": "assistant", "content": "Crossword mode."},
        {"role": "user", "content": last_user_text},
    ])
    _storage["task_mode"] = "crossword"
    _storage["context"] = ctx
    _storage["persona_params"] = {}
    _storage["tars_data"] = {}

    async def cb(msg):
        result.append(msg)

    params = _FunctionCallParams(arguments={"mode": mode}, result_cb=cb)
    return params, result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSetTaskModeGuard(unittest.TestCase):

    def tearDown(self):
        # Reset storage after each test
        _storage["task_mode"] = None
        _storage["context"] = None
        _storage["proactive_monitor"] = None

    # -- Guard triggers: should REJECT 'off' ----------------------------------

    def test_rejects_two_word_filler(self):
        """'I, um.' (2 words) must not exit task mode."""
        params, result = _make_params("off", "I, um.")
        _run(set_task_mode(params))
        self.assertIn("Task mode stays active", result[0])
        self.assertEqual(_storage["task_mode"], "crossword")

    def test_rejects_single_filler(self):
        params, result = _make_params("off", "Uh.")
        _run(set_task_mode(params))
        self.assertIn("Task mode stays active", result[0])

    def test_rejects_four_word_fragment(self):
        """Exactly 4 words — boundary case, should reject."""
        params, result = _make_params("off", "okay I got it")
        _run(set_task_mode(params))
        self.assertIn("Task mode stays active", result[0])

    def test_rejects_pure_filler_burst(self):
        params, result = _make_params("off", "um uh hmm")
        _run(set_task_mode(params))
        self.assertIn("Task mode stays active", result[0])

    # -- Guard does NOT trigger: should ALLOW 'off' ---------------------------

    def test_allows_explicit_done(self):
        """'I'm done with the crossword' — clear task-end signal, must pass."""
        params, result = _make_params("off", "I'm done with the crossword")
        _run(set_task_mode(params))
        # result_callback fires with the task mode label, not the rejection message
        self.assertFalse(any("stays active" in r for r in result))

    def test_allows_stop_command(self):
        # 5 words — above the ≤4 word threshold
        params, result = _make_params("off", "okay let's stop for today")
        _run(set_task_mode(params))
        self.assertFalse(any("stays active" in r for r in result))

    def test_allows_five_words(self):
        """5 words with non-filler content — should not be blocked."""
        params, result = _make_params("off", "okay I am all done")
        _run(set_task_mode(params))
        self.assertFalse(any("stays active" in r for r in result))

    def test_guard_skipped_when_task_mode_already_off(self):
        """Guard only applies when task mode is currently active."""
        params, result = _make_params("off", "um")
        _storage["task_mode"] = None  # already off
        _run(set_task_mode(params))
        self.assertFalse(any("stays active" in r for r in result))

    def test_guard_skipped_for_on_call(self):
        """Guard does not interfere with turning task mode ON."""
        params, result = _make_params("crossword", "I'm going to do a crossword")
        _storage["task_mode"] = None
        _run(set_task_mode(params))
        self.assertFalse(any("stays active" in r for r in result))


if __name__ == "__main__":
    unittest.main()
