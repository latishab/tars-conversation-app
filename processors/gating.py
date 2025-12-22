"""Intervention Gating: Traffic Controller for Bot Responses."""

import json
import aiohttp
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import LLMMessagesFrame, Frame


class InterventionGating(FrameProcessor):
    """
    Traffic Controller: Decides if the bot should reply or stay silent.
    """
    def __init__(self, api_key: str, model: str = "Qwen/Qwen2.5-7B-Instruct"):
        super().__init__()
        self.api_key = api_key
        self.model = model 
        self.api_url = "https://api.deepinfra.com/v1/openai/chat/completions"

    async def _check_should_reply(self, messages: list) -> bool:
        """Asks the fast LLM if we should reply."""
        if not messages:
            return False

        # Extract the last user message
        last_msg = messages[-1]
        if last_msg.get("role") != "user":
            # If the last message wasn't from the user (e.g. system injection), let it pass.
            return True 

        content = last_msg.get("content", "")
        
        # The 'Fast' System Prompt - Speaker-aware for multi-party conversations
        system_prompt = (
            "You are a conversational traffic controller for a bot named TARS. "
            "Analyze the last user message. "
            "The input may contain speaker labels like 'Speaker 1:' or 'Speaker 2:'. "
            "Output JSON: {\"reply\": true} ONLY if:\n"
            "1. The user explicitly addresses 'TARS', 'Bot', 'Computer', or 'AI'.\n"
            "2. The context clearly implies a question or command directed at the AI.\n"
            "3. The user is asking for help, information, or assistance.\n"
            "Output JSON: {\"reply\": false} if:\n"
            "- Users are talking to each other (e.g., 'Speaker 2: Yes, I agree').\n"
            "- The user is thinking out loud, mumbling, or self-correcting.\n"
            "- The user is pausing (e.g., 'Umm...', 'Let me see...', 'Wait').\n"
            "- The conversation is clearly between humans, not directed at TARS.\n"
            "Be conservative. If unsure or if it's inter-human conversation, output false."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User message: '{content}'"}
            ],
            "response_format": {"type": "json_object"}
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
                        logger.debug(f"Gating decision for message: '{content[:50]}...' -> reply={should_reply}")
                        
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

