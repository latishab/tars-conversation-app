# Proactive Monitor Testing Checklist

Updated: March 4, 2026. Fourteen live test runs completed (browser mode).
Fixes 1-21 applied + ReactiveGate (Fix 22). Reactive silence compliance now code-enforced.
Next: hesitation trigger live verification with LLM nudge quality.

Pipeline: Soniox JP + Cerebras GPT-OSS-120B + ElevenLabs Flash v2.5

---

## TODO: What still needs testing

### Phase 7: Integrated dry run (crossword app + TARS)

ReactiveGate (Fix 22) applied. Crossword webapp already running.

**Setup**
- [ ] TARS running (`python tars_bot.py --browser-audio --gradio`)
- [ ] Crossword app open in browser
- [ ] Two terminal windows open: one tailing `logs/proactive_interventions_YYYY-MM-DD.jsonl`, one watching bot stdout

---

**Step 1 — Baseline silence compliance (ReactiveGate / Fix 22)**
Read crossword clues aloud with full narration. Do not ask TARS anything. Expect silence for all of these:
- [x] Read a clue and letter count aloud: "7 across, ice cream holder, four letters" — suppressed (Run 13/14)
- [x] Clue + letter count with fillers: "opposite of day, five letters, um" — suppressed (Run 13/14)
- [x] State a wrong guess: "I think it's cone, yeah cone" — suppressed (Run 14)
- [x] Express uncertainty: "Not so sure about this one" — suppressed (Run 14)
- [x] Move on: "Okay, next clue", "I'm gonna keep thinking" — suppressed (Run 14)
- [x] Say "I don't know" then immediately continue: "I don't know... wait, maybe it's bin" — suppressed (Run 14)
- [ ] Spell a word aloud: "T-H-R-O-W" or "it starts with C"
- Log check: ReactiveGate logs `suppressed reactive response — window: ...`. **Zero spoken responses = pass.**

**Step 2 — "Hold on / I'm still thinking" treated as CONDITION C (ReactiveGate)**
After TARS would respond, push back without using correction phrases:
- [x] "I'm still thinking, hold on" passes through ReactiveGate (CONDITION C phrase in window) → LLM returns "Got it." (Run 13/14)
- [x] "let me think" passes through → "Got it." (Run 14)
- Log check: ReactiveGate passes, LLM returns correction response. **Got it. = pass.**

**Step 3 — Correction stays in task mode (Fix 14)**
After TARS speaks unprompted, correct it:
- [x] "Stop helping" / "You shouldn't answer" passes through ReactiveGate (CONDITION C) → LLM responds "Got it." (Run 14)
- [ ] Continue crossword normally for 2+ more clues
- Log check: after correction, `task_mode` must remain `crossword` in the log (no `task mode OFF` line). All subsequent clue narration = ReactiveGate suppression. **task_mode stays ON = pass.**

**Step 4 — Silence trigger fires (Phase 2: Trigger 1 / Fix 13)**
Go completely silent mid-crossword:
- [x] Say a clue aloud, then stop talking entirely for 20+ seconds — verified Run 12: fired at 19:40:02 with richer context (5 entries), TARS said "Take your time—let me know if you need any help."
- Log check: expect `fired silence trigger` in log within 20s of last speech. **Fires = pass.**

**Step 5 — Hesitation trigger fires (Phase 2: Trigger 2)**
Do a deliberate hesitation cluster then stop:
- [ ] Say ONLY fillers in a burst: "Um... uh... um... hmm... uh..." (aim for 5+ fillers in 5 seconds)
- [ ] Then go completely silent for 3+ seconds
- Log check: expect `hesitation threshold reached score=N` (N >= 4), then `fired hesitation trigger` within 3 seconds of stopping. **Fires = pass.**
- Note: ReactiveGate suppresses reactive responses, so hesitation trigger no longer races against reactive path resetting cooldown.

**Step 6 — Confusion trigger fires as proactive (Phase 2: Trigger 3 / Fix 15)**
The confusion proactive trigger only fires when the reactive pipeline returns silence AND the user stays quiet.
This requires: confusion phrase in an utterance where TARS decides silence (task mode, think-aloud), followed by a pause.

Scenario A — embedded confusion, reactive returns silence:
- [x] Verified Run 12: "I'm stuck" → confusion detected at 19:35:00, fired at 19:35:02, TARS gave contextually correct nudge "Think of a short word that describes a fortunate outcome that happens by chance."
- [x] Verified Run 12: "I don't know" → confusion detected at 19:38:00, fired at 19:38:02 with clue context in snippet.

Scenario B — confusion phrase alone with no full sentence context:
- [ ] Say just: "hmm, I don't know" or "I'm stuck" — do not continue speaking
- [ ] Stay quiet for 3+ seconds
- Log check: reactive pipeline may or may not respond. If it responds (bot speaks), confusion was handled reactively — that is correct behavior. If reactive returns silence (SilenceFilter), `fired confusion trigger` should appear. **Reactive-silence → proactive fires = pass.**

**Step 7 — Confusion does not spam (Fix 15)**
- [x] Run 9 verified: `confusion pattern detected` logged once per utterance, not every tick. Cursor advances at detection time.
- [x] Run 12 verified: confusion detected once per "I'm stuck", once per "I don't know". No spam.

**Step 8 — Suppression works (Phase 3)**
- [x] Verified Run 12: TARS did not interrupt during active speech
- [ ] Check that TARS does not fire twice within 60 seconds (task mode cooldown)
- [x] Verified Run 11/12: consecutive_unanswered limit working (probe_note fires correctly)

**Step 9 — Proactive response quality (Phase 4)**
For each proactive intervention that fires:
- [x] Response is 1-2 sentences — verified Run 12
- [x] Response is a nudge/notification, not the direct answer — verified Run 12 (all three trigger types tested in LLM compliance suite, 22/22 pass)
- [x] Response is contextually relevant — verified Run 12: confusion trigger used clue context from snippet
- [x] No "[PROACTIVE DETECTION]" prefix in TTS output — verified (system message is stripped)

**Step 9 — Count interventions**
- [ ] Total proactive interventions in session: target 3-6 per 10 minutes. Log check against `proactive_interventions_YYYY-MM-DD.jsonl`.

**Step 10 — CONDITION A override (Fix 17):** Mid-crossword, say "just give me the answer" after struggling with a clue.
- [x] Verified Run 12: "give me the answer" → TARS gave direct answer immediately
- Log check: no `{"action": "silence"}` on this turn. **Direct answer = pass.**

**Step 11 — Short fragment protection (Fix 20):** Mid-crossword, say "I, um." or "Uh." then stay silent for 5+ seconds.
- [ ] Task mode must NOT drop. TARS must not exit task mode from a 2-word filler fragment.
- Log check: no `task mode OFF` line after the utterance. **task_mode stays ON = pass.**

**Step 12 — Hesitation gives useful nudge (Fix 18):** Narrate a clue aloud, then do a filler burst ("um, um, um") and pause.
- [ ] TARS should offer a nudge referencing the clue you just narrated — not generic silence
- Log check: `fired hesitation trigger` with context_snippet containing clue text (not just fillers). **Contextual nudge = pass.**
- Note: ReactiveGate now suppresses reactive answers, so hesitation trigger should fire unobstructed. First clean test pending (was blocked by reactive leaks in Runs 10-12).

### Phase 8: Robot mode (tars_bot.py)

Only after Phase 7 passes in browser mode.

- [ ] Uncomment ProactiveMonitor in tars_bot.py, wire into pipeline
- [ ] Populate task_ref after PipelineTask creation
- [ ] Verify monitor starts through RPi audio path
- [ ] Test expression-speech sync with proactive responses
- [ ] Test gesture blocking (create_task vs await on fire_expression)

### Prompt tuning (open issues)

- [x] **Issue A:** Proactive injection prompt hard-codes "hint" and "tricky one." Replaced with generic "canned helper phrases".
- [x] **Issue B:** TARS persona too heavy on space roleplay. Trimmed TARS.json dead fields; added space jargon prohibition to tone section.
- [x] **Issue C:** Proactive response length — "1-2 sentences maximum" already in build_proactive_section(). Confirmed.
- [x] **Notification-first reinforcement:** Added "offer a brief nudge or observation only — never give the answer directly" to task mode proactive prompt.

---

## DONE: Verified in live testing

### Phase 0: Pre-flight

All resolved. Soniox filler transcription confirmed. Imports, logs, system prompt, task_ref all passing.

### Fixes 1-13: All applied

| Fix | Description | Status |
|-----|-------------|--------|
| 1 | Context cleanup (LLMMessagesUpdateFrame) | Applied, 37/37 tests |
| 2 | SilenceFilter buffer-then-flush | Confirmed Runs 4-6 |
| 3 | Browser AEC | Confirmed all runs |
| 4 | TTS debounce (500ms) | Applied |
| 5 | Startup race (_last_bot_speech_time init) | Applied |
| 6 | Bot speech tracking (three-layer suppression) | Applied |
| 7 | Consecutive unanswered probes limit (max 2) | Applied |
| 8 | Require user transcript for silence triggers | Applied |
| 9 | Pass unanswered count in system message | Applied |
| 10 | set_task_mode tool call | Applied, live tested Run 6 |
| 11 | Concrete think-aloud examples in task mode prompt | Applied, needs live verification |
| 12 | Separate confusion trigger cooldown | Applied, needs live verification |
| 13 | Exempt silence trigger from _user_speaking_until | Applied, needs live verification |
| 14 | CONDITION C must not call set_task_mode('off') — correction ≠ task-end | Applied, needs live verification |
| 15 | Confusion trigger: advance cursor on detection (not on fire), store pending, fire after speech ends | Applied, needs live verification |
| 16 | set_task_mode('off') fires on clue resolution ('Okay, evening.') — tightened tool description to require explicit task-end phrasing | Verified Run 9: task mode stayed on entire session |
| 17 | CONDITION A broken: hint restriction over-generalized, LLM refused "just give me the answer". Made CONDITION A an explicit override; narrowed hint rule to allow first letter/partial hints | Applied, needs live verification |
| 18 | Hesitation trigger context too minimal ("Um. Um.") — LLM returned silence because no clue context. Added pre-hesitation buffer (last 5 transcripts before hesitation window) to context_snippet | Applied, needs live verification |
| 19 | Confusion context too stale — first detection accumulated all text since greeting (session start). Added 30s cap to check_cutoff | Applied, needs live verification |
| 20 | set_task_mode('off') from "I, um." (2-word fragment) — still firing despite Fix 14/16. Added explicit rule: never call 'off' if utterance is ≤4 words or filler-only. Added to both tool schema and tools section doc | Applied, needs live verification |
| 21 | Reactive pipeline answering think-aloud: clue+letter-count without question words still triggered hints ("opposite of day, five letters, um"). "I'm still thinking, Tars, hold on" got a hint instead of Got it. Added CRITICAL note to CONDITION B, added hold-on/I'm-still-thinking to CONDITION C, expanded silence list with Run 12 failure patterns | Applied, 22/22 LLM compliance tests pass |
| 22 | Reactive silence moved from LLM-trust to deterministic gate. ReactiveGate FrameProcessor: buffers LLM response frames, suppresses on EndFrame unless user explicitly addressed TARS (direct name, CONDITION A/C phrases, directed question) within 15s window. Added `_proactive_response_pending`, `_task_mode_just_activated` flags to ProactiveMonitor. Added 2-layer confusion false-positive filter (fast-path phrases + 4s timing check). Restructured compliance tests: removed all 12 LLM-silence tests (now gate's job), kept 11 gate pass-through behavior tests. | Verified Run 13/14: think-aloud suppressed throughout, proactive passthroughs correct, hints and direct questions pass through |

Stuck-flag timeout bug (Run 5): resolved inline in _check_triggers with 60s timeout.
Dead LLMFullResponseEndFrame handler: already absent from codebase.

### Phase 1: Monitor runs

- [x] Monitor loop starts (confirmed all six runs)
- [x] Transcript buffer populated

### Phase 2: Triggers fire

**Trigger 1 (silence):**
- [x] Fires correctly (Runs 2-6)
- [x] No startup false trigger
- [x] Consecutive unanswered limit works
- [x] User speech resets counter
- [x] Reasonable frequency: 2 in ~5min (Run 5), 2 in ~10min (Run 6)
- [x] 42-second silence gap miss diagnosed and fixed (Fix 13, needs live verification)

**Trigger 2 (hesitation):**
- [x] Debug logging added
- [x] Fired in Run 9 (18:09:01): context "Um, um." — score=4, fired after user paused following filler burst.
- [x] Run 10: score=8 (18:22:58, "Um, um, um, um.") — fired but LLM returned silence. Context was filler-only, no clue context. Fix 18 applied (pre-hesitation context enrichment).
- [x] Run 10: score=4 (18:25:03, "Um. Um.") — fired, LLM returned silence. Same root cause. Fix 18 applied.
- [ ] Hesitation fires with LLM giving useful nudge (needs Fix 18 live verification)

**Trigger 3 (confusion):**
- [x] Confusion phrases observed in Run 6 transcripts ("I'm not so sure", "I'm confused")
- [x] Shared cooldown blocking diagnosed and fixed (Fix 12, needs live verification)
- [x] Run 9: detection working — "confusion pattern detected: 'i don't know'" logged at 18:09:43, 18:10:18, 18:10:52, 18:11:21. Cursor advances at detection, no spam. Fix 15 confirmed.
- [ ] Not yet fired as independent proactive trigger. When confusion is in a full sentence, reactive pipeline handles it first (correct). Proactive fires only when reactive returns silence AND user stays quiet after. Needs deliberate test (Step 5 Scenario A).

### Phase 3: Suppression works

- [x] _tars_speaking flag blocks triggers during bot speech
- [x] max() baseline blocks triggers after bot speech
- [x] Cooldown gates trigger frequency (30s default, 60s task mode)
- [x] Consecutive unanswered limit (max 2) prevents loops
- [x] SilenceFilter catches silence responses (17 in Run 6)
- [x] Context cleanup verified (37/37 tests)
- [x] Stuck-flag timeout resolved (inline 60s check)
- [x] Separate confusion cooldown applied (Fix 12)
- [x] Silence exempt from _user_speaking_until (Fix 13)

### Phase 4: LLM responds appropriately

- [x] LLM responds when trigger fires
- [x] LLM returns silence on unanswered probes
- [x] LLM infers crossword context from transcript (Run 5: SIM, CARS; Run 6: BIN, OMEN, BINGOS, CAST)
- [x] Task mode silence compliance (17 suppressions in Run 6 via SilenceFilter; now handled deterministically by ReactiveGate — LLM compliance no longer required for silence)
- [x] LLM still breaks silence on clue narration. Fix 11 applied. Run 11 verified: SilenceFilter suppressed at 18:54:28, 18:54:44. ReactiveGate (Fix 22) makes this permanent — gate drops frames before SilenceFilter sees them.
- [x] Response length: "1-2 sentences maximum" confirmed in build_proactive_section() (Issue C, resolved)
- [ ] Correction phrase ("You shouldn't answer") triggered set_task_mode('off') in Run 7 — task mode dropped mid-session, guardrails lost. Fix 14 applied (CONDITION C + tool schema), needs live verification.

### Phase 5: AEC

- [x] Browser AEC confirmed all runs

### Phase 6: Crossword app

- [x] App loads, grid renders, typing/submission works
- [x] Event logging confirmed (clue_selected, cell_typed with timestamps)
- [x] All 18 clues and intersections verified

---

## Known risks

1. **SilenceFilter buffer latency.** Buffering all LLMTextFrames until EndFrame delays TTS start. ReactiveGate adds a second buffer upstream — two buffering stages in sequence. Consider measuring end-to-end latency on passthroughs.
2. **Confusion trigger vs reactive pipeline overlap.** Confusion phrases as standalone utterances go through reactive path first. If ReactiveGate suppresses (think-aloud), confusion proactive still fires. If ReactiveGate passes (directed question), reactive handles it — confusion proactive fires on cooldown anyway. Double-response risk is low but possible if user says "I'm confused, can you help?" — reactive passes + proactive queued.
3. **Phrase list coverage gaps.** ReactiveGate relies on substring match against fixed phrase lists. Novel directed-question phrasing (e.g., "what would you say?", "any ideas?") currently suppressed. Monitor logs for suppressed passthroughs that should have fired.
4. **Confusion timing threshold fixed at 4s.** Fast talkers who self-resolve quickly may still trigger confusion. Slow talkers who pause mid-thought may suppress a genuine confusion trigger. Threshold may need tuning after more sessions.

---

## Session log

| Run | Date | Key result |
|-----|------|------------|
| 1 | Mar 2 | Context explosion, broken SilenceFilter, echo, double TTS |
| 2 | Mar 3 | Silence trigger fires but during bot speech. AEC confirmed. |
| 3 | Mar 3 | Three-layer suppression working. Infinite loop, startup false trigger. |
| 4 | Mar 3 | Consecutive limit working. Identified prompt issues A-C. |
| 5 | Mar 3 | First crossword test. LLM infers context. Reactive over-triggering. |
| 6 | Mar 4 | Task mode working (17 suppressions). Three new bugs found, all fixed (11-13). |
| 7 | Mar 4 | Crossword session. "You shouldn't answer" triggered set_task_mode('off') — task mode dropped, TARS answered directly for rest of session. Fix 14 applied. |
| 8 | Mar 4 | Crossword session. "Okay, evening." (clue resolution) triggered set_task_mode('off') prematurely. After task mode off, TARS gave direct answers ("CAST"). Corrections ("you shouldn't answer me") had no effect because task mode was already gone. Fix 16 applied. |
| 9 | Mar 4 | Task mode stable (no premature exit). Trigger 2 (hesitation) FIRED first time. Trigger 3 (confusion) detected. New bug: CONDITION A broken — "just give me the answer" got "I'm sorry, but I can't". Hint restriction over-generalized. TARS also refused to give first letter. Fix 17 applied (CONDITION A as explicit override, hint restriction narrowed). |
| 10 | Mar 4 | Triggers 2 and 3 fire correctly but LLM returns silence (no useful nudge). Root cause: hesitation context = filler-only ("Um. Um.") — LLM can't nudge without clue context. Confusion context too stale (accumulated from session start). task_mode OFF from "I, um." — Fix 14/16 insufficient for 2-word fragments. Fixes 18/19/20 applied. |
| 11 | Mar 4 | All three trigger types fired correctly. LLM returned silence for all three. Root cause: silence trigger message said "Only speak if context contains a clear, unresolved question" — hesitation/confusion triggers fire when there IS no question. Clue narration silence verified: SilenceFilter suppressed correctly at 18:54:28 and 18:54:44. Probe messages rewritten (trigger-type-specific, no silence escape hatch for hesitation/confusion). |
| 12 | Mar 4 | Proactive monitor verified: silence trigger fired with richer context (5 entries), confusion trigger fired twice with correct nudges, no direct answers in proactive responses. Remaining issue: reactive pipeline still answering think-aloud (clue narration with letter count, "I'm still thinking" getting a hint instead of Got it.). Fix 21 applied to CONDITION B/C. LLM compliance suite: 22/22 pass. |
| 13 | Mar 4 | ReactiveGate (Fix 22) first live test. Think-aloud suppressed throughout session. Task mode activation acknowledgement working (_task_mode_just_activated flag). "Hey Tars, what's the last letter?" passes through despite STT splitting ("Hey Tars, um." / "What's the last letter?") — 15s window captures both segments. False confusion trigger on "I don't know, I think I'm just going to move on." — self-resolution fix applied (fast-path phrases + 4s timing check). |
| 14 | Mar 4 | Full clean run. ReactiveGate suppressing all think-aloud. Proactive passthroughs correct. Confusion self-resolution ("moving on" fast-path) discarding pending confusion. All three trigger types firing cleanly. Compliance test suite restructured (removed 12 LLM-silence tests, kept 11 gate pass-through tests). |
