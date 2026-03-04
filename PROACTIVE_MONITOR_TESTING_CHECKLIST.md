# Proactive Monitor Testing Checklist

Updated: March 4, 2026. Six live test runs completed (browser mode).
All code fixes applied (Fixes 1-13). Next step: Phase 7 integrated
dry run to verify Fixes 11-13 in live session.

Pipeline: Soniox JP + Cerebras GPT-OSS-120B + ElevenLabs Flash v2.5

---

## TODO: What still needs testing

### Phase 7: Integrated dry run (crossword app + TARS)

All fixes applied. This is the next live test.

- [ ] Run TARS and crossword web app simultaneously
- [ ] Think-aloud for 8-10 minutes
- [ ] Collect three log files: TARS trigger log, crossword app events, screen/audio recording
- [ ] Count interventions (target: 3-6 in 10 minutes)
- [ ] Verify proactive responses are contextually relevant
- [ ] Verify TTS debounce
- [ ] **Fix 11 verification:** Read clues aloud with letter counts and guesses ("14 down, garbage holder, three letters, bin"). Expect silence.
- [ ] **Fix 12 verification:** Say "I'm not sure about this" within 60s of a silence trigger. Expect confusion trigger fires independently.
- [ ] **Fix 13 verification:** Go silent for 20+ seconds during think-aloud. Expect silence trigger fires without _user_speaking_until suppression.
- [ ] **Trigger 2 verification:** Cluster hesitation fillers ("um... um... uh...") in 3-second burst. Check debug log for hesitation score >= 4.
- [ ] **Trigger 3 verification:** Check debug logs confirm confusion pattern matching runs and logs correctly.

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
- [ ] Not yet fired in live session. Fillers observed but scattered below threshold. Needs deliberate cluster test in Phase 7.

**Trigger 3 (confusion):**
- [x] Confusion phrases observed in Run 6 transcripts ("I'm not so sure", "I'm confused")
- [x] Shared cooldown blocking diagnosed and fixed (Fix 12, needs live verification)
- [ ] Not yet fired independently as proactive trigger. Most confusion phrases handled by reactive pipeline first.

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
- [x] Task mode silence compliance (17 suppressions in Run 6)
- [ ] LLM still breaks silence on clue narration (turns 30, 52, 55). Fix 11 applied, needs live verification.
- [ ] Response length unconstrained (Issue C)

### Phase 5: AEC

- [x] Browser AEC confirmed all runs

### Phase 6: Crossword app

- [x] App loads, grid renders, typing/submission works
- [x] Event logging confirmed (clue_selected, cell_typed with timestamps)
- [x] All 18 clues and intersections verified

---

## Known risks

1. **SilenceFilter buffer latency.** Buffering all LLMTextFrames until EndFrame delays TTS start. Consider buffering only during proactive probes.
2. **Confusion trigger vs reactive pipeline overlap.** Confusion phrases as standalone utterances go through reactive path first. Trigger 3 adds value for embedded phrases and cases where reactive path returns silence. Legitimate finding for report.
3. **LLM defaults to answers not hints.** Notification-first needs reinforcing. User corrected TARS in Run 6 and it adapted, but initial behavior was wrong.

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
