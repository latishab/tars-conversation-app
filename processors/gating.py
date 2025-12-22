"""Intervention Gating: Traffic Controller for Bot Responses."""

import json
import time
import aiohttp
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import LLMMessagesFrame, Frame
from character.prompts import build_gating_system_prompt


class InterventionGating(FrameProcessor):
    """
    Traffic Controller: Decides if TARS should reply based on Audio + Vision.
    Uses OpenAI-compatible API (DeepInfra).
    """
    def __init__(
        self, 
        api_key: str, 
        base_url: str = "https://api.deepinfra.com/v1/openai",
        model: str = "meta-llama/Llama-3.2-3B-Instruct",
        visual_observer=None
    ):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model 
        self.visual_observer = visual_observer
        self.api_url = f"{base_url}/chat/completions"

    async def _check_should_reply(self, messages: list) -> bool:
        """Asks the fast LLM if we should reply (Audio + Vision)."""
        if not messages:
            return False

        # Extract the last user message
        last_msg = messages[-1]
        if last_msg.get("role") != "user":
            return True 

        # 1. READ VISUAL CONTEXT (0ms Latency)
        is_looking = False
        if self.visual_observer:
            # Read the variable updated by the background task
            is_looking = self.visual_observer.visual_context.get("is_looking_at_robot", False)
            
            # Ignore if data is too old (> 5 seconds)
            last_update = self.visual_observer.visual_context.get("last_updated", 0)
            if time.time() - last_update > 5.0:
                is_looking = False 

        # 2. ANALYZE CONTEXT (Use last 3 messages to detect struggle)
        # We grab a bit more context to see if they are stuck
        history_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-3:]])
        
        # Get the collaborative spotter system prompt from prompts.py
        system_prompt = build_gating_system_prompt(is_looking)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Context:\n{history_text}"}
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": 50
        }

        try:
            async with aiohttp.ClientSession() as session:
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
                        
                        # Log the decision for debugging
                        logger.debug(f"Gating decision: {should_reply} (Looking: {is_looking})")
                        
                        return should_reply
                    else:
                        logger.warning(f"Gating check failed: {resp.status}")
                        return True # Fail open (reply if check fails)
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
            # Extract last user message for logging
            last_msg = ""
            if frame.messages:
                last_user_msg = frame.messages[-1]
                if last_user_msg.get("role") == "user":
                    last_msg = last_user_msg.get("content", "")[:60]
            
            # Check if we should reply
            should_reply = await self._check_should_reply(frame.messages)
            
            if not should_reply:
                logger.info(f"🚦 Gating: BLOCKING response | Message: '{last_msg}...'")
                return # DROP THE FRAME. Pipeline stops here for this turn.
            
            logger.info(f"🟢 Gating: PASSING through | Message: '{last_msg}...'")
        
        # Push the frame if we didn't return above
        await self.push_frame(frame, direction)

