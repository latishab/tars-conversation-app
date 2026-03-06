# Final Run Testing Checklist — March 6, 2026

Run in **robot mode** (`tars_bot.py`). This is the eval configuration.

## Pre-flight

- [x] Add temporary debug logging in `src/tools/persona.py` after system prompt update:
  ```python
  logger.debug(f"System prompt length: {len(context.messages[0]['content'])} chars")
  logger.debug(f"CONDITION B present: {'CONDITION B' in context.messages[0]['content']}")
  ```
- [x] Verify `persona_storage["context"] = context` is in `tars_bot.py` (today's bug fix)
- [x] Start `tars_bot.py`, confirm RPi connection, audio working

---

## 1. Task mode prompt injection (context bug fix)

- [x] Say: "Hey Tars, I'm going to do a crossword, thinking aloud."
- [x] Check logs for: `System prompt updated: task_mode=crossword` ✓
- [ ] Check logs for: `CONDITION B present: True` — **not visible; debug logs require lowering log level**
- [ ] Check logs for: system prompt length (~3000-4000 chars, not suspiciously short) — same issue

**Note:** Debug lines are `logger.debug` — invisible at INFO level. Re-run with `--log-level debug` to verify, or temporarily promote to `logger.info`.

**If CONDITION B present: False or no system prompt update log → STOP. Bug fix didn't work.**

---

## 2. Expression tuning

- [x] Say: "Tars, can you give me a hint?" (multiple clues tested)
- [x] Check: TARS gives hints, not direct answers ✓
- [x] Check: response ends with `[express(curious, low)]` ✓ (confirmed March 6, third run)
- [ ] Say: "Just tell me the answer."
- [ ] Check: TARS gives the direct answer
- [ ] Check: response uses medium intensity expression

**Fix applied:** Rebalanced `build_examples_section()` in `prompts.py` (neutral/low → curious/skeptical/smug/happy/side eye R) + added situation-to-emotion mapping to `express_reminder` in `proactive_monitor.py`.

---

## 3. ReactiveGate suppression (think-aloud)

- [x] Think-aloud clues suppressed ✓
- [x] "I think it's night." type responses suppressed ✓
- [x] Filler utterances ("Um.", "Let me think.") suppressed ✓

---

## 4. Proactive triggers

### Silence trigger
- [x] Silence trigger fires in logs ✓
- [x] Check: TARS delivers check-in on first fire ✓ (SilenceFilter swallow bug resolved in second run)
- [x] Check: response has a non-neutral expression tag ✓ (curious/low confirmed March 6, third run)

### Hesitation trigger
- [x] Hesitation trigger fired: `hesitation score >= 4` ✓
- [x] TARS responded with relevant hint ✓

### Confusion trigger
- [x] `ProactiveMonitor: confusion pattern detected: 'i don't know'` ✓
- [x] TARS responded with help ✓

---

## 5. Proactive followup window chaining

**Confirmed working** (March 6, second run).

- [x] Silence trigger fires → `ReactiveGate: proactive passthrough` ✓
- [x] `ReactiveGate: proactive followup window passthrough` visible in logs ✓
- [x] Window chains across multiple turns ("Yeah, like what?" → "What do you mean?" → "Is it level?" → "Thank you, TARS.") ✓
- [x] Window correctly expires on new topic ("Okay, so another. Clue is competing...") → suppressed ✓
- [x] Confusion trigger fires new proactive passthrough → chaining resumes ✓
- [x] First silence trigger response no longer swallowed by SilenceFilter ✓ (previous run bug resolved)

---

## 6. Task mode exit (CONDITION D)

- [x] Say: "Hey Tars, I'm done with the crossword."
- [x] Check logs for: `ProactiveMonitor: task mode OFF` ✓
- [x] Check logs for: `System prompt updated: task_mode=None` ✓
- [x] Check logs for: NOT rejected by code guard ✓
- [x] Check: TARS responds with acknowledgment — "Got it." ✓
- [ ] Check: response has medium intensity expression — pending re-test
- [x] Verify think-aloud suppression is OFF: said something casual, TARS responded normally ✓

**Note:** Mid-session `set_task_mode('off')` was correctly rejected when user said "Crossword. Hold on." — code guard working. Expression system functional when explicitly directed (angry/high + Wiggle fired correctly on request).

---

## 7. Latency summary

- [x] Disconnect from the session (close browser or ctrl+C)
- [x] Check console for P50/P95 summary table ✓
- [x] Check `logs/sessions/latency_*.json` exists — `logs/sessions/latency_20260306_193835.json` ✓
- [ ] Verify P50 TTFA is in the expected range (~700-1000ms) — **P50 TTFA: 1131.8ms, slightly above target**

```
stt_ttfb   p50=292ms   p95=390ms
llm_ttfb   p50=358ms   p95=498ms
tts_ttfb   p50=138ms   p95=172ms
ttfa       p50=1132ms  p95=2598ms  ← slightly above 700-1000ms target
total      p50=782ms   p95=1033ms
```

P95 ttfa (2598ms) is skewed by silence-trigger turns where TARS waited the full window before firing. Steady-state reactive turns were 700-1000ms.

---

## Issues to fix before eval

~~**Expressions stuck on `neutral/low`**~~ — fixed (March 6, third run confirmed)

1. **CONDITION B debug logging not visible** — promote to `logger.info` or run with debug level
2. **Medium intensity expressions** — not yet observed; need to test "just tell me the answer" / task exit flows

~~**First proactive silence response swallowed by SilenceFilter**~~ — resolved (second run confirmed)

---

## Post-run

- [ ] Remove temporary debug logging from `persona.py`
- [ ] Note any issues found for fixing before tomorrow's eval
- [ ] If all checks pass: ready for evaluation
