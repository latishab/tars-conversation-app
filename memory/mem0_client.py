"""Thin wrapper around Mem0 and Pipecat processor for memory saving."""

from __future__ import annotations

import asyncio
from typing import List, Optional
from loguru import logger

# Pipeline imports
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import TranscriptionFrame, Frame

try:
    try:
        from mem0 import MemoryClient  # type: ignore
    except Exception:  # pragma: no cover - fallback
        from mem0ai import MemoryClient  # type: ignore
except Exception as e:  # pragma: no cover - mem0 not installed
    raise ImportError("mem0ai is required. Please install it via requirements.txt.") from e


class Mem0Wrapper:
    """Safe wrapper for Mem0 memory operations."""

    def __init__(self, api_key: str):
        if not api_key or not api_key.strip():
            raise ValueError("MEM0_API_KEY is required but missing.")
        try:
            self._client = MemoryClient(api_key=api_key)
            logger.info("✓ Mem0 initialized for long-term memory")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Mem0: {e}") from e

    @property
    def enabled(self) -> bool:
        return True

    def save_user_message(self, user_id: str, text: str) -> None:
        if not self._client:
            return
        try:
            messages = [{"role": "user", "content": text}]
            if hasattr(self._client, "add_memory"):
                self._client.add_memory(user_id=user_id, text=text)
            elif hasattr(self._client, "add"):
                self._client.add(messages, user_id=user_id)
            elif hasattr(self._client, "create"):
                self._client.create(user_id=user_id, text=text)
        except Exception as e:
            logger.warning(f"Mem0 save_user_message failed: {e}")

    def recall(self, user_id: str, query: Optional[str] = None, limit: int = 8) -> List[str]:
        if not self._client:
            return []
        try:
            results = []
            if query and hasattr(self._client, "search"):
                results = self._client.search(query, user_id=user_id, limit=limit)
            elif hasattr(self._client, "get_all"):
                all_results = self._client.get_all(user_id=user_id)
                results = all_results[:limit] if isinstance(all_results, list) else []
            elif hasattr(self._client, "search"):
                results = self._client.search("", user_id=user_id, limit=limit)
            else:
                return []

            texts: List[str] = []
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict):
                        text = (
                            item.get("text") 
                            or item.get("content") 
                            or item.get("memory")
                            or item.get("message")
                            or (item.get("messages", [{}])[0].get("content") if isinstance(item.get("messages"), list) else None)
                        )
                        if isinstance(text, str):
                            texts.append(text)
            return texts[:limit]
        except Exception as e:
            logger.warning(f"Mem0 recall failed: {e}")
            return []

    def transfer_memories(self, old_user_id: str, new_user_id: str):
        if not self._client or old_user_id == new_user_id:
            return
        logger.info(f"🔄 Transferring memories from {old_user_id} to {new_user_id}...")
        old_memories = self.recall(user_id=old_user_id, limit=100)
        if not old_memories:
            logger.info("No temporary memories found to transfer.")
            return
        for memory_text in old_memories:
            self.save_user_message(new_user_id, memory_text)
        logger.info(f"✅ Successfully transferred {len(old_memories)} memories to {new_user_id}")


class Mem0Saver(FrameProcessor):
    """
    Pipeline processor that saves user transcriptions to Mem0.
    """
    def __init__(self, mem0_wrapper: Mem0Wrapper, client_state_ref: dict):
        # CRITICAL: This call initializes the internal queues of FrameProcessor
        super().__init__()
        self._mem0 = mem0_wrapper
        self._client_state = client_state_ref 

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # 1. Forward frame downstream immediately (Non-blocking)
        await super().process_frame(frame, direction)

        # 2. Inspect for Transcription (Side effect)
        try:
            if isinstance(frame, TranscriptionFrame) and direction == FrameDirection.UPSTREAM:
                text = frame.text
                user_id = self._client_state.get("client_id", "unknown_guest")
                
                # Filter out empty noise
                if text and len(text.strip()) > 1:
                    # Save in background task
                    asyncio.create_task(self._save_safe(user_id, text))
        except Exception as e:
            # Swallow errors here so we never crash the pipeline flow
            logger.error(f"Mem0Saver logic error: {e}")

    async def _save_safe(self, user_id, text):
        try:
            await asyncio.to_thread(self._mem0.save_user_message, user_id, text)
            logger.debug(f"💾 Saved to Mem0 [{user_id}]: {text}")
        except Exception as e:
            logger.error(f"Failed to save memory for {user_id}: {e}")