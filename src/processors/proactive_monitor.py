import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from pipecat.frames.frames import (
    Frame, StartFrame, EndFrame, CancelFrame,
    TranscriptionFrame, InterimTranscriptionFrame,
    LLMRunFrame, LLMFullResponseEndFrame, BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
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
        task_context: str = "",
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
        self._task_context = task_context

        self._transcript_buffer: list[dict] = []
        self._last_bot_speech_time: float = 0.0
        self._last_intervention_time: float = 0.0
        self._task_start_time: float = 0.0
        self._last_checked_transcript_time: float = 0.0
        self._task_active: bool = False
        self._user_speaking_until: float = 0.0
        self._tars_speaking: bool = False
        self._tars_speaking_since: float = 0.0
        self._consecutive_unanswered: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame):
            self._task_active = True
            now = time.time()
            self._task_start_time = now
            self._last_bot_speech_time = now  # prevent false trigger before greeting fires
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
            self._consecutive_unanswered = 0

        elif isinstance(frame, InterimTranscriptionFrame):
            self._user_speaking_until = time.time() + 2.0

        elif isinstance(frame, BotStartedSpeakingFrame):
            self._tars_speaking = True
            self._tars_speaking_since = time.time()
            self._last_bot_speech_time = time.time()
            logger.debug("ProactiveMonitor: BotStartedSpeakingFrame received")

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._tars_speaking = False
            self._last_bot_speech_time = time.time()
            logger.debug("ProactiveMonitor: BotStoppedSpeakingFrame received")

        elif isinstance(frame, LLMFullResponseEndFrame):
            self._last_bot_speech_time = time.time()

        await self.push_frame(frame, direction)

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
        # Silence = neither user nor TARS has been active for silence_threshold.
        # Use max(last_user_transcript, last_bot_speech) so TARS speaking resets
        # the clock the same way user speech does.
        if self._transcript_buffer:
            last_user_time = self._transcript_buffer[-1]["timestamp"]
            last_active = max(last_user_time, self._last_bot_speech_time)
            if now - last_active > self._silence_threshold:
                trigger_type = "silence"
                context_snippet = self._transcript_buffer[-1]["text"]

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
            # Safety: clear stuck flag if BotStoppedSpeakingFrame was never received.
            # 60s is longer than any realistic TTS output.
            if self._tars_speaking and now2 - self._tars_speaking_since > 60.0:
                logger.warning("ProactiveMonitor: BotStoppedSpeakingFrame never received, clearing stuck flag")
                self._tars_speaking = False

            suppressed = (
                self._tars_speaking
                or now2 - self._last_bot_speech_time < self._post_bot_buffer
                or now2 - self._last_intervention_time < self._cooldown
                or now2 < self._user_speaking_until
                or self._consecutive_unanswered >= 2
            )
            if suppressed:
                reasons = []
                if self._tars_speaking:
                    reasons.append("tars_speaking")
                if now2 - self._last_bot_speech_time < self._post_bot_buffer:
                    reasons.append("post_bot_buffer")
                if now2 - self._last_intervention_time < self._cooldown:
                    reasons.append("cooldown")
                if now2 < self._user_speaking_until:
                    reasons.append("user_speaking")
                if self._consecutive_unanswered >= 2:
                    reasons.append("max_unanswered")
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
        self._consecutive_unanswered += 1
        probe_num = self._consecutive_unanswered

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

        probe_note = (
            f"\n\nThis is unanswered probe #{probe_num}. Previous probes got no user response. "
            f"If this is probe #2 or higher, return {{\"action\": \"silence\"}} — the user is likely away or ignoring you."
            if probe_num >= 2
            else ""
        )

        if self._task_context:
            # In task mode: only fire if the user is truly stuck, default to silence
            system_msg = {
                "role": "system",
                "content": (
                    f"[PROACTIVE DETECTION - {trigger_type.upper()}]: "
                    f"The user is in task mode ({self._task_context}) and has been silent. "
                    f'Recent context: "{context_snippet}"\n\n'
                    f"Task mode rule: default to {{\"action\": \"silence\"}}. "
                    f"Only speak if the recent context contains a direct, unresolved question the user cannot answer. "
                    f"Thinking aloud, fragments, and partial progress are NOT requests for help. "
                    f"If in any doubt, return exactly {{\"action\": \"silence\"}}."
                    f"{probe_note}"
                ),
            }
        else:
            system_msg = {
                "role": "system",
                "content": (
                    f"[PROACTIVE DETECTION - {trigger_type.upper()}]: "
                    f"The user has not directly addressed you, but the proactive monitor "
                    f"has detected signs they may need help.\n"
                    f'Recent context: "{context_snippet}"\n\n'
                    f"Read the recent context and infer what kind of help is relevant. "
                    f"You have three options:\n"
                    f"1. Offer brief, relevant help based on what the user said (1-2 sentences max)\n"
                    f"2. If this seems like a false positive, return exactly {{\"action\": \"silence\"}}\n"
                    f"3. If the user appears away or unresponsive, return exactly {{\"action\": \"silence\"}}\n\n"
                    f"Default to option 1. Keep it to 1-2 sentences. "
                    f"Never give a direct answer, list steps, or use phrases like 'want a hint' or 'tricky one'."
                    f"{probe_note}"
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

    def set_task_mode(self, mode: str | None):
        """Adjust monitor behavior for task mode. None = exit task mode."""
        if mode is None:
            self._task_context = ""
            self._silence_threshold = 8.0
            self._cooldown = 30.0
            self._consecutive_unanswered = 0
            logger.info("ProactiveMonitor: task mode OFF")
        else:
            self._task_context = mode
            self._silence_threshold = 15.0  # longer silence expected during tasks
            self._cooldown = 60.0           # less frequent interventions
            self._consecutive_unanswered = 0
            logger.info(f"ProactiveMonitor: task mode ON ({mode})")

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
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = log_dir / f"proactive_interventions_{today}.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(event) + "\n")
        # Delete files older than 7 days
        cutoff = datetime.now() - timedelta(days=7)
        for old in log_dir.glob("proactive_interventions_*.jsonl"):
            try:
                file_date = datetime.strptime(old.stem.split("_", 2)[2], "%Y-%m-%d")
                if file_date < cutoff:
                    old.unlink()
            except (ValueError, IndexError):
                pass
