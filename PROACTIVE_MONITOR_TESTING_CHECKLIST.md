# Proactive Monitor Testing Checklist

Updated: March 4, 2026. Fifteen live test runs completed (browser mode).
Fixes 1-22 applied. Phase 7 browser-mode testing complete.
System ready for participant evaluation.

Pipeline: Soniox JP + Cerebras GPT-OSS-120B + ElevenLabs Flash v2.5

---

## TODO: What still needs testing

### Phase 7: Integrated dry run (crossword app + TARS) — COMPLETE

All steps verified across Runs 12-15. Summary:

- [x] Think-aloud suppressed (clue narration, guesses, fillers, spelling, "I don't know" with continuation)
- [x] CONDITION C passthrough: "hold on", "let me think", "stop helping", "you shouldn't answer" → "Got it."
- [x] task_mode stays ON after correction; session continued normally
- [x] Silence trigger fires within 20s of last speech with clue context
- [x] Hesitation trigger fires organically (Run 15 ×2); contextual nudge, not generic
- [x] Confusion trigger fires proactively (Runs 12-15, multiple instances); no spam, separate cooldown
- [x] Cooldowns prevent cross-trigger spam; consecutive_unanswered limit working
- [x] Proactive responses: 1-2 sentences, nudge not answer, contextually grounded
- [x] Run 15 intervention rate: ~9 in 15 min (slightly above target; confusion-driven, acceptable)
- [x] CONDITION A override: "give me the answer" → direct answer immediately
- [x] Short fragment protection: filler-only utterances never drop task_mode

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
3. **Phrase list suppression misses.** ReactiveGate relies on fixed phrase lists. Observed miss in run 15: "do I need a hint?" / "I do think I need a hint" — suppressed because "i need a hint" is not in DIRECTED_QUESTION (only "give me a hint" is). User had decided to ask for help but phrased it as self-talk rather than a direct request. Hesitation trigger covered it, but the latency was higher than a direct passthrough. Monitor logs for similar gaps in participant sessions.
4. **"do you know" confirmed passthrough.** Run 15 verified: "Do you know, like, car manufacturer, four letters?" → passthrough via "do you" in DIRECTED_QUESTION. "do you know the answer for Blight?" → passthrough. Working correctly.
5. **"you know" filler vs directed-at-TARS ambiguity.** In run 15 at 21:40:35: "you shouldn't give me the answer, you know?" — CONDITION C passed correctly (TARS gave a hint). "You know" here is a filler tag, not addressing TARS. Gate handled it correctly, but "you know" as a standalone utterance without CONDITION C context could produce a false passthrough. Not observed yet; flag if it appears in participant sessions.
6. **LLM misparse of crossword clue context read aloud.** In run 15 at 21:37:52: user read "Blyton Noddy Arthur" as clue fragments. LLM parsed these as four separate crossword clues (Blight → PEST, On → AT, Naughty → BAD, Arthur → KING) rather than understanding them as a single author-identification clue about Enid Blyton. This will recur whenever the user reads a multi-part clue description aloud. Not a gate issue. Worth tracking in participant evaluation — if it appears consistently, the LLM needs explicit instruction to treat multi-line user speech as a single clue context.
7. **Confusion timing threshold fixed at 4s.** Fast talkers who self-resolve quickly may still trigger confusion. Slow talkers who pause mid-thought may suppress a genuine confusion trigger. Threshold may need tuning after more sessions.

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
| 15 | Mar 4 | Hesitation trigger firing (10s window fix confirmed). "do you know" DIRECTED_QUESTION passthrough verified. Found two new issues: (1) CONDITION A carryover — "give me the answer" at t=0, "I would say Earl" at t=9s, TARS confirmed Earl. Fixed by splitting window: CONDITION A/C now 6s, address/directed-question stays 15s. (2) Suppression miss: "do I need a hint?" / "I do think I need a hint" suppressed because "i need a hint" not in DIRECTED_QUESTION phrase list; hesitation covered it with higher latency. LLM Blyton misparse: user reading "Blyton Noddy Arthur" as clue context — LLM split into four separate answers. "you know" filler tag on CONDITION C sentence: gate handled correctly, not an issue currently. |
