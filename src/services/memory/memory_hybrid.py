"""
Hybrid memory system optimized for voice AI with sub-50ms latency.

Features:
1. Hybrid search combining vector similarity (70%) and BM25 keyword matching (30%)
2. SQLite + FTS5 for fast, local storage and search
3. Query embedding cache to avoid redundant encoding
4. Pre-warmed embedding model for consistent latency
5. Strict timeout with graceful fallback
6. Thread pool for non-blocking SQLite operations
7. Fire-and-forget storage to prevent blocking

Architecture:
- Vector search for semantic similarity (cosine distance)
- BM25 via FTS5 for exact keyword matching
- Weighted score fusion for best of both worlds
- Target latency: <50ms (vs ChromaDB's ~50-100ms)
"""

import asyncio
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, List, Tuple
import numpy as np

from loguru import logger
from pipecat.frames.frames import Frame, LLMMessagesFrame, LLMContextFrame, MetricsFrame
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContextFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from sentence_transformers import SentenceTransformer


class HybridMemoryService(FrameProcessor):
    """
    Hybrid memory service combining vector similarity and keyword search.

    Target latency: <50ms

    Architecture:
    - Vector search via numpy (semantic similarity with cosine distance)
    - BM25 via FTS5 (exact keyword matching)
    - Weighted score fusion: 70% vector + 30% BM25

    Voice AI optimizations:
    - Query embedding cache (avoid re-encoding similar queries)
    - Pre-warmed embedding model for consistent performance
    - Thread pool for non-blocking SQLite operations
    - Strict timeout with graceful fallback
    - Fire-and-forget storage to prevent blocking
    """

    def __init__(
        self,
        user_id: str,
        db_path: str = "./memory_data/memory.sqlite",
        embedding_model: str = "all-MiniLM-L6-v2",
        search_limit: int = 3,
        search_timeout_ms: int = 40,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        system_prompt_prefix: str = "From our conversations:\n",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.db_path = db_path
        self.search_limit = search_limit
        self.search_timeout_ms = search_timeout_ms
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.system_prompt_prefix = system_prompt_prefix

        # Thread pool for blocking operations
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="HybridMemory")

        # Initialize SQLite with FTS5 and vector support
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()

        # Load and warm embedding model
        logger.info("Loading embedding model for hybrid memory...")
        self.embedder = SentenceTransformer(embedding_model)
        self._embedding_dim = self.embedder.get_sentence_embedding_dimension()
        self._warmup_model()

        # Embedding caches
        self._query_cache: dict[str, np.ndarray] = {}  # For queries
        self._doc_cache: dict[str, np.ndarray] = {}    # For documents
        self._cache_max_size = 500

        # Metrics
        self._stats = {"searches": 0, "cache_hits": 0, "timeouts": 0, "total_latency_ms": 0}
        self._frame_count = 0

        logger.info(f"✓ Hybrid memory ready (vector + BM25, {search_timeout_ms}ms timeout)")

    def _init_database(self):
        """Initialize SQLite with FTS5 and vector table."""
        conn = sqlite3.connect(self.db_path)

        # Main memories table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,
                created_at REAL DEFAULT (unixepoch('now', 'subsec'))
            )
        """)

        # FTS5 virtual table for BM25 keyword search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(content, content='memories', content_rowid='id')
        """)

        # Triggers to keep FTS in sync
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                DELETE FROM memories_fts WHERE rowid = old.id;
            END
        """)

        # Index for user filtering
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON memories(user_id)")

        conn.commit()
        conn.close()
        logger.info("✓ SQLite database initialized with FTS5")

    def _warmup_model(self):
        """Warm up embedding model for consistent latency."""
        warmup_start = time.perf_counter()
        for _ in range(3):
            _ = self.embedder.encode("warmup query", show_progress_bar=False)
        warmup_time = (time.perf_counter() - warmup_start) * 1000
        logger.info(f"✓ Embedding model warmed up ({warmup_time:.0f}ms)")

    def _get_query_embedding(self, text: str) -> np.ndarray:
        """Get embedding with query cache."""
        cache_key = text.strip().lower()[:100]

        if cache_key in self._query_cache:
            self._stats["cache_hits"] += 1
            return self._query_cache[cache_key]

        embedding = self.embedder.encode(text, show_progress_bar=False)

        # LRU eviction
        if len(self._query_cache) >= self._cache_max_size:
            oldest = next(iter(self._query_cache))
            del self._query_cache[oldest]

        self._query_cache[cache_key] = embedding
        return embedding

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Fast cosine similarity."""
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))

    def _bm25_rank_to_score(self, rank: int) -> float:
        """Convert BM25 rank to normalized score."""
        return 1.0 / (1.0 + max(0, rank))

    def _hybrid_search_sync(self, query: str) -> List[Tuple[str, float]]:
        """
        Hybrid search combining vector similarity and BM25 keyword matching.
        Returns [(content, score), ...] sorted by score.
        """
        conn = sqlite3.connect(self.db_path)

        # Get query embedding
        query_embedding = self._get_query_embedding(query)

        # ========== Vector Search ==========
        vector_results = {}
        cursor = conn.execute(
            "SELECT id, content, embedding FROM memories WHERE user_id = ? ORDER BY created_at DESC LIMIT 100",
            (self.user_id,)
        )

        for row_id, content, embedding_blob in cursor:
            if embedding_blob:
                doc_embedding = np.frombuffer(embedding_blob, dtype=np.float32)
                similarity = self._cosine_similarity(query_embedding, doc_embedding)
                vector_results[row_id] = {
                    "content": content,
                    "vector_score": similarity,
                    "bm25_score": 0.0,
                }

        # ========== BM25 Search (FTS5) ==========
        # Build FTS query using OR for flexible token matching
        tokens = [t for t in query.split() if len(t) > 2]
        if tokens:
            # Use OR for more flexible matching
            fts_query = " OR ".join(f'"{t}"' for t in tokens[:5])  # Limit tokens
            try:
                bm25_cursor = conn.execute(
                    """
                    SELECT rowid, rank FROM memories_fts
                    WHERE memories_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, self.search_limit * 4)
                )

                for rank_idx, (row_id, bm25_rank) in enumerate(bm25_cursor):
                    bm25_score = self._bm25_rank_to_score(rank_idx)
                    if row_id in vector_results:
                        vector_results[row_id]["bm25_score"] = bm25_score
                    else:
                        # BM25 found something vector didn't
                        content_cursor = conn.execute(
                            "SELECT content FROM memories WHERE id = ?", (row_id,)
                        )
                        row = content_cursor.fetchone()
                        if row:
                            vector_results[row_id] = {
                                "content": row[0],
                                "vector_score": 0.0,
                                "bm25_score": bm25_score,
                            }
            except sqlite3.OperationalError as e:
                # FTS query failed, continue with vector only
                logger.debug(f"FTS query failed: {e}")
                pass

        conn.close()

        # ========== Weighted Score Fusion ==========
        results = []
        for data in vector_results.values():
            final_score = (
                self.vector_weight * data["vector_score"] +
                self.bm25_weight * data["bm25_score"]
            )
            results.append((data["content"], final_score))

        # Sort by score, return top N
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:self.search_limit]

    def _store_sync(self, text: str):
        """Store memory with embedding."""
        embedding = self.embedder.encode(text, show_progress_bar=False)
        embedding_blob = embedding.astype(np.float32).tobytes()

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO memories (user_id, content, embedding) VALUES (?, ?, ?)",
            (self.user_id, text, embedding_blob)
        )
        conn.commit()
        conn.close()

    async def _search_with_timeout(self, query: str) -> List[Tuple[str, float]]:
        """Async search with strict timeout."""
        loop = asyncio.get_event_loop()

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._hybrid_search_sync, query),
                timeout=self.search_timeout_ms / 1000,
            )
            return result
        except asyncio.TimeoutError:
            self._stats["timeouts"] += 1
            logger.warning(f"⏱️  Memory search timed out ({self.search_timeout_ms}ms)")
            return []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process Pipecat frames with hybrid memory injection."""
        await super().process_frame(frame, direction)

        try:
            self._frame_count += 1

            # Debug: Log all frame types to understand what's flowing through
            frame_type = type(frame).__name__
            direction_name = "DOWNSTREAM" if direction == FrameDirection.DOWNSTREAM else "UPSTREAM"

            # Log LLM-related frames to debug
            if 'LLM' in frame_type or 'Messages' in frame_type or 'Context' in frame_type:
                logger.info(f"🔍 [HybridMemory] >>> RECEIVED: {frame_type} | Direction: {direction_name} | Count: {self._frame_count}")

            context = None
            messages = None

            if isinstance(frame, (LLMContextFrame, OpenAILLMContextFrame)):
                logger.info(f"🧠 [HybridMemory] ✓✓✓ PROCESSING LLMContextFrame ✓✓✓")
                context = frame.context
            elif isinstance(frame, LLMMessagesFrame):
                logger.info(f"🧠 [HybridMemory] ✓✓✓ PROCESSING LLMMessagesFrame ✓✓✓")
                messages = frame.messages
                context = LLMContext(messages)

            if context:
                # Extract user message
                user_message = None
                for msg in reversed(context.get_messages()):
                    if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                        user_message = msg["content"]
                        break

                if user_message:
                    self._stats["searches"] += 1
                    start_time = time.perf_counter()

                    logger.info(f"🔍 [HybridMemory] Searching for: '{user_message[:50]}...'")

                    # Hybrid search with timeout
                    results = await self._search_with_timeout(user_message)

                    latency_ms = (time.perf_counter() - start_time) * 1000
                    self._stats["total_latency_ms"] += latency_ms

                    # Emit metrics
                    await self.push_frame(
                        MetricsFrame(data=[
                            TTFBMetricsData(processor="HybridMemory", value=latency_ms / 1000)
                        ]),
                        direction,
                    )

                    # Inject memories
                    if results:
                        memories_text = self.system_prompt_prefix + "\n".join(
                            f"- {content}" for content, score in results
                        )
                        context.add_message({"role": "system", "content": memories_text})

                        cache_rate = self._stats["cache_hits"] / max(1, self._stats["searches"]) * 100
                        avg_latency = self._stats["total_latency_ms"] / max(1, self._stats["searches"])
                        logger.info(
                            f"📚 [HybridMemory] {len(results)} memories ({latency_ms:.0f}ms, "
                            f"avg: {avg_latency:.0f}ms, cache: {cache_rate:.0f}%)"
                        )
                    else:
                        logger.info(f"📚 [HybridMemory] No relevant memories ({latency_ms:.0f}ms)")

                    # Fire-and-forget storage
                    asyncio.create_task(self._store_async(user_message))

                # Push frame
                if messages is not None:
                    await self.push_frame(LLMMessagesFrame(context.get_messages()), direction)
                else:
                    await self.push_frame(frame, direction)
            else:
                await self.push_frame(frame, direction)

        except Exception as e:
            logger.error(f"❌ [HybridMemory] Memory error: {e}", exc_info=True)
            await self.push_frame(frame, direction)

    async def _store_async(self, text: str):
        """Async storage (fire-and-forget)."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(self._executor, self._store_sync, text)
            logger.debug(f"💾 [HybridMemory] Stored: {text[:50]}...")
        except Exception as e:
            logger.debug(f"[HybridMemory] Store failed: {e}")

    def get_stats(self) -> dict:
        """Get performance statistics."""
        searches = max(1, self._stats["searches"])
        return {
            "searches": self._stats["searches"],
            "cache_hits": self._stats["cache_hits"],
            "cache_hit_rate": f"{(self._stats['cache_hits'] / searches) * 100:.1f}%",
            "timeouts": self._stats["timeouts"],
            "avg_latency_ms": f"{self._stats['total_latency_ms'] / searches:.1f}",
        }

    async def close(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=False)
        stats = self.get_stats()
        logger.info(f"📊 [HybridMemory] Final stats: {stats}")
