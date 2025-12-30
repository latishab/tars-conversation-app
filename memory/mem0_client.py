"""Thin wrapper around Mem0 to make it optional and safe to call.

This module avoids hard-coupling to Mem0's exact API surface. If the
`mem0ai` package is not installed or the API key is missing, methods no-op.
"""

from __future__ import annotations

from typing import List, Optional

from loguru import logger

try:
    # The canonical package name is `mem0ai` (as of 2025); some versions expose `mem0` top-level
    try:
        from mem0 import MemoryClient  # type: ignore
    except Exception:  # pragma: no cover - fallback
        from mem0ai import MemoryClient  # type: ignore
except Exception as e:  # pragma: no cover - mem0 not installed
    raise ImportError("mem0ai is required. Please install it via requirements.txt.") from e


class Mem0Wrapper:
    """Safe wrapper for Mem0 memory operations.

    Mem0 is mandatory in this project; failures during initialization are fatal.
    """

    def __init__(self, api_key: str):
        if not api_key or not api_key.strip():
            raise ValueError("MEM0_API_KEY is required but missing.")
        try:
            self._client = MemoryClient(api_key=api_key)
            logger.info("✓ Mem0 initialized for long-term memory")
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Failed to initialize Mem0: {e}") from e

    @property
    def enabled(self) -> bool:
        return True

    def save_user_message(self, user_id: str, text: str) -> None:
        if not self._client:
            return
        try:
            # Mem0 API requires messages as a list of dicts with 'role' and 'content'
            messages = [{"role": "user", "content": text}]
            
            # Try different methods in order of preference
            if hasattr(self._client, "add_memory"):
                self._client.add_memory(user_id=user_id, text=text)  # type: ignore[attr-defined]
            elif hasattr(self._client, "add"):
                # add() requires messages as first positional arg, user_id in kwargs
                self._client.add(messages, user_id=user_id)  # type: ignore[attr-defined]
            elif hasattr(self._client, "create"):
                self._client.create(user_id=user_id, text=text)  # type: ignore[attr-defined]
            else:
                logger.debug("Mem0 client missing known add/create methods; skipping save")
        except Exception as e:  # pragma: no cover
            logger.warning(f"Mem0 save_user_message failed: {e}")

    def recall(self, user_id: str, query: Optional[str] = None, limit: int = 8) -> List[str]:
        if not self._client:
            return []
        try:
            results = []
            
            # Use search() if query provided, otherwise use get_all() with user_id filter
            if query and hasattr(self._client, "search"):
                # search() takes query as first arg, user_id in kwargs
                results = self._client.search(query, user_id=user_id, limit=limit)  # type: ignore[attr-defined]
            elif hasattr(self._client, "get_all"):
                # get_all() can filter by user_id in kwargs
                all_results = self._client.get_all(user_id=user_id)  # type: ignore[attr-defined]
                results = all_results[:limit] if isinstance(all_results, list) else []
            elif hasattr(self._client, "search"):
                # Fallback: search with empty query to get all memories for user
                results = self._client.search("", user_id=user_id, limit=limit)  # type: ignore[attr-defined]
            else:
                return []

            # Coerce to list[str]
            texts: List[str] = []
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict):
                        # Try different possible keys for the memory content
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
        except Exception as e:  # pragma: no cover
            logger.warning(f"Mem0 recall failed: {e}")
            return []

    def transfer_memories(self, old_user_id: str, new_user_id: str):
        """Moves memories from a temporary ID (e.g. guest) to a named ID."""
        if not self._client or old_user_id == new_user_id:
            return

        logger.info(f"🔄 Transferring memories from {old_user_id} to {new_user_id}...")
        
        # 1. Recall recent memories from the old ID
        old_memories = self.recall(user_id=old_user_id, limit=100)
        
        if not old_memories:
            logger.info("No temporary memories found to transfer.")
            return

        # 2. Add them to the new ID
        for memory_text in old_memories:
            self.save_user_message(new_user_id, memory_text)
            
        logger.info(f"✅ Successfully transferred {len(old_memories)} memories to {new_user_id}")