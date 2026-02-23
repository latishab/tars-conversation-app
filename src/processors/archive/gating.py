"""Intervention Gating: Traffic Controller for Bot Responses."""

import json
import time
import aiohttp
import asyncio
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import LLMMessagesFrame, Frame
from character.prompts import build_gating_system_prompt

class InterventionGating(FrameProcessor):
    """
    Traffic Controller: Decides if TARS should reply based on Audio + Vision + Emotions.
    Uses OpenAI-compatible API (DeepInfra).
    """
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepinfra.com/v1/openai",
        model: str = "meta-llama/Llama-3.2-3B-Instruct",
        visual_observer=None,
        emotional_monitor=None
    ):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.visual_observer = visual_observer
        self.emotional_monitor = emotional_monitor
        self.api_url = f"{base_url}/chat/completions"

    async def _check_should_reply(self, messages: list) -> bool:
        """Asks the fast LLM if we should reply (Audio + Vision + Emotions)."""
        if not messages:
            return False

        # Extract the last user message
        last_msg = messages[-1]
        if last_msg.get("role") != "user":
            return True

        # 1. READ EMOTIONAL STATE (Highest Priority)
        emotional_state = None
        needs_help = False
        if self.emotional_monitor:
            emotional_state = self.emotional_monitor.get_current_state()
            if emotional_state and emotional_state.needs_intervention():
                # User is confused/hesitant/frustrated - ALWAYS respond
                logger.info(
                    f"🧠 Gating: User shows {emotional_state} - BYPASSING gating, offering help"
                )
                return True
            needs_help = emotional_state.needs_intervention() if emotional_state else False

        # 2. READ VISUAL CONTEXT (0ms Latency)
        is_looking = False
        if self.visual_observer:
            # Read the variable updated by the background task
            is_looking = self.visual_observer.visual_context.get("is_looking_at_robot", False)

            # Ignore if data is too old (> 5 seconds)
            last_update = self.visual_observer.visual_context.get("last_updated", 0)
            if time.time() - last_update > 5.0:
                is_looking = False

        # 3. ANALYZE CONTEXT
        history_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-3:]])

        # Build enriched system prompt with emotional context
        system_prompt = build_gating_system_prompt(is_looking, emotional_state)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{history_text}"}
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 50
        }

        # Set strict timeout so we don't silence the bot if API is slow
        timeout = aiohttp.ClientTimeout(total=1.5)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.api_url, 
                    headers={"Authorization": f"Bearer {self.api_key}"}, 
                    json=payload
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        content_response = result["choices"][0]["message"]["content"]
                        content_response = content_response.replace("```json", "").replace("```", "").strip()
                        data = json.loads(content_response)
                        should_reply = data.get("reply", False)
                        
                        logger.debug(f"Gating decision: {should_reply} (Looking: {is_looking})")
                        return should_reply
                    else:
                        logger.warning(f"Gating check failed: {resp.status}")
                        return True # Fail open (reply if check fails)
        except asyncio.TimeoutError:
            logger.warning("🚦 Gating: Timed out! Defaulting to REPLY.")
            return True
        except Exception as e:
            logger.error(f"Gating error: {e}")
            return True

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """
        Intercepts LLMMessagesFrame. 
        If 'should_reply' is False, we DROP the frame, effectively silencing the bot.
        """
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMMessagesFrame) and direction == FrameDirection.DOWNSTREAM:
            # Check if we should reply
            should_reply = await self._check_should_reply(frame.messages)
            
            if not should_reply:
                logger.info(f"🚦 Gating: BLOCKING response.")
                return # DROP THE FRAME
            
            logger.info(f"🟢 Gating: PASSING through.")
        
        await self.push_frame(frame, direction)