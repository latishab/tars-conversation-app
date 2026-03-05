import asyncio
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger
from pipecat.frames.frames import (
    Frame, StartFrame, EndFrame, CancelFrame,
    TranscriptionFrame, InterimTranscriptionFrame,
    LLMRunFrame, BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
    LLMMessagesUpdateFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


HESITATION_WEIGHTS = {"um": 2, "uh": 1, "hmm": 1, "er": 1, "ah": 1}

CONFUSION_PATTERNS = [
    "i don't know", "no idea", "i'm stuck", "this is hard",
    "i can't figure", "i can't remember", "help me", "i need help",
    "what does this mean", "i'm confused", "i have no idea", "i'm not sure",
    "how do i", "i'm having trouble", "i'm having a problem",
    "i don't understand", "i don't get it",
]

# If ANY of these appear in the same utterance window as a confusion pattern,
# the user is self-resolving — do not fire a proactive intervention.
# Fast-path phrases: if these appear in the same confusion window, skip immediately
# without waiting for the timing check. Keep short — timing is the primary filter.
SELF_RESOLUTION_PHRASES = [
    "move on", "moving on", "never mind", "nevermind",
]

# How long the user must keep talking after a confusion pattern before we
# assume they self-resolved. Genuine confusion → brief pause → silence.
# Self-resolution → user keeps narrating for several seconds about a new topic.
_CONFUSION_SELF_RESOLVE_SECS = 4.0


class ProactiveMonitor(FrameProcessor):
    def __init__(
        self,
        context,
        task_ref: dict,
        silence_threshold: float = 8.0,
        hesitation_threshold: int = 3,
        hesitation_window: float = 10.0,
        cooldown: float = 30.0,
        post_bot_buffer: float = 5.0,
        check_interval: float = 1.0,
        enabled: bool = True,
        task_context: str = "",
        session_id: str = "",
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
        self._session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        self._proactive_response_pending = False
        self._task_mode_just_activated = False
        self._transcript_buffer: list[dict] = []
        self._last_bot_speech_time: float = 0.0
        self._last_intervention_time: float = 0.0
        self._last_confusion_intervention_time: float = 0.0
        self._last_hesitation_intervention_time: float = 0.0
        self._confusion_cooldown: float = 30.0
        self._hesitation_cooldown: float = 30.0
        self._task_start_time: float = 0.0
        self._last_checked_transcript_time: float = 0.0
        self._task_active: bool = False
        self._user_speaking_until: float = 0.0
        self._tars_speaking: bool = False
        self._tars_speaking_since: float = 0.0
        self._consecutive_unanswered: int = 0
        self._pending_confusion: str | None = None  # detected during speech, fire after pause
        self._pending_confusion_detected_at: float = 0.0

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
            self._pending_confusion = None  # reactive pipeline handled it
            logger.debug("ProactiveMonitor: BotStartedSpeakingFrame received")

        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._tars_speaking = False
            self._last_bot_speech_time = time.time()
            logger.debug("ProactiveMonitor: BotStoppedSpeakingFrame received")

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
        # Proactive monitoring only runs during an active task. Without task context
        # the triggers produce too many false positives in general conversation.
        if not self._task_context:
            return

        now = time.time()
        trigger_type = None
        context_snippet = ""
        hesitation_score = 0

        # Trigger 1: silence
        # Silence = neither user nor TARS has been active for silence_threshold.
        # Use max(last_user_transcript, last_bot_speech) so TARS speaking resets
        # the clock the same way user speech does.
        if self._transcript_buffer:
            last_user_time = self._transcript_buffer[-1]["timestamp"]
            last_active = max(last_user_time, self._last_bot_speech_time)
            if now - last_active > self._silence_threshold:
                trigger_type = "silence"
                # Include last 5 entries so LLM sees the clue, not just the final filler
                context_snippet = " ".join(
                    e["text"] for e in self._transcript_buffer[-5:]
                ).strip()

        # Trigger 2: weighted hesitation (overrides silence)
        window_cutoff = now - self._hesitation_window
        recent = [e for e in self._transcript_buffer if e["timestamp"] > window_cutoff]
        if recent:
            tokens = re.findall(r"[a-z']+", " ".join(e["text"] for e in recent).lower())
            score = sum(HESITATION_WEIGHTS.get(t, 0) for t in tokens)
            if score > 0:
                logger.debug(
                    f"ProactiveMonitor: hesitation score={score}/{self._hesitation_threshold} "
                    f"window={len(recent)} entries, tokens={tokens}"
                )
                if score < self._hesitation_threshold:
                    self._log_event("hesitation_below_threshold", "hesitation", False, {
                        "hesitation_score": score,
                        "context_snippet": " ".join(e["text"] for e in recent[-3:]),
                    })
            if score >= self._hesitation_threshold:
                trigger_type = "hesitation"
                # Include pre-hesitation context so LLM knows what clue the user was on
                pre_window = [e for e in self._transcript_buffer if e["timestamp"] <= window_cutoff]
                pre_text = " ".join(e["text"] for e in pre_window[-5:]).strip()
                recent_text = " ".join(e["text"] for e in recent)
                context_snippet = (pre_text + " " + recent_text).strip() if pre_text else recent_text
                hesitation_score = score
                logger.debug(f"ProactiveMonitor: hesitation threshold reached score={score}")

        # Trigger 3: confusion patterns (highest priority)
        # Scan only transcripts newer than last check. Advance the cursor immediately on
        # detection — before suppression — so the same text is never re-scanned next tick.
        # Store as _pending_confusion and fire once the user stops speaking.
        # Cap confusion scan window to 30s so context snippet stays recent and focused
        check_cutoff = max(self._last_bot_speech_time, self._last_checked_transcript_time, now - 30.0)
        since_last_check = [e for e in self._transcript_buffer if e["timestamp"] > check_cutoff]
        if since_last_check:
            combined = " ".join(e["text"] for e in since_last_check).lower()
            logger.debug(f"ProactiveMonitor: confusion check on: {combined[:100]}")
            for pattern in CONFUSION_PATTERNS:
                if pattern in combined:
                    self._last_checked_transcript_time = time.time()  # advance before suppression
                    # Fast-path: explicit self-resolution phrase in the same window
                    if any(p in combined for p in SELF_RESOLUTION_PHRASES):
                        logger.info(
                            f"ProactiveMonitor: confusion '{pattern}' discarded "
                            f"— self-resolution phrase in window"
                        )
                        self._log_event("confusion_discarded", "confusion", False, {
                            "context_snippet": combined[:120],
                            "suppression_reason": "self_resolution_phrase",
                        })
                        break
                    self._pending_confusion = combined[:200]
                    self._pending_confusion_detected_at = time.time()
                    logger.info(f"ProactiveMonitor: confusion pattern detected: '{pattern}'")
                    break

        # Fire pending confusion once user has stopped speaking
        if self._pending_confusion is not None and now >= self._user_speaking_until:
            # Timing check: if user kept talking for >_CONFUSION_SELF_RESOLVE_SECS after
            # detection, they likely moved on without needing help — discard.
            last_speech = self._transcript_buffer[-1]["timestamp"] if self._transcript_buffer else 0.0
            continued_talking = last_speech > self._pending_confusion_detected_at + _CONFUSION_SELF_RESOLVE_SECS
            if continued_talking:
                logger.info(
                    f"ProactiveMonitor: confusion discarded — user continued talking "
                    f"{last_speech - self._pending_confusion_detected_at:.1f}s after detection "
                    f"(threshold {_CONFUSION_SELF_RESOLVE_SECS}s)"
                )
                self._log_event("confusion_discarded", "confusion", False, {
                    "context_snippet": self._pending_confusion[:120] if self._pending_confusion else "",
                    "suppression_reason": "user_continued_talking",
                })
                self._pending_confusion = None
            else:
                trigger_type = "confusion"
                context_snippet = self._pending_confusion
                self._pending_confusion = None

        if trigger_type:
            now2 = time.time()
            # Safety: clear stuck flag if BotStoppedSpeakingFrame was never received.
            # 60s is longer than any realistic TTS output.
            if self._tars_speaking and now2 - self._tars_speaking_since > 60.0:
                logger.warning("ProactiveMonitor: BotStoppedSpeakingFrame never received, clearing stuck flag")
                self._tars_speaking = False

            # Confusion and hesitation each have their own cooldown so they aren't
            # blocked by silence fires (or each other).
            if trigger_type == "confusion":
                within_cooldown = now2 - self._last_confusion_intervention_time < self._confusion_cooldown
            elif trigger_type == "hesitation":
                within_cooldown = now2 - self._last_hesitation_intervention_time < self._hesitation_cooldown
            else:
                within_cooldown = now2 - self._last_intervention_time < self._cooldown
            # Silence trigger: if last_active guard already passed (>silence_threshold ago),
            # the user is definitively not speaking — interim VAD frames must not block it.
            speaking_check = trigger_type != "silence" and now2 < self._user_speaking_until
            suppressed = (
                self._tars_speaking
                or now2 - self._last_bot_speech_time < self._post_bot_buffer
                or within_cooldown
                or speaking_check
                or self._consecutive_unanswered >= 2
            )
            if suppressed:
                reasons = []
                if self._tars_speaking:
                    reasons.append("tars_speaking")
                if now2 - self._last_bot_speech_time < self._post_bot_buffer:
                    reasons.append("post_bot_buffer")
                if within_cooldown:
                    reasons.append("cooldown")
                if speaking_check:
                    reasons.append("user_speaking")
                if self._consecutive_unanswered >= 2:
                    reasons.append("max_unanswered")
                self._log_event("suppressed", trigger_type, False, {
                    "context_snippet": context_snippet,
                    "suppression_reason": ",".join(reasons),
                })
                return

            await self._fire_intervention(trigger_type, context_snippet, hesitation_score)

    async def _fire_intervention(self, trigger_type: str, context_snippet: str, hesitation_score: int = 0):
        now = time.time()
        self._last_intervention_time = now
        if trigger_type == "confusion":
            self._last_confusion_intervention_time = now
        elif trigger_type == "hesitation":
            self._last_hesitation_intervention_time = now
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

        express_reminder = (
            "\nEnd your response with [express(emotion, intensity)]. "
            "emotion: neutral/happy/sad/angry/excited/afraid/sleepy/curious/skeptical/smug/surprised. "
            "intensity: low/medium/high. Exact words only."
        )

        if self._task_context:
            no_context_escape = (
                '\nIf there is no identifiable topic in context or history: {"action": "silence"}'
            )
            post_intervention_note = (
                "\nAfter your check-in, if the user continues to think aloud or narrate to "
                "themselves (clue narration, fillers, self-answers), return to silence. "
                "Only engage if they directly address you."
            )
            if trigger_type == "silence":
                system_content = (
                    f"[PROACTIVE DETECTION: extended silence]\n"
                    f"The user has been silent for 15+ seconds while working on a {self._task_context}.\n"
                    f'Recent context: "{context_snippet}"\n\n'
                    f"Identify the specific clue or topic they were last working on from the context above, "
                    f"then offer a one-sentence check-in that references it.\n"
                    f"Good: \"That 'impatiently longing' clue is a tough one — want a nudge?\"\n"
                    f"Bad: \"Let me know if you need help.\" / \"Need anything?\"\n"
                    f"Do not give the answer or name the answer word. "
                    f"The user already read the clue aloud — do NOT restate, rephrase, or paraphrase it. Give a hint from a different angle: a related word, a category, a letter hint, or wordplay nudge. "
                    f"Do not prefix with \"Notification:\". Just respond naturally."
                    f"{post_intervention_note}"
                    f"{no_context_escape}"
                    f"{express_reminder}"
                    f"{probe_note}"
                )
            elif trigger_type == "hesitation":
                system_content = (
                    f"[PROACTIVE DETECTION: hesitation cluster]\n"
                    f"The user is hesitating heavily (multiple \"um\", \"uh\" in quick succession) "
                    f"while working on a {self._task_context}.\n"
                    f'Recent context: "{context_snippet}"\n\n'
                    f"They appear to be struggling. Offer a gentle nudge about whatever they were last "
                    f"working on. Look back through conversation history for the most recent clue. "
                    f"One sentence.\n"
                    f"Do not name specific words or titles that could be the answer — "
                    f"not even as examples. Use category or category description only. "
                    f"The user already read the clue aloud — do NOT restate, rephrase, or paraphrase it. Give a hint from a different angle: a related word, a category, a letter hint, or wordplay nudge. "
                    f"Just respond naturally."
                    f"{post_intervention_note}"
                    f"{no_context_escape}"
                    f"{express_reminder}"
                    f"{probe_note}"
                )
            else:  # confusion
                system_content = (
                    f"[PROACTIVE DETECTION: user expressed difficulty]\n"
                    f"The user said something indicating they're stuck or confused while working on "
                    f"a {self._task_context}.\n"
                    f'Recent context: "{context_snippet}"\n\n'
                    f"Offer a helpful nudge related to what they're working on. Look back through "
                    f"conversation history for the most recent clue. One sentence, Suggestion-level "
                    f"is appropriate here.\n"
                    f"Do not give the answer or name the answer word. "
                    f"The user already read the clue aloud — do NOT restate, rephrase, or paraphrase it. Give a hint from a different angle: a related word, a category, a letter hint, or wordplay nudge. "
                    f"Just respond naturally."
                    f"{post_intervention_note}"
                    f"{no_context_escape}"
                    f"{express_reminder}"
                    f"{probe_note}"
                )
            system_msg = {"role": "system", "content": system_content}
        else:
            system_msg = {
                "role": "system",
                "content": (
                    f"[PROACTIVE DETECTION - {trigger_type.upper()}]: "
                    f"The user has not addressed you. The monitor detected they may need help.\n"
                    f'Recent context: "{context_snippet}"\n\n'
                    f"This is a proactive intervention. Apply this hierarchy:\n"
                    f"  Notification — signal you're available. Brief, non-intrusive. Preferred.\n"
                    f"  Suggestion — a nudge or hint, not the answer.\n"
                    f"  Never give the answer directly. If the user wants it, they will ask — "
                    f"that becomes a reactive request and is handled normally.\n"
                    f"Do not prefix your response with 'Notification:', 'Suggestion:', or 'Hint:'. Just respond naturally.\n"
                    f"If context is ambiguous or this is a false positive: {{\"action\": \"silence\"}}.\n"
                    f"1-2 sentences maximum."
                    f"{express_reminder}"
                    f"{probe_note}"
                ),
            }
        filtered.append(system_msg)

        task = self._task_ref.get("task")
        if task:
            self._proactive_response_pending = True
            # LLMMessagesUpdateFrame is the official compaction pattern: it
            # replaces the LLM service's context in-place before triggering.
            await task.queue_frames([
                LLMMessagesUpdateFrame(messages=filtered, run_llm=False),
                LLMRunFrame(),
            ])

        logger.info(f"ProactiveMonitor: fired {trigger_type} trigger, context: {context_snippet[:80]}")
        self._log_event("intervention_fired", trigger_type, True, {
            "context_snippet": context_snippet,
            "hesitation_score": hesitation_score,
        })

    def set_task_mode(self, mode: str | None):
        """Adjust monitor behavior for task mode. None = exit task mode."""
        if mode is None:
            self._task_context = ""
            self._silence_threshold = 8.0
            self._cooldown = 30.0
            self._confusion_cooldown = 30.0
            self._consecutive_unanswered = 0
            logger.info("ProactiveMonitor: task mode OFF")
        else:
            self._task_context = mode
            self._task_mode_just_activated = True
            self._silence_threshold = 15.0  # longer silence expected during tasks
            self._cooldown = 60.0           # less frequent interventions
            self._confusion_cooldown = 30.0  # confusion can fire every 30s regardless
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
        log_path = log_dir / f"proactive_interventions_{self._session_id}.jsonl"
        with open(log_path, "a") as f:
            f.write(json.dumps(event) + "\n")
        # Delete files older than 7 days
        cutoff = datetime.now() - timedelta(days=7)
        for old in log_dir.glob("proactive_interventions_*.jsonl"):
            try:
                # Parse date from session_id prefix (YYYYMMDD_...) or legacy YYYY-MM-DD suffix
                stem_parts = old.stem.split("_")
                date_str = stem_parts[2] if len(stem_parts) >= 3 else ""
                if len(date_str) == 8:
                    file_date = datetime.strptime(date_str, "%Y%m%d")
                else:
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                if file_date < cutoff:
                    old.unlink()
            except (ValueError, IndexError):
                pass
