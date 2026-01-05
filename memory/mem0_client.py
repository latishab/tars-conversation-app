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

    def save_user_message(self, user_id: str, text: str) -> Optional[List[str]]:
        """Save user message and return extracted memories from the response.

        Returns:
            List of memory strings extracted from the save response, or None if no memories.
        """
        if not self._client:
            logger.debug("Mem0 client not available, skipping save")
            return None
        try:
            logger.debug(f"Saving message to Mem0 for user '{user_id}': {text[:50]}...")
            messages = [{"role": "user", "content": text}]
            result = None

            if hasattr(self._client, "add_memory"):
                result = self._client.add_memory(user_id=user_id, text=text)
                logger.info(f"✓ Saved to Mem0 (add_memory) for '{user_id}'")
                logger.debug(f"Mem0 response type: {type(result)}")
                logger.debug(f"Mem0 response: {result}")
            elif hasattr(self._client, "add"):
                result = self._client.add(messages, user_id=user_id)
                logger.info(f"✓ Saved to Mem0 (add) for '{user_id}'")
                logger.debug(f"Mem0 response type: {type(result)}")
                logger.debug(f"Mem0 response: {result}")
            elif hasattr(self._client, "create"):
                result = self._client.create(user_id=user_id, text=text)
                logger.info(f"✓ Saved to Mem0 (create) for '{user_id}'")
                logger.debug(f"Mem0 response type: {type(result)}")
                logger.debug(f"Mem0 response: {result}")
            else:
                logger.warning(f"⚠️  Mem0 client has no save method available")
                return None

            # Extract new memories from the API response
            return self._extract_memories_from_result(result)

        except Exception as e:
            logger.warning(f"❌ Mem0 save_user_message failed: {e}")
            return None

    def _extract_memories_from_result(self, result) -> Optional[List[str]]:
        """Extract memory strings from Mem0 API response."""
        if not result:
            return None

        try:
            memories = []

            # Handle dict response
            if isinstance(result, dict):
                # Check for 'results' array 
                if 'results' in result and isinstance(result['results'], list):
                    for item in result['results']:
                        if isinstance(item, dict) and 'memory' in item:
                            memories.append(str(item['memory']))

                # Check for direct memory field
                elif 'memory' in result:
                    memories.append(str(result['memory']))

            # Handle list response
            elif isinstance(result, list):
                for item in result:
                    if isinstance(item, dict) and 'memory' in item:
                        memories.append(str(item['memory']))
                    elif isinstance(item, str):
                        memories.append(item)

            if memories:
                logger.info(f"💡 Extracted {len(memories)} new memories")
                for i, mem in enumerate(memories, 1):
                    logger.debug(f"  New: {mem[:100]}...")
                return memories

            return None

        except Exception as e:
            logger.debug(f"Could not extract memories from response: {e}")
            return None

    def recall(self, user_id: str, query: Optional[str] = None, limit: int = 8) -> List[str]:
        if not self._client:
            logger.debug("Mem0 client not available, returning empty list")
            return []
        try:
            logger.debug(f"🔍 Recalling memories for user '{user_id}' (limit={limit}, query={query})")
            results = []
            if query and hasattr(self._client, "search"):
                logger.debug(f"Using search method with query: {query}")
                results = self._client.search(query, user_id=user_id, limit=limit)
            elif hasattr(self._client, "get_all"):
                logger.debug("Using get_all method")
                all_results = self._client.get_all(user_id=user_id)
                results = all_results[:limit] if isinstance(all_results, list) else []
                logger.debug(f"get_all returned {len(results)} results")
            elif hasattr(self._client, "search"):
                logger.debug("Using search method with empty query")
                results = self._client.search("", user_id=user_id, limit=limit)
            else:
                logger.warning("⚠️  Mem0 client has no recall method available")
                return []

            logger.debug(f"Raw results count: {len(results) if isinstance(results, list) else 'not a list'}")

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

            logger.info(f"📚 Recalled {len(texts)} memories for '{user_id}'")
            return texts[:limit]
        except Exception as e:
            logger.error(f"❌ Mem0 recall failed: {e}", exc_info=True)
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