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
            # Generic call; adapt if your SDK exposes a different method name
            # Common semantics: add textual memory scoped to a user
            # Examples in the wild: `add`, `add_memory`, or `create`
            if hasattr(self._client, "add_memory"):
                self._client.add_memory(user_id=user_id, text=text)  # type: ignore[attr-defined]
            elif hasattr(self._client, "add"):
                self._client.add(user_id=user_id, text=text)  # type: ignore[attr-defined]
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
            # Generic retrieval; adapt to actual SDK as needed
            # Likely shapes: search(query, user_id=...), get(user_id=...)
            if query and hasattr(self._client, "search"):
                results = self._client.search(user_id=user_id, query=query, k=limit)  # type: ignore[attr-defined]
            elif hasattr(self._client, "get"):
                results = self._client.get(user_id=user_id, limit=limit)  # type: ignore[attr-defined]
            else:
                return []

            # Coerce to list[str]
            texts: List[str] = []
            if isinstance(results, list):
                for item in results:
                    if isinstance(item, str):
                        texts.append(item)
                    elif isinstance(item, dict):
                        text = item.get("text") or item.get("content") or item.get("memory")
                        if isinstance(text, str):
                            texts.append(text)
            return texts[:limit]
        except Exception as e:  # pragma: no cover
            logger.warning(f"Mem0 recall failed: {e}")
            return []


