"""ReactiveGate: deterministic suppressor for reactive LLM responses in task mode.

Buffers LLM response frames and on EndFrame decides to flush or suppress based
on recent user utterances. Proactive interventions (flagged by ProactiveMonitor)
always pass through. Outside task mode, always passes through.

Intent is checked over a rolling window of recent utterances rather than the
last segment only — STT frequently splits a single sentence into multiple
short segments (e.g. "Hey Tars, um." / "What's the first letter?"), so the
intent signal may appear several seconds before the final segment.
"""

import time

from loguru import logger
from pipecat.frames.frames import (
    Frame, StartFrame, EndFrame, CancelFrame,
    LLMFullResponseStartFrame, LLMTextFrame, LLMFullResponseEndFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection

# Seconds to look back when checking direct address / directed questions.
# Needs to be long enough to cover STT split segments (e.g. "Hey Tars, um."
# followed by the actual question 2-5s later).
_ADDRESS_WINDOW_SECS = 15.0

# Seconds to look back when checking surrender (CONDITION A) and correction
# (CONDITION C). These are immediate intent signals — if the user said "give me
# the answer" 10s ago and has since moved on to a new clue, that intent has
# expired. Keep this short so carry-over doesn't trigger passthrough on the
# next clue's think-aloud.
_INTENT_WINDOW_SECS = 6.0


# Phrases that mean the user is surrendering and wants the answer.
_CONDITION_A = (
    "just tell me",
    "give me the answer",
    "what's the answer",
    "i give up",
    "tell me the answer",
    "what is it",
)

# Phrases that mean the user is correcting TARS or asking for silence.
# Keep narrow: must be clearly directed at TARS, not pure think-aloud.
# "let me think", "hold on", "i'm still thinking" removed — these are
# think-aloud that should NOT open the gate.
_CONDITION_C = (
    "stop helping",
    "stop answering",
    "don't talk",
    "don't give me",
    "i didn't ask",
    "you shouldn't",
)

# Phrases that imply the user is talking to someone (or TARS specifically).
_DIRECTED_QUESTION = (
    "can you",
    "could you",
    "do you",
    "would you",
    "help me",
    "i need help",
    "i need a hint",
    "i would like a hint",
    "i would like a clue",
    "give me a hint",
    "give me a clue",
    "what do you think",
    "tell me",
    "is it",          # "is it toxic?" — STT may add punctuation so no trailing space
)


class ReactiveGate(FrameProcessor):
    """Buffer-then-decide gate for reactive LLM responses during task mode.

    All non-LLM-response frames pass through immediately. LLM response frames
    (StartFrame, TextFrames, EndFrame) are buffered. On EndFrame the gate
    either flushes the buffer downstream or discards it based on the last
    user utterance and proactive flag.
    """

    def __init__(self, proactive_monitor):
        super().__init__()
        self._monitor = proactive_monitor
        self._buffer: list = []
        self._buffering = False

    def _window(self, secs: float) -> str:
        """Return lowercased text of all transcript entries within the given seconds."""
        cutoff = time.time() - secs
        parts = [
            e.get("text", "")
            for e in self._monitor._transcript_buffer
            if e.get("timestamp", 0) >= cutoff
        ]
        return " ".join(parts).lower()

    def _should_pass_through(self) -> bool:
        """Return True if the buffered response should be passed downstream."""
        if not self._monitor._task_context:
            return True

        if self._monitor._proactive_response_pending:
            logger.info("ReactiveGate: proactive passthrough")
            self._monitor._proactive_response_pending = False
            return True

        if self._monitor._task_mode_just_activated:
            logger.info("ReactiveGate: task mode activation passthrough")
            self._monitor._task_mode_just_activated = False
            return True

        buf = self._monitor._transcript_buffer
        if not buf:
            return True

        # Surrender and correction intent expires quickly — if the user said
        # "give me the answer" 8s ago and has already moved on to a new clue,
        # that intent should not carry over to the new think-aloud.
        short_window = self._window(_INTENT_WINDOW_SECS)

        for phrase in _CONDITION_A:
            if phrase in short_window:
                return True

        for phrase in _CONDITION_C:
            if phrase in short_window:
                return True

        # Direct address and directed questions use a longer window to handle
        # STT split segments (e.g. "Hey Tars, um." arrives 2-5s before the
        # actual question in the next STT segment).
        long_window = self._window(_ADDRESS_WINDOW_SECS)

        if "tars" in long_window:
            return True

        for phrase in _DIRECTED_QUESTION:
            if phrase in long_window:
                return True

        return False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, (StartFrame, EndFrame)):
            self._buffer.clear()
            self._buffering = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, CancelFrame):
            self._buffer.clear()
            self._buffering = False
            self._monitor._proactive_response_pending = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._buffer.clear()
            self._buffer.append((frame, direction))
            self._buffering = True
            return

        if isinstance(frame, LLMTextFrame) and self._buffering:
            self._buffer.append((frame, direction))
            return

        if isinstance(frame, LLMFullResponseEndFrame) and self._buffering:
            self._buffering = False
            if self._should_pass_through():
                for f, d in self._buffer:
                    await self.push_frame(f, d)
                self._buffer.clear()
                await self.push_frame(frame, direction)
            else:
                window = self._window(15)
                logger.info(f"ReactiveGate: suppressed reactive response — window: {window[:120]!r}")
                self._buffer.clear()
            return

        await self.push_frame(frame, direction)
