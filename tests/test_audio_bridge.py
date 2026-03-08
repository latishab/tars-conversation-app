"""Unit tests for AudioBridge interruption handling (no hardware required)."""

import asyncio
import importlib.util
import sys
import types
import unittest
import numpy as np

# ---------------------------------------------------------------------------
# Stub every external dependency audio_bridge.py imports.
# ---------------------------------------------------------------------------

def _stub(name):
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# loguru
loguru = _stub("loguru")
loguru.logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    debug=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    error=lambda *a, **k: None,
)

# scipy
scipy_mod = _stub("scipy")
scipy_signal = _stub("scipy.signal")
scipy_mod.signal = scipy_signal
scipy_signal.stft = None
scipy_signal.resample_poly = lambda pcm, up, down: pcm  # identity

# aiortc
aiortc_mod = _stub("aiortc")
class _MediaStreamTrack:
    kind = "audio"
    def __init__(self):
        pass
aiortc_mod.MediaStreamTrack = _MediaStreamTrack

# av
av_mod = _stub("av")
class _AVAudioFrame:
    def __init__(self, format, layout, samples):
        self.format = format
        self.layout = layout
        self.samples = samples
        self.sample_rate = 48000
        self.pts = 0
        self.time_base = None
        self.planes = [types.SimpleNamespace(update=lambda b: None)]
av_mod.AudioFrame = _AVAudioFrame

# pipecat frames
for pkg in ["pipecat", "pipecat.frames", "pipecat.frames.frames",
            "pipecat.processors", "pipecat.processors.frame_processor"]:
    if pkg not in sys.modules:
        _stub(pkg)

frames_mod = sys.modules["pipecat.frames.frames"]
for _cls in [
    "Frame", "AudioRawFrame", "InputAudioRawFrame", "OutputAudioRawFrame",
    "TTSStartedFrame", "TTSStoppedFrame", "CancelFrame",
    "BotStartedSpeakingFrame", "BotStoppedSpeakingFrame",
]:
    setattr(frames_mod, _cls, type(_cls, (), {}))

proc_mod = sys.modules["pipecat.processors.frame_processor"]

class _FP:
    def __init__(self):
        self._pushed = []  # [(frame, direction)]

    async def process_frame(self, frame, direction):
        pass

    async def push_frame(self, frame, direction=None):
        self._pushed.append((frame, direction))

    async def _start_interruption(self):
        pass  # base no-op

proc_mod.FrameProcessor = _FP
proc_mod.FrameDirection = type("FrameDirection", (), {"UPSTREAM": "upstream", "DOWNSTREAM": "downstream"})

# tools.robot
tools_mod = _stub("tools")
tools_robot = _stub("tools.robot")
tools_robot.fire_expression = lambda *a, **k: None
tools_mod.robot = tools_robot

# ---------------------------------------------------------------------------
# Load audio_bridge from source, bypassing package __init__
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location(
    "audio_bridge",
    "/Users/mac/Desktop/tars-conversation-app/src/transport/audio_bridge.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

RPiAudioOutputTrack = _mod.RPiAudioOutputTrack
AudioBridge = _mod.AudioBridge

# Grab stub frame classes for use in tests
_frames = sys.modules["pipecat.frames.frames"]
TTSStartedFrame       = _frames.TTSStartedFrame
TTSStoppedFrame       = _frames.TTSStoppedFrame
CancelFrame           = _frames.CancelFrame
OutputAudioRawFrame   = _frames.OutputAudioRawFrame
BotStartedSpeakingFrame  = _frames.BotStartedSpeakingFrame
BotStoppedSpeakingFrame  = _frames.BotStoppedSpeakingFrame
FrameDirection        = sys.modules["pipecat.processors.frame_processor"].FrameDirection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_output_track() -> RPiAudioOutputTrack:
    track = RPiAudioOutputTrack(sample_rate=48000)
    return track


def _make_bridge(output_track=None) -> AudioBridge:
    bridge = AudioBridge(rpi_output_track=output_track)
    return bridge


def _make_audio_frame(num_samples=960) -> OutputAudioRawFrame:
    frame = OutputAudioRawFrame()
    frame.audio = np.zeros(num_samples, dtype=np.int16).tobytes()
    frame.sample_rate = 48000
    frame.num_channels = 1
    return frame


# ---------------------------------------------------------------------------
# RPiAudioOutputTrack.flush() — synchronous tests
# ---------------------------------------------------------------------------

class TestRPiAudioOutputTrackFlush(unittest.TestCase):

    def test_flush_empties_queue(self):
        track = _make_output_track()
        for _ in range(5):
            track._queue.put_nowait(b"\x00\x01" * 100)
        self.assertEqual(track._queue.qsize(), 5)
        track.flush()
        self.assertTrue(track._queue.empty())

    def test_flush_clears_buf(self):
        track = _make_output_track()
        track._buf = np.ones(1000, dtype=np.int16)
        track.flush()
        self.assertEqual(len(track._buf), 0)

    def test_flush_on_empty_track_is_safe(self):
        track = _make_output_track()
        track.flush()  # should not raise
        self.assertTrue(track._queue.empty())
        self.assertEqual(len(track._buf), 0)

    def test_flush_leaves_track_usable(self):
        """flush() does not set _running=False; track should still accept audio."""
        track = _make_output_track()
        track._buf = np.ones(100, dtype=np.int16)
        track._queue.put_nowait(b"\x00" * 20)
        track.flush()
        self.assertTrue(track._running)


# ---------------------------------------------------------------------------
# AudioBridge._speaking flag — via process_frame
# ---------------------------------------------------------------------------

class TestAudioBridgeSpeakingFlag(unittest.TestCase):

    def test_speaking_false_on_init(self):
        bridge = _make_bridge()
        self.assertFalse(bridge._speaking)

    def test_speaking_set_true_on_first_audio_frame(self):
        bridge = _make_bridge(output_track=_make_output_track())
        async def _run():
            await bridge.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
            await bridge.process_frame(_make_audio_frame(), FrameDirection.DOWNSTREAM)
        asyncio.run(_run())
        self.assertTrue(bridge._speaking)

    def test_speaking_not_set_before_tts_started(self):
        """Audio frames without a preceding TTSStartedFrame must not set _speaking."""
        bridge = _make_bridge(output_track=_make_output_track())
        async def _run():
            await bridge.process_frame(_make_audio_frame(), FrameDirection.DOWNSTREAM)
        asyncio.run(_run())
        self.assertFalse(bridge._speaking)

    def test_speaking_cleared_on_tts_stopped(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        async def _run():
            await bridge.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
        asyncio.run(_run())
        self.assertFalse(bridge._speaking)

    def test_speaking_not_cleared_on_cancel(self):
        """CancelFrame flushes audio but does NOT emit BotStoppedSpeakingFrame — _speaking stays."""
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        async def _run():
            await bridge.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM)
        asyncio.run(_run())
        # _speaking is not cleared by CancelFrame (only flush happens)
        self.assertTrue(bridge._speaking)


# ---------------------------------------------------------------------------
# AudioBridge._start_interruption()
# ---------------------------------------------------------------------------

class TestAudioBridgeStartInterruption(unittest.TestCase):

    def test_flushes_output_track(self):
        track = _make_output_track()
        track._queue.put_nowait(b"\x00" * 200)
        track._buf = np.ones(500, dtype=np.int16)
        bridge = _make_bridge(output_track=track)
        asyncio.run(bridge._start_interruption())
        self.assertTrue(track._queue.empty())
        self.assertEqual(len(track._buf), 0)

    def test_resets_tts_started(self):
        bridge = _make_bridge()
        bridge._tts_started = True
        asyncio.run(bridge._start_interruption())
        self.assertFalse(bridge._tts_started)

    def test_emits_bot_stopped_when_speaking(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        asyncio.run(bridge._start_interruption())
        pushed_types = [type(f).__name__ for f, _ in bridge._pushed]
        self.assertIn("BotStoppedSpeakingFrame", pushed_types)

    def test_no_bot_stopped_when_not_speaking(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = False
        asyncio.run(bridge._start_interruption())
        pushed_types = [type(f).__name__ for f, _ in bridge._pushed]
        self.assertNotIn("BotStoppedSpeakingFrame", pushed_types)

    def test_bot_stopped_direction_is_upstream(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        asyncio.run(bridge._start_interruption())
        for frame, direction in bridge._pushed:
            if isinstance(frame, BotStoppedSpeakingFrame):
                self.assertEqual(direction, FrameDirection.UPSTREAM)
                return
        self.fail("BotStoppedSpeakingFrame not found in pushed frames")

    def test_speaking_flag_cleared_after_interruption(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        asyncio.run(bridge._start_interruption())
        self.assertFalse(bridge._speaking)

    def test_safe_without_output_track(self):
        bridge = _make_bridge(output_track=None)
        bridge._speaking = True
        asyncio.run(bridge._start_interruption())  # should not raise
        self.assertFalse(bridge._speaking)


# ---------------------------------------------------------------------------
# CancelFrame flushes audio (safety net path)
# ---------------------------------------------------------------------------

class TestAudioBridgeCancelFrame(unittest.TestCase):

    def test_cancel_flushes_output_track(self):
        track = _make_output_track()
        track._queue.put_nowait(b"\x00" * 200)
        track._buf = np.ones(300, dtype=np.int16)
        bridge = _make_bridge(output_track=track)
        asyncio.run(bridge.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM))
        self.assertTrue(track._queue.empty())
        self.assertEqual(len(track._buf), 0)

    def test_cancel_does_not_emit_bot_stopped(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        asyncio.run(bridge.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM))
        # BotStoppedSpeakingFrame must NOT appear — that's _start_interruption's job
        pushed_types = [type(f).__name__ for f, _ in bridge._pushed]
        self.assertNotIn("BotStoppedSpeakingFrame", pushed_types)

    def test_cancel_resets_tts_started(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._tts_started = True
        asyncio.run(bridge.process_frame(CancelFrame(), FrameDirection.DOWNSTREAM))
        self.assertFalse(bridge._tts_started)


# ---------------------------------------------------------------------------
# TTSStoppedFrame emits BotStoppedSpeakingFrame (normal completion path)
# ---------------------------------------------------------------------------

class TestAudioBridgeTTSStopped(unittest.TestCase):

    def test_tts_stopped_emits_bot_stopped(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        asyncio.run(bridge.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM))
        pushed_types = [type(f).__name__ for f, _ in bridge._pushed]
        self.assertIn("BotStoppedSpeakingFrame", pushed_types)

    def test_tts_stopped_bot_stopped_direction_upstream(self):
        bridge = _make_bridge(output_track=_make_output_track())
        bridge._speaking = True
        asyncio.run(bridge.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM))
        for frame, direction in bridge._pushed:
            if isinstance(frame, BotStoppedSpeakingFrame):
                self.assertEqual(direction, FrameDirection.UPSTREAM)
                return
        self.fail("BotStoppedSpeakingFrame not found")


if __name__ == "__main__":
    unittest.main(verbosity=2)
