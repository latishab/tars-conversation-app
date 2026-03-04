"""Unit tests for ReactiveGate._should_pass_through logic.

No LLM calls, no I/O — pure deterministic gate logic.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from unittest.mock import MagicMock
from processors.reactive_gate import ReactiveGate


def make_gate(task_context="crossword", transcript_texts=None, proactive_pending=False):
    """transcript_texts: list of strings (most recent within window) or a single string."""
    monitor = MagicMock()
    monitor._task_context = task_context
    monitor._proactive_response_pending = proactive_pending
    monitor._task_mode_just_activated = False
    now = time.time()
    if transcript_texts is None:
        monitor._transcript_buffer = []
    elif isinstance(transcript_texts, str):
        monitor._transcript_buffer = [{"text": transcript_texts, "timestamp": now}]
    else:
        monitor._transcript_buffer = [
            {"text": t, "timestamp": now - (len(transcript_texts) - i) * 2}
            for i, t in enumerate(transcript_texts)
        ]
    gate = ReactiveGate(monitor)
    return gate


# ---- task mode off ----------------------------------------------------------

def test_gate_inactive_without_task_mode():
    gate = make_gate(task_context="", transcript_texts="opposite of day, five letters")
    assert gate._should_pass_through() is True


# ---- proactive flag ---------------------------------------------------------

def test_gate_passes_proactive_responses():
    gate = make_gate(proactive_pending=True, transcript_texts="opposite of day, five letters")
    assert gate._should_pass_through() is True
    assert gate._monitor._proactive_response_pending is False


# ---- task mode activation ---------------------------------------------------

def test_gate_passes_task_mode_activation():
    monitor = MagicMock()
    monitor._task_context = "crossword"
    monitor._proactive_response_pending = False
    monitor._task_mode_just_activated = True
    monitor._transcript_buffer = [{"text": "I'm going to do a crossword, thinking aloud.", "timestamp": time.time()}]
    gate = ReactiveGate(monitor)
    assert gate._should_pass_through() is True
    assert gate._monitor._task_mode_just_activated is False


# ---- CONDITION A (surrender) ------------------------------------------------

def test_gate_passes_surrender():
    for phrase in ("just tell me", "give me the answer", "what's the answer",
                   "i give up", "tell me the answer", "what is it"):
        gate = make_gate(transcript_texts=phrase)
        assert gate._should_pass_through() is True, f"failed on: {phrase!r}"


# ---- direct address ---------------------------------------------------------

def test_gate_passes_direct_address():
    gate = make_gate(transcript_texts="Tars, what's a five-letter word for poison?")
    assert gate._should_pass_through() is True

    gate = make_gate(transcript_texts="hey tars can you help me")
    assert gate._should_pass_through() is True


# ---- DIRECTED_QUESTION phrases ----------------------------------------------

def test_gate_passes_directed_questions():
    for phrase in ("can you give me a hint", "could you help", "do you know this one",
                   "help me with this", "give me a hint", "what do you think",
                   "tell me more"):
        gate = make_gate(transcript_texts=phrase)
        assert gate._should_pass_through() is True, f"failed on: {phrase!r}"


# ---- CONDITION C (corrections) ----------------------------------------------

def test_gate_passes_corrections():
    for phrase in ("stop helping", "stop answering", "don't talk", "don't give me the answer",
                   "i didn't ask", "you shouldn't answer", "hold on",
                   "let me think", "i'm still thinking", "i'm trying to think"):
        gate = make_gate(transcript_texts=phrase)
        assert gate._should_pass_through() is True, f"failed on: {phrase!r}"


# ---- think-aloud suppression ------------------------------------------------

def test_gate_suppresses_think_aloud():
    think_aloud = [
        "12 across, British nobleman, four letters",
        "opposite of day, five letters, um",
        "I think it's Earl",
        "bin",
        "I would say either FBI or CIA. Pick CIA.",
        "Um.",
        "Uh.",
        "Hmm.",
        "okay, next clue",
        "anyways moving on",
        "this is hard",
        "what does this even mean",
        "three letters, take legal action, it's Sue",
        "I'll go with Earl.",
        "I don't know, I'm confused. Ugh. Okay.",
        "evening",
    ]
    for utterance in think_aloud:
        gate = make_gate(transcript_texts=utterance)
        assert gate._should_pass_through() is False, f"should suppress: {utterance!r}"


# ---- empty buffer -----------------------------------------------------------

def test_gate_passes_empty_buffer():
    gate = make_gate(transcript_texts=None)
    assert gate._should_pass_through() is True


# ---- window: intent in earlier segment --------------------------------------

def test_gate_passes_tars_in_earlier_segment():
    """'Hey Tars, um.' then 'What's the last letter?' — tars is in prior segment."""
    gate = make_gate(transcript_texts=["Hey Tars, um.", "What's the last letter?"])
    assert gate._should_pass_through() is True


def test_gate_passes_can_you_split_across_segments():
    """'Can you tell me the last.' then 'Letter?' — 'can you' is in prior segment."""
    gate = make_gate(transcript_texts=["Can you tell me the last.", "Letter?"])
    assert gate._should_pass_through() is True


def test_gate_suppresses_when_tars_outside_window():
    """'Tars, hello.' from 20s ago then a think-aloud now — outside window, suppress."""
    import time
    monitor = MagicMock()
    monitor._task_context = "crossword"
    monitor._proactive_response_pending = False
    monitor._task_mode_just_activated = False
    now = time.time()
    monitor._transcript_buffer = [
        {"text": "Hey Tars, hello.", "timestamp": now - 20},  # outside 15s window
        {"text": "opposite of day, five letters", "timestamp": now - 1},
    ]
    from processors.reactive_gate import ReactiveGate
    gate = ReactiveGate(monitor)
    assert gate._should_pass_through() is False


def test_gate_suppresses_condition_a_carryover():
    """CONDITION A 9s ago then new clue think-aloud — short window should suppress."""
    import time
    monitor = MagicMock()
    monitor._task_context = "crossword"
    monitor._proactive_response_pending = False
    monitor._task_mode_just_activated = False
    now = time.time()
    monitor._transcript_buffer = [
        {"text": "please give me the answer", "timestamp": now - 9},  # outside 6s intent window
        {"text": "British nobleman, I would say Earl", "timestamp": now - 1},
    ]
    from processors.reactive_gate import ReactiveGate
    gate = ReactiveGate(monitor)
    assert gate._should_pass_through() is False
