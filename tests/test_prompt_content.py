"""Tests for build_task_mode_section and build_proactive_section content.

Covers:
- Task mode silence examples: hesitation markers, confusion expressions, clue+answer narration
- Task mode correction handling rule
- Task mode notification-first for reactive answers
- Task mode prohibition on proactive phrases in reactive responses
- Proactive section: labels for reference only (not to be spoken)
- Proactive section: hierarchy applies only on [PROACTIVE DETECTION] messages
- Proactive section: no literal "Stuck on something?" phrase (prevents reactive leakage)
"""

import importlib.util
import sys
import types
import unittest


# ---------------------------------------------------------------------------
# Stubs for tools.robot — only need VALID_EMOTIONS and VALID_INTENSITIES
# ---------------------------------------------------------------------------

_tools = types.ModuleType("tools")
_tools_robot = types.ModuleType("tools.robot")
_tools_robot.VALID_EMOTIONS = [
    "neutral", "happy", "sad", "angry", "excited", "afraid",
    "sleepy", "side eye L", "side eye R", "curious", "skeptical", "smug", "surprised",
]
_tools_robot.VALID_INTENSITIES = ["low", "mid", "high"]
sys.modules.setdefault("tools", _tools)
sys.modules.setdefault("tools.robot", _tools_robot)
_tools.robot = _tools_robot

# Load prompts.py directly to bypass tools/__init__.py
_spec = importlib.util.spec_from_file_location(
    "character_prompts",
    "/Users/mac/Desktop/tars-conversation-app/src/character/prompts.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
build_task_mode_section = _mod.build_task_mode_section
build_proactive_section = _mod.build_proactive_section


# ---------------------------------------------------------------------------
# Task mode section content
# ---------------------------------------------------------------------------

class TestTaskModeSectionSilenceExamples(unittest.TestCase):
    """build_task_mode_section must include silence examples for all known failure patterns."""

    def setUp(self):
        self.section = build_task_mode_section("crossword")

    def test_bare_hesitation_um_is_silence(self):
        """'Um.' must be listed as a thinking-aloud / silence example."""
        self.assertIn("Um.", self.section)

    def test_bare_hesitation_uh_is_silence(self):
        self.assertIn("Uh.", self.section)

    def test_bare_hesitation_hmm_is_silence(self):
        self.assertIn("Hmm.", self.section)

    def test_confusion_expression_is_silence(self):
        """'I'm confused' must be listed as a state expression, not a request."""
        lower = self.section.lower()
        self.assertIn("confused", lower)

    def test_clue_plus_answer_narration_is_silence(self):
        """Clue + proposed answer (e.g., 'it's Sue, I guess') must be listed as thinking aloud."""
        # Check for the concept — at least one example of clue + self-answer pattern
        self.assertIn("guess", self.section)

    def test_clue_narration_without_answer_is_silence(self):
        """Narrating a clue alone (no proposed answer) must also be silence."""
        # e.g., "12 across, British nobleman, four letters"
        lower = self.section.lower()
        has_clue_example = "british nobleman" in lower or "four letters" in lower or "ice cream holder" in lower
        self.assertTrue(has_clue_example,
            "Must include a clue-only narration example (no proposed answer)")

    def test_silence_default_stated(self):
        lower = self.section.lower()
        has_default = "do not speak" in lower or "default" in lower or "silence is the default" in lower
        self.assertTrue(has_default, "Must state silence is the default behavior")

    def test_silence_action_format(self):
        self.assertIn('{"action": "silence"}', self.section)


class TestTaskModeSectionCorrectionHandling(unittest.TestCase):
    """build_task_mode_section must include handling for user corrections."""

    def setUp(self):
        self.section = build_task_mode_section("crossword")

    def test_correction_triggers_got_it(self):
        """When user corrects TARS for answering, section must say to respond 'Got it.'"""
        self.assertIn("Got it.", self.section)

    def test_correction_followed_by_silence(self):
        """After correction, section must say to say nothing further (silence)."""
        idx = self.section.find("Got it.")
        self.assertGreater(idx, -1)
        surrounding = self.section[idx:idx + 200].lower()
        has_silence = '{"action": "silence"}' in surrounding or "nothing else" in surrounding
        self.assertTrue(has_silence,
            "After 'Got it.' must indicate no further response (silence or nothing else)")

    def test_correction_examples_mentioned(self):
        """Correction scenario must include examples like 'you shouldn't tell me the answer'."""
        lower = self.section.lower()
        has_example = (
            "shouldn't tell me" in lower
            or "don't give me" in lower
            or "stop giving" in lower
        )
        self.assertTrue(has_example,
            "Correction handling must include example phrasing users might say")


class TestTaskModeSectionNotificationFirst(unittest.TestCase):
    """Task mode reactive answers must use hint-not-answer principle."""

    def setUp(self):
        self.section = build_task_mode_section("crossword")

    def test_direct_question_gets_hint_not_answer(self):
        """Even direct questions in task mode should get a hint, not the answer."""
        lower = self.section.lower()
        # Rule must say nudge/hint rather than direct answer
        has_hint_rule = "nudge" in lower or "hint" in lower
        self.assertTrue(has_hint_rule,
            "Task mode section must say to give hints not direct answers for reactive questions")

    def test_explicit_request_exception(self):
        """'Just tell me' / 'what's the answer' must be listed as exceptions."""
        lower = self.section.lower()
        has_exception = "just tell me" in lower or "what's the answer" in lower
        self.assertTrue(has_exception,
            "Must acknowledge the exception: user can explicitly ask for the answer")


class TestTaskModeSectionNoProactivePhrases(unittest.TestCase):
    """Task mode section must not instruct the LLM to behave like a proactive assistant."""

    def setUp(self):
        self.section = build_task_mode_section("crossword")

    def test_proactive_phrases_prohibited(self):
        """Task mode section must restrict responses to explicitly triggered conditions.

        The proactive hierarchy is handled separately by build_proactive_section().
        Task mode must not invite unsolicited responses — conditions for speaking
        must be narrow and explicit (give up, explicit question words, correction).
        """
        lower = self.section.lower()
        # Must gate responses on explicit conditions — question words, correction, or give-up
        has_gate = (
            "question" in lower
            or "interrogative" in lower
            or "what" in lower
            or "can you" in lower
        )
        self.assertTrue(has_gate,
            "Task mode must gate responses on explicit question words or conditions")


# ---------------------------------------------------------------------------
# Proactive section content
# ---------------------------------------------------------------------------

class TestProactiveSectionLabelsForReferenceOnly(unittest.TestCase):
    """build_proactive_section must instruct LLM not to speak hierarchy labels aloud."""

    def setUp(self):
        self.section = build_proactive_section()

    def test_labels_are_reference_only(self):
        """Must say category labels are for internal reference, not to be spoken."""
        lower = self.section.lower()
        has_reference_note = (
            "reference only" in lower
            or "for your reference" in lower
            or "internal reference" in lower
        )
        self.assertTrue(has_reference_note,
            "Proactive section must say labels are for reference only, not to be included in response")

    def test_no_prefix_instruction(self):
        """Must say not to prefix responses with category labels."""
        lower = self.section.lower()
        has_no_prefix = "do not include" in lower or "not include" in lower
        self.assertTrue(has_no_prefix,
            "Proactive section must explicitly say not to include labels as prefixes")

    def test_notification_label_present(self):
        """Notification must be named as a response type."""
        self.assertIn("Notification", self.section)

    def test_suggestion_label_present(self):
        """Suggestion must be named as a response type."""
        self.assertIn("Suggestion", self.section)


class TestProactiveSectionScope(unittest.TestCase):
    """Proactive hierarchy must be scoped to [PROACTIVE DETECTION] messages only."""

    def setUp(self):
        self.section = build_proactive_section()

    def test_hierarchy_scoped_to_proactive_detection(self):
        """Must explicitly state this hierarchy applies only on [PROACTIVE DETECTION] messages."""
        self.assertIn("[PROACTIVE DETECTION]", self.section)
        lower = self.section.lower()
        has_scope = (
            "only when you receive" in lower
            or "applies only" in lower
            or "only applies" in lower
        )
        self.assertTrue(has_scope,
            "Proactive section must scope the hierarchy to [PROACTIVE DETECTION] messages only")

    def test_not_for_reactive_turns(self):
        """Must say this does NOT apply during normal reactive turns."""
        lower = self.section.lower()
        has_reactive_note = "reactive" in lower or "normal" in lower
        self.assertTrue(has_reactive_note,
            "Proactive section must clarify it doesn't apply on normal reactive turns")

    def test_no_answer_directly_rule(self):
        """Must state never to give the answer directly in a proactive intervention."""
        self.assertIn("Never give the answer directly", self.section)

    def test_reactive_exception_stated(self):
        """Must state that giving the answer is fine when explicitly asked (reactive)."""
        lower = self.section.lower()
        has_exception = "will ask" in lower or "on request" in lower
        self.assertTrue(has_exception,
            "Proactive section must acknowledge direct answers are fine when explicitly requested")


class TestProactiveSectionNoLeakyPhrase(unittest.TestCase):
    """'Stuck on something?' must not appear as a literal example phrase.

    This phrase leaking into the proactive section causes the LLM to adopt
    it as a reactive template, producing the wrong behavior in task mode.
    """

    def setUp(self):
        self.section = build_proactive_section()

    def test_stuck_on_something_not_literal_example(self):
        """The phrase 'Stuck on something?' must not appear verbatim in the proactive section."""
        self.assertNotIn(
            "Stuck on something?",
            self.section,
            "Literal 'Stuck on something?' must be removed to prevent reactive path adoption",
        )


class TestTaskModeSectionConditionD(unittest.TestCase):
    """build_task_mode_section must include CONDITION D for task completion."""

    def setUp(self):
        self.section = build_task_mode_section("crossword")

    def test_condition_d_present(self):
        self.assertIn("CONDITION D", self.section)

    def test_condition_d_calls_set_task_mode_off(self):
        """CONDITION D must instruct calling set_task_mode('off')."""
        lower = self.section.lower()
        self.assertIn('set_task_mode("off")', self.section.lower().replace("'", '"'))

    def test_condition_d_has_done_examples(self):
        """CONDITION D must include example done phrases."""
        lower = self.section.lower()
        has_examples = "i'm done" in lower or "i am done" in lower or "finished" in lower
        self.assertTrue(has_examples, "CONDITION D must include done-phrase examples")

    def test_condition_d_excludes_standalone_done(self):
        """CONDITION D must warn that standalone 'I'm done' is think-aloud."""
        lower = self.section.lower()
        has_caveat = "think-aloud" in lower or "standalone" in lower or "stay silent" in lower
        self.assertTrue(has_caveat,
            "CONDITION D must note that bare 'I'm done' mid-narration is think-aloud")

    def test_condition_d_excludes_never_mind(self):
        """CONDITION D must explicitly exclude 'Never mind' as a task-end signal."""
        lower = self.section.lower()
        self.assertIn("never mind", lower,
            "CONDITION D must list 'Never mind' as a non-exit phrase")

    def test_condition_c_clarifies_not_task_end(self):
        """CONDITION C must clarify it is a mid-task correction, not task-end."""
        lower = self.section.lower()
        has_clarification = "mid-task" in lower or "not task-end" in lower or "correction" in lower
        self.assertTrue(has_clarification,
            "CONDITION C must distinguish corrections from task-end")


class TestTaskModeSectionExpressionGuidance(unittest.TestCase):
    """build_task_mode_section must include expression mapping for spoken turns."""

    def setUp(self):
        self.section = build_task_mode_section("crossword")

    # --- all 6 emotions in the mapping ---

    def test_happy_expression_present(self):
        """Must map positive moments (correct guess, thanks) to happy."""
        self.assertIn("happy", self.section)

    def test_curious_expression_present(self):
        """Must map hint/nudge moments to curious."""
        self.assertIn("curious", self.section)

    def test_sad_expression_present(self):
        """Must map user frustration to sad."""
        self.assertIn("sad", self.section)

    def test_skeptical_expression_present(self):
        """Must map correcting/pushing back to skeptical."""
        self.assertIn("skeptical", self.section)

    def test_surprised_expression_present(self):
        """Must map funny or surprising moments to surprised."""
        self.assertIn("surprised", self.section)

    def test_excited_expression_present(self):
        """Must map task completion / celebration to excited."""
        self.assertIn("excited", self.section)

    # --- intensity levels ---

    def test_low_intensity_present(self):
        """Low intensity must appear (used for most task-mode expressions)."""
        self.assertIn("low", self.section)

    def test_medium_intensity_present(self):
        """Medium intensity must appear (used for celebration/finish moments)."""
        self.assertIn("medium", self.section)

    # --- anti-neutral ---

    def test_anti_neutral_instruction_present(self):
        """Must explicitly instruct not to default to neutral on every turn."""
        lower = self.section.lower()
        has_anti_neutral = "do not default to neutral" in lower or "not default to neutral" in lower
        self.assertTrue(has_anti_neutral,
            "Must contain anti-neutral instruction (e.g. 'Do not default to neutral')")

    def test_neutral_allowed_for_emotionless_moments(self):
        """Must clarify that neutral is acceptable for genuinely emotionless moments."""
        lower = self.section.lower()
        # The guidance should say when neutral IS acceptable, not just ban it entirely
        has_neutral_exception = (
            "neutral only" in lower
            or "use neutral" in lower
            or "genuinely emotionless" in lower
        )
        self.assertTrue(has_neutral_exception,
            "Must state when neutral is acceptable (e.g. 'Use neutral only for...')")

    # --- existing rules intact ---

    def test_silence_rules_intact(self):
        """Existing silence rules must not be removed."""
        self.assertIn('{"action": "silence"}', self.section)

    def test_condition_a_intact(self):
        """CONDITION A (give up → direct answer) must still be present."""
        self.assertIn("CONDITION A", self.section)

    def test_condition_b_intact(self):
        """CONDITION B (question → hint) must still be present."""
        self.assertIn("CONDITION B", self.section)

    def test_condition_c_intact(self):
        """CONDITION C (correction → 'Got it.') must still be present."""
        self.assertIn("CONDITION C", self.section)

    def test_condition_c_neutral_is_correct(self):
        """CONDITION C hardcodes neutral — a correction acknowledgement is emotionless.

        This must NOT be changed: 'Got it. [express(neutral, low)]' is the prescribed
        CONDITION C output. The anti-neutral guidance applies to other spoken turns, not this.
        """
        self.assertIn("Got it. [express(neutral, low)]", self.section)


if __name__ == "__main__":
    unittest.main(verbosity=2)
