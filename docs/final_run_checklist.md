# Final Run Testing Checklist — March 6, 2026

Run in **robot mode** (`tars_bot.py`). This is the eval configuration.

## Pre-flight

- [x] Verify `persona_storage["context"] = context` is in `tars_bot.py`
- [x] Start `tars_bot.py`, confirm RPi connection, audio working

---

## 1. Task mode prompt injection

- [x] Say: "Hey Tars, I'm going to do a crossword."
- [x] Logs: `System prompt updated: task_mode=crossword` ✓
- [x] TARS responds: "Crossword mode." ✓

---

## 2. ReactiveGate suppression (think-aloud)

- [x] Think-aloud clues suppressed ✓
- [x] Self-answers ("I think it's night.") suppressed ✓
- [x] Filler utterances ("Um.", "Let me think.") suppressed ✓

---

## 3. Proactive triggers

### Silence trigger (Notification level)
- [x] Fires after 15s of user speech with no TARS response ✓
- [x] Does NOT fire when TARS had the last word (post_bot empty guard) ✓
- [x] Response is a check-in referencing what user was working on ✓
- [x] Example: "That last clue still giving you trouble — need a nudge?" ✓
- [x] Does not offer a hint or answer unprompted ✓
- [x] Expression: `[express(curious, low)]` ✓

### Hesitation trigger (Suggestion level)
- [x] Fires on hesitation cluster (score ≥ threshold) ✓
- [x] Response is a nudge — direction or angle, not the answer ✓
- [x] Does not name specific answers, solutions, or words ✓
- [x] Example: "Think about which continent is renowned for having the largest population..." ✓

### Confusion trigger (Suggestion level)
- [x] Fires on confusion pattern ("i don't know", "i'm confused") ✓
- [x] Response is a nudge — direction or angle, not the answer ✓
- [x] Does not name specific answers, solutions, or words ✓
- [x] Example: "Consider which three-letter abbreviation commonly represents a major part of the U.S. government structure." ✓

---

## 4. Proactive followup window

- [x] Silence trigger fires → `ReactiveGate: proactive passthrough` ✓
- [x] `ReactiveGate: proactive followup window passthrough` visible on followup turns ✓
- [x] User says "Yes please" after notification → Suggestion-level nudge only (not the answer) ✓
- [x] Example: "Think about what you usually write on a name tag..." ✓
- [x] Window correctly expires on new topic → suppressed ✓
- [x] Confusion trigger fires new proactive passthrough → chaining resumes ✓

---

## 5. CONDITION A — explicit give-up

- [x] User says "Hey TARS, I give up." → TARS gives direct answer ✓
- [x] Example: "The answer is FED." ✓
- [x] Expression: medium intensity ✓

---

## 6. CONDITION B — user asks for hint

- [x] User asks "Like what? Like what, TARS?" → TARS gives nudge, not the answer ✓
- [x] Multiple followup questions handled at Suggestion level ✓
- [x] "Is it TIA or FBI?" / "Is it CIA?" → TARS narrows without giving answer ✓

---

## 7. CONDITION C — user asks TARS to stop

- [x] Gate and prompt handle correction phrases ✓

---

## 8. Task mode exit (CONDITION D)

- [x] "Hey Tars, I'm done with the crossword." → `ProactiveMonitor: task mode OFF` ✓
- [x] `System prompt updated: task_mode=None` ✓
- [x] TARS acknowledges briefly ✓
- [x] Think-aloud suppression OFF after exit — casual speech responded to normally ✓
- [x] Mid-session "off" correctly rejected without direct address + end signal ✓

---

## 9. Stale context fix (silence trigger)

- [x] After TARS resolves a clue and user goes silent: silence trigger does NOT fire ✓
- [x] After user states a new clue and goes silent: silence trigger fires with fresh context ✓
- [x] No `fired silence trigger` entries with empty or pre-resolution context ✓

---

## 10. Prompt task-agnosticism

- [x] Condition prompts (silence/hesitation/confusion) contain no crossword-specific language ✓
- [x] Crossword examples self-contained in `build_task_examples("crossword")` ✓
- [x] Tone section and general examples section contain no crossword-specific instructions ✓

---

## 11. Latency

- [x] P50/P95 summary printed on disconnect ✓
- [x] `logs/sessions/latency_*.json` written ✓

```
stt_ttfb   p50=292ms   p95=390ms
llm_ttfb   p50=358ms   p95=498ms
tts_ttfb   p50=138ms   p95=172ms
ttfa       p50=1132ms  p95=2598ms  ← p95 skewed by silence-trigger wait windows
total      p50=782ms   p95=1033ms
```

Steady-state reactive turns: 700–1000ms. P95 skew expected from proactive fire latency.

---

## Known issues / resolved

- ~~Expressions stuck on `neutral/low`~~ — fixed (March 6)
- ~~First proactive silence response swallowed by SilenceFilter~~ — fixed (March 6)
- ~~Stale context in silence trigger after resolved topics~~ — fixed (March 6)
- ~~Hesitation/confusion triggers giving direct answers~~ — fixed (March 6)
- ~~Followup "yes please" triggering full answer~~ — fixed (March 6)
