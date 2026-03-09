# Interruption & Anti-Parroting Checklist — March 9, 2026

Run in **robot mode** (`tars_bot.py`). Requires RPi connected with audio working.

---

## Pre-flight

- [ ] Start `tars_bot.py`, confirm RPi connection, audio working
- [ ] Confirm TARS is speaking back (say something, wait for response)

---

## 1. Audio interruption — basic cut

- [x] TARS is mid-sentence speaking a longer response
- [x] Say something while TARS is speaking
- [x] TARS audio stops immediately (no tail audio on RPi speaker)
- [x] TARS processes your new utterance without hanging

---

## 2. Audio interruption — `flush()` clears buffer

- [x] TARS is speaking a multi-sentence response (trigger with a question requiring a longer answer)
- [x] Interrupt mid-way through
- [x] No leftover audio plays after interruption (buffer fully cleared)
- [x] `rpi_output_track.flush()` empties queue and `_buf`

---

## 3. `BotStoppedSpeakingFrame` on interruption

- [x] Interrupt TARS mid-speech
- [x] Logs show `BotStoppedSpeakingFrame` emitted (not skipped)
- [x] Next TTS cycle starts cleanly — no double-speaking or stuck state
- [x] `_speaking` flag resets to `False` after interruption

---

## 4. `CancelFrame` path — flush on cancel

- [x] Trigger a cancel scenario (e.g., user speaks while pipeline is mid-TTS)
- [x] `CancelFrame` hits `AudioBridge` → `rpi_output_track.flush()` called
- [x] Audio stops; pipeline recovers and handles next input normally

---

## 5. Repeated interruptions

- [x] Interrupt TARS 3 times in a row on different utterances
- [x] Each time: audio cuts, `_speaking` resets, new response generated
- [x] No accumulation of stuck state or ghost audio

---

## 6. Anti-parroting — clue echo suppression (reactive)

Say: *"5 letters, starts with P, means allowed by law."*

- [ ] TARS does NOT say: "Think of a 5-letter P word that means legal" or any rephrase of the clue
- [ ] TARS offers a different angle: category, common phrase, wordplay, or context
- [ ] Example good response: "This word often comes up in contracts and official documents."

---

## 7. Anti-parroting — clue echo suppression (proactive hint)

Let hesitation or confusion trigger fire on the same clue.

- [ ] TARS proactive hint does NOT mirror back letter count, starting letter, or definition
- [ ] TARS offers a related concept, category association, or phrasing context
- [ ] Confirm in logs: `Suggestion` level applied, not `Notification`

---

## 8. Hint variety — CONDITION B

Say: *"Like what? What do you mean?"* (follow-up after a hint)

- [ ] TARS gives a second hint that is NOT a rephrasing of the first hint
- [ ] TARS does NOT echo the original clue details back
- [ ] Second hint uses a different angle (wordplay, phrase, category shift)

---

## 9. Repeated proactive hint — skip suggestion

Simulate TARS having hinted at the same clue 2+ times (via conversation history).
Let another proactive trigger fire for the same clue.

- [ ] TARS does NOT generate a third hint
- [ ] TARS suggests skipping: e.g., "You might want to skip this one and come back to it."
- [ ] Response is one sentence

---

## 10. No-monitor task-mode-off fallback (parroting commit)

With `proactive_monitor` unavailable, say a short phrase like *"off"* or *"stop"*.

- [ ] TARS rejects the task-mode-off call (word count ≤ 4)
- [ ] Log: `set_task_mode('off') REJECTED (no monitor): short utterance`
- [ ] TARS responds: "Task mode stays active — that didn't sound like you're done."

---

## 11. Combined — interruption during a parroted-style response

- [ ] Trigger a response where TARS would otherwise parrot (give a clue and wait)
- [ ] Interrupt TARS before it finishes if it starts echoing
- [ ] Confirm audio cuts and new input processed

---

## Known issues to watch

- [x] No leftover audio on RPi after interruption
- [x] `_speaking` does not get stuck `True` after rapid back-to-back interruptions
- [x] Pipeline does not hang waiting for `BotStoppedSpeakingFrame` that was never sent
