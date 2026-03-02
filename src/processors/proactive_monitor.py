import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from loguru import logger
from pipecat.frames.frames import (
    Frame, StartFrame, EndFrame, CancelFrame,
    TranscriptionFrame, InterimTranscriptionFrame,
    LLMRunFrame, LLMFullResponseEndFrame, BotStartedSpeakingFrame,
    LLMMessagesUpdateFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


HESITATION_WEIGHTS = {"um": 2, "uh": 1, "hmm": 1, "er": 1, "ah": 1}

CONFUSION_PATTERNS = [
    "i don't know", "no idea", "i'm stuck", "this is hard",
    "i can't figure", "i can't remember", "help me", "i need help",
    "what does this mean", "i'm confused", "i have no idea", "i'm not sure",
]


class ProactiveMonitor(FrameProcessor):
    def __init__(
        self,
        context,
        task_ref: dict,
        silence_threshold: float = 8.0,
        hesitation_threshold: int = 4,
        hesitation_window: float = 5.0,
        cooldown: float = 30.0,
        post_bot_buffer: float = 5.0,
        check_interval: float = 1.0,
        enabled: bool = True,
    ):
        super().__init__()
        self._context = context
        self._task_ref = task_ref
        self._silence_threshold = silence_threshold
        self._hesitation_threshold = hesitation_threshold
        self._hesitation_window = hesitation_window
        self._cooldown = cooldown
        self._post_bot_buffer = post_bot_buffer
        self._check_interval = check_interval
        self._enabled = enabled

        self._transcript_buffer: list[dict] = []
        self._last_bot_speech_time: float = 0.0
        self._last_intervention_time: float = 0.0
        self._task_start_time: float = 0.0
        self._last_checked_transcript_time: float = 0.0
        self._task_active: bool = False
        self._user_speaking: bool = False
        self._speaking_reset_task: Optional[asyncio.Task] = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._task_active = True
            self._task_start_time = time.time()
            if self._enabled:
                self.create_task(self._monitor_loop(), "proactive_monitor")

        elif isinstance(frame, (EndFrame, CancelFrame)):
            self._task_active = False

        elif isinstance(frame, TranscriptionFrame):
            self._transcript_buffer.append({
                "text": frame.text,
                "timestamp": time.time(),
                "is_final": True,
            })
            # Trim to last 60 seconds
            cutoff = time.time() - 60.0
            self._transcript_buffer = [e for e in self._transcript_buffer if e["timestamp"] > cutoff]

        elif isinstance(frame, InterimTranscriptionFrame):
            self._user_speaking = True
            if self._speaking_reset_task:
                self._speaking_reset_task.cancel()
            self._speaking_reset_task = self.create_task(self._reset_speaking_flag(), "speaking_reset")

        elif isinstance(frame, (BotStartedSpeakingFrame, LLMFullResponseEndFrame)):
            self._last_bot_speech_time = time.time()

        await self.push_frame(frame, direction)

    async def _reset_speaking_flag(self):
        try:
            await asyncio.sleep(2.0)
            self._user_speaking = False
        except asyncio.CancelledError:
            pass

    async def _monitor_loop(self):
        logger.info("ProactiveMonitor: monitor loop started")
        while self._task_active:
            await asyncio.sleep(self._check_interval)
            if not self._task_active:
                break
            try:
                await self._check_triggers()
            except Exception as e:
                logger.error(f"ProactiveMonitor error: {e}")
        logger.info("ProactiveMonitor: monitor loop ended")

    async def _check_triggers(self):
        now = time.time()
        trigger_type = None
        context_snippet = ""

        # Trigger 1: silence
        if self._transcript_buffer:
            last_time = self._transcript_buffer[-1]["timestamp"]
            if now - last_time > self._silence_threshold:
                trigger_type = "silence"
                context_snippet = self._transcript_buffer[-1]["text"]
        elif self._task_start_time and now - self._task_start_time > self._silence_threshold:
            trigger_type = "silence"
            context_snippet = ""

        # Trigger 2: weighted hesitation (overrides silence)
        window_cutoff = now - self._hesitation_window
        recent = [e for e in self._transcript_buffer if e["timestamp"] > window_cutoff]
        if recent:
            tokens = " ".join(e["text"] for e in recent).lower().split()
            score = sum(HESITATION_WEIGHTS.get(t, 0) for t in tokens)
            if score >= self._hesitation_threshold:
                trigger_type = "hesitation"
                context_snippet = " ".join(e["text"] for e in recent)

        # Trigger 3: confusion patterns (highest priority)
        # Only check transcripts newer than last check to avoid re-firing on stale text
        check_cutoff = max(self._last_bot_speech_time, self._last_checked_transcript_time)
        since_last_check = [e for e in self._transcript_buffer if e["timestamp"] > check_cutoff]
        if since_last_check:
            combined = " ".join(e["text"] for e in since_last_check).lower()
            for pattern in CONFUSION_PATTERNS:
                if pattern in combined:
                    trigger_type = "confusion"
                    context_snippet = combined[:200]
                    break

        if trigger_type:
            now2 = time.time()
            suppressed = (
                now2 - self._last_bot_speech_time < self._post_bot_buffer
                or now2 - self._last_intervention_time < self._cooldown
                or self._user_speaking
            )
            if suppressed:
                reasons = []
                if now2 - self._last_bot_speech_time < self._post_bot_buffer:
                    reasons.append("post_bot_buffer")
                if now2 - self._last_intervention_time < self._cooldown:
                    reasons.append("cooldown")
                if self._user_speaking:
                    reasons.append("user_speaking")
                self._log_event("suppressed", trigger_type, False, {
                    "context_snippet": context_snippet,
                    "suppression_reason": ",".join(reasons),
                })
                self._last_checked_transcript_time = time.time()
                return

            self._last_checked_transcript_time = time.time()
            await self._fire_intervention(trigger_type, context_snippet)

    async def _fire_intervention(self, trigger_type: str, context_snippet: str):
        self._last_intervention_time = time.time()

        # Strip previous probe-response pairs to prevent context explosion.
        # Walk linearly so we can drop the assistant message that immediately
        # follows each proactive system message (the LLM's reply to the probe).
        filtered = []
        skip_next_assistant = False
        for m in self._context.messages:
            is_probe = m.get("role") == "system" and "[PROACTIVE DETECTION" in m.get("content", "")
            if is_probe:
                skip_next_assistant = True
                continue  # drop probe system message
            if skip_next_assistant and m.get("role") == "assistant":
                skip_next_assistant = False
                continue  # drop orphaned assistant response to that probe
            skip_next_assistant = False
            filtered.append(m)

        system_msg = {
            "role": "system",
            "content": (
                f"[PROACTIVE DETECTION - {trigger_type.upper()}]: "
                f"The user has not directly addressed you, but the proactive monitor "
                f"has detected signs they may need help. "
                f'Recent context: "{context_snippet}"\n\n'
                f"You have three options:\n"
                f"1. Offer a gentle Notification (e.g. 'That\\'s a tricky one. Want a hint?')\n"
                f"2. Offer a Suggestion if the user has been struggling for a while\n"
                f"3. Return exactly {{\"action\": \"silence\"}} if this seems like a false positive\n\n"
                f"Default to Notification (option 1). Never give the answer directly."
            ),
        }
        filtered.append(system_msg)

        task = self._task_ref.get("task")
        if task:
            # LLMMessagesUpdateFrame is the official compaction pattern: it
            # replaces the LLM service's context in-place before triggering.
            await task.queue_frames([
                LLMMessagesUpdateFrame(messages=filtered, run_llm=False),
                LLMRunFrame(),
            ])

        logger.info(f"ProactiveMonitor: fired {trigger_type} trigger, context: {context_snippet[:80]}")
        self._log_event("intervention_fired", trigger_type, True, {"context_snippet": context_snippet})

    def _log_event(self, event_type: str, trigger_type: str, fired: bool, details: dict):
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "trigger_type": trigger_type,
            "fired": fired,
            "hesitation_score": details.get("hesitation_score", 0),
            "context_snippet": details.get("context_snippet", ""),
            "suppression_reason": details.get("suppression_reason", None),
        }
        log_path = Path("logs/proactive_interventions.jsonl")
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "a") as f:
            f.write(json.dumps(event) + "\n")
