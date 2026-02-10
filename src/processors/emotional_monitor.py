"""
Real-time emotional and cognitive state monitoring using continuous video analysis.
Detects hesitation, confusion, frustration, and other emotional cues to trigger TARS intervention.
"""

import asyncio
import time
import base64
from typing import Optional, Dict, List
from loguru import logger
from PIL import Image
import io

from pipecat.frames.frames import (
    Frame,
    ImageRawFrame,
    TextFrame,
    LLMRunFrame,
)
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection


class EmotionalState:
    """Container for detected emotional/cognitive state"""

    def __init__(
        self,
        confused: bool = False,
        hesitant: bool = False,
        frustrated: bool = False,
        focused: bool = False,
        confidence: float = 0.0,
        description: str = "",
    ):
        self.confused = confused
        self.hesitant = hesitant
        self.frustrated = frustrated
        self.focused = focused
        self.confidence = confidence
        self.description = description
        self.timestamp = time.time()

    def needs_intervention(self) -> bool:
        """Determine if TARS should intervene based on detected state"""
        # Intervene if user shows signs of confusion, hesitation, or frustration
        return self.confused or self.hesitant or self.frustrated

    def __repr__(self):
        states = []
        if self.confused: states.append("confused")
        if self.hesitant: states.append("hesitant")
        if self.frustrated: states.append("frustrated")
        if self.focused: states.append("focused")
        return f"EmotionalState({', '.join(states) if states else 'neutral'}, confidence={self.confidence:.2f})"


class EmotionalStateMonitor(FrameProcessor):
    """
    Continuously monitors video feed for emotional and cognitive states.
    Analyzes facial expressions, body language, and behavior patterns to detect:
    - Confusion (furrowed brow, head tilt, puzzled expression)
    - Hesitation (pauses, uncertain gestures, looking away)
    - Frustration (tense posture, sighs, agitated movements)
    - Focus (engaged eye contact, attentive posture)

    Triggers TARS intervention when negative states are detected.
    """

    def __init__(
        self,
        vision_client,
        model: str = "moondream",
        sampling_interval: float = 3.0,
        intervention_threshold: int = 2,
        enabled: bool = True,
        auto_intervene: bool = False,
    ):
        """
        Args:
            vision_client: Moondream or compatible vision API client
            model: Vision model to use
            sampling_interval: Seconds between frame analyses (default: 3.0)
            intervention_threshold: Number of consecutive negative states before intervening
            enabled: Whether monitoring is active
            auto_intervene: If True, automatically triggers LLM when threshold reached.
                           If False, only tracks state (used by gating layer)
        """
        super().__init__()
        self._vision_client = vision_client
        self._model = model
        self._sampling_interval = sampling_interval
        self._intervention_threshold = intervention_threshold
        self._enabled = enabled
        self._auto_intervene = auto_intervene

        # State tracking
        self._last_sample_time = 0
        self._last_state: Optional[EmotionalState] = None
        self._state_history: List[EmotionalState] = []
        self._consecutive_negative_states = 0
        self._analyzing = False

        # Cooldown tracking (when user declines help)
        self._help_declined_time: Optional[float] = None
        self._cooldown_duration = 30.0  # seconds - don't re-offer help for 30s after decline

        logger.info(f"🧠 Emotional State Monitor initialized")
        logger.info(f"   Sampling interval: {sampling_interval}s")
        logger.info(f"   Intervention threshold: {intervention_threshold}")
        logger.info(f"   Auto-intervene: {auto_intervene}")
        logger.info(f"   Enabled: {enabled}")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process video frames and sample periodically for emotional analysis"""
        await super().process_frame(frame, direction)

        # Only analyze if enabled and frame is video input
        if not self._enabled or not isinstance(frame, ImageRawFrame):
            await self.push_frame(frame, direction)
            return

        # Check if it's time to sample
        current_time = time.time()
        if current_time - self._last_sample_time >= self._sampling_interval:
            # Don't block the pipeline - analyze in background
            if not self._analyzing:
                self._last_sample_time = current_time
                asyncio.create_task(self._analyze_emotional_state(frame))

        await self.push_frame(frame, direction)

    async def _analyze_emotional_state(self, frame: ImageRawFrame):
        """Analyze frame for emotional/cognitive state"""
        self._analyzing = True

        try:
            # Convert frame to base64
            image = Image.frombytes(frame.format, frame.size, frame.image)
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode()

            # Construct emotion detection prompt
            prompt = (
                "Analyze the person's emotional and cognitive state. "
                "Are they showing signs of: confusion (furrowed brow, puzzled expression), "
                "hesitation (pauses, uncertain gestures), frustration (tense posture), "
                "or focus (engaged, attentive)? "
                "Respond concisely with detected states."
            )

            logger.debug(f"🔍 Analyzing emotional state...")

            try:
                response = await asyncio.wait_for(
                    self._vision_client.chat.completions.create(
                        model=self._model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/jpeg;base64,{img_str}"
                                        },
                                    },
                                ],
                            }
                        ],
                        max_tokens=100,
                    ),
                    timeout=5.0,
                )

                description = response.choices[0].message.content.lower()
                logger.debug(f"📊 Emotional analysis: {description}")

                # Parse response to detect states
                state = EmotionalState(
                    confused="confus" in description or "puzzle" in description or "uncertain" in description,
                    hesitant="hesita" in description or "unsure" in description or "pause" in description,
                    frustrated="frustrat" in description or "tense" in description or "agitat" in description,
                    focused="focus" in description or "attentive" in description or "engaged" in description,
                    confidence=0.7,  # Could be enhanced with more sophisticated parsing
                    description=description,
                )

                self._last_state = state
                self._state_history.append(state)

                # Keep only recent history (last 10 states)
                if len(self._state_history) > 10:
                    self._state_history.pop(0)

                logger.info(f"🎭 State detected: {state}")

                # Track consecutive negative states
                if state.needs_intervention():
                    self._consecutive_negative_states += 1
                    logger.warning(
                        f"⚠️ Negative state detected "
                        f"({self._consecutive_negative_states}/{self._intervention_threshold})"
                    )
                else:
                    self._consecutive_negative_states = 0

                # Trigger intervention if threshold reached AND auto-intervene enabled
                if self._auto_intervene and self._consecutive_negative_states >= self._intervention_threshold:
                    await self._trigger_intervention(state)
                    self._consecutive_negative_states = 0  # Reset after intervention
                elif self._consecutive_negative_states >= self._intervention_threshold:
                    # Just log, don't intervene (gating layer will handle it)
                    logger.info(
                        f"🎭 Intervention threshold reached ({self._consecutive_negative_states}) "
                        f"- state available for gating layer"
                    )

            except asyncio.TimeoutError:
                logger.warning("⚠️ Emotional analysis timed out")
            except Exception as e:
                logger.error(f"❌ Emotional analysis error: {e}")

        except Exception as e:
            logger.error(f"Error in emotional monitoring: {e}")
        finally:
            self._analyzing = False

    async def _trigger_intervention(self, state: EmotionalState):
        """Trigger TARS intervention based on detected emotional state"""
        logger.info(f"🚨 Triggering TARS intervention for: {state}")

        # Construct intervention message based on state
        intervention_msg = self._get_intervention_message(state)

        # Push context message to LLM
        context_frame = TextFrame(
            text=f"[Emotional State Alert]: {intervention_msg}"
        )
        await self.push_frame(context_frame, FrameDirection.UPSTREAM)

        # Trigger LLM to respond
        await self.push_frame(LLMRunFrame(), FrameDirection.UPSTREAM)

        logger.info("✅ Intervention triggered")

    def _get_intervention_message(self, state: EmotionalState) -> str:
        """Generate appropriate intervention message based on detected state"""
        if state.confused:
            return (
                "The user appears confused or uncertain. "
                "Consider offering help or clarification proactively."
            )
        elif state.hesitant:
            return (
                "The user seems hesitant or unsure. "
                "You might want to check if they need assistance."
            )
        elif state.frustrated:
            return (
                "The user appears frustrated or tense. "
                "Consider offering support or suggesting a different approach."
            )
        else:
            return (
                "The user shows signs of difficulty. "
                "Consider offering assistance."
            )

    def enable(self):
        """Enable emotional monitoring"""
        self._enabled = True
        logger.info("🧠 Emotional monitoring enabled")

    def disable(self):
        """Disable emotional monitoring"""
        self._enabled = False
        logger.info("🧠 Emotional monitoring disabled")

    def get_current_state(self) -> Optional[EmotionalState]:
        """Get the most recent emotional state"""
        return self._last_state

    def get_state_summary(self) -> Dict:
        """Get summary of recent emotional states"""
        if not self._state_history:
            return {"status": "no_data"}

        total = len(self._state_history)
        confused_count = sum(1 for s in self._state_history if s.confused)
        hesitant_count = sum(1 for s in self._state_history if s.hesitant)
        frustrated_count = sum(1 for s in self._state_history if s.frustrated)
        focused_count = sum(1 for s in self._state_history if s.focused)

        return {
            "total_samples": total,
            "confused_ratio": confused_count / total,
            "hesitant_ratio": hesitant_count / total,
            "frustrated_ratio": frustrated_count / total,
            "focused_ratio": focused_count / total,
            "current_state": str(self._last_state) if self._last_state else "unknown",
        }
