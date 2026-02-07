"""Local memory service using ChromaDB for semantic search."""

import time
from loguru import logger
from pipecat.frames.frames import Frame, LLMMessagesFrame, MetricsFrame
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from sentence_transformers import SentenceTransformer
import chromadb


class ChromaDBMemoryService(FrameProcessor):
    """
    Local memory service using ChromaDB for semantic search.

    Replaces Mem0 with a local, fast, and free alternative:
    - Stores conversation history with semantic embeddings
    - Retrieves relevant memories based on similarity search
    - No external API calls - everything runs locally
    - Latency: ~50-100ms vs Mem0's ~200-500ms
    """

    def __init__(
        self,
        user_id: str,
        agent_id: str = "tars_agent",
        collection_name: str = "conversations",
        search_limit: int = 5,
        search_threshold: float = 0.5,
        system_prompt_prefix: str = "Based on previous conversations, I recall:\n\n",
        **kwargs
    ):
        super().__init__(**kwargs)
        self.user_id = user_id
        self.agent_id = agent_id
        self.search_limit = search_limit
        self.search_threshold = search_threshold
        self.system_prompt_prefix = system_prompt_prefix

        # Initialize ChromaDB (persistent local storage)
        self.client = chromadb.PersistentClient(path="./chroma_memory")

        # Create or get collection for this user
        self.collection = self.client.get_or_create_collection(
            name=f"{collection_name}_{user_id}",
            metadata={"agent_id": agent_id}
        )

        # Load embedding model (lightweight, ~80MB)
        logger.info("Loading sentence transformer model...")
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')

        # Frame counter for debugging
        self._frame_count = 0

        logger.info("✓ ChromaDB memory service initialized and ready to process frames")

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Process frames and inject memories into LLM context."""
        try:
            await super().process_frame(frame, direction)

            # Frame counter
            self._frame_count += 1

            # Debug: Log all frame types to understand what's flowing through
            frame_type = type(frame).__name__

            # Log every 50th frame to verify it's being called
            if self._frame_count % 50 == 0:
                logger.info(f"🔍 [ChromaDB] Processed {self._frame_count} frames so far (latest: {frame_type})")

            if frame_type == 'LLMMessagesFrame':  # Only log the frame type we care about
                logger.info(f"🧠 [ChromaDB] ✓✓✓ Received {frame_type} ✓✓✓")

            if isinstance(frame, LLMMessagesFrame):
                logger.info(f"🧠 [ChromaDB] ✓ Processing LLMMessagesFrame")
                # Get the last user message
                messages = frame.messages
                user_message = None
                for msg in reversed(messages):
                    if msg.get("role") == "user":
                        user_message = msg.get("content", "")
                        break

                if user_message:
                    logger.info(f"🧠 [ChromaDB] Searching memories for: '{user_message[:50]}...'")
                    # Search for relevant memories
                    start_time = time.time()
                    memories = await self._search_memories(user_message)
                    search_latency_ms = (time.time() - start_time) * 1000

                    # Emit metrics for observer tracking
                    logger.info(f"📊 [ChromaDB] Search completed in {search_latency_ms:.0f}ms, emitting MetricsFrame")
                    metrics_frame = MetricsFrame(
                        data=[TTFBMetricsData(processor="ChromaDBMemoryService", value=search_latency_ms / 1000)]
                    )
                    await self.push_frame(metrics_frame, direction)

                    if memories:
                        # Inject memories into system message
                        memory_text = self.system_prompt_prefix + "\n".join(memories)

                        # Find system message or create one
                        has_system = False
                        for msg in messages:
                            if msg.get("role") == "system":
                                # Append to existing system message
                                msg["content"] += "\n\n" + memory_text
                                has_system = True
                                break

                        if not has_system:
                            # Insert new system message at the beginning
                            messages.insert(0, {
                                "role": "system",
                                "content": memory_text
                            })

                        logger.info(f"📚 Retrieved {len(memories)} memories in {search_latency_ms:.0f}ms")

                    # Store current conversation turn
                    await self._store_memory(user_message)

            # Pass frame through
            await self.push_frame(frame, direction)

        except Exception as e:
            logger.error(f"❌ [ChromaDB] Error in process_frame: {e}", exc_info=True)
            # Still pass frame through even if we failed
            await self.push_frame(frame, direction)

    async def _search_memories(self, query: str) -> list[str]:
        """Search for relevant memories based on semantic similarity."""
        try:
            # Generate embedding for query
            query_embedding = self.embedder.encode(query).tolist()

            # Search in ChromaDB
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=self.search_limit,
            )

            # Extract documents and filter by threshold
            memories = []
            if results and "documents" in results and results["documents"]:
                for doc_list, distance_list in zip(results["documents"], results.get("distances", [[]])):
                    for doc, distance in zip(doc_list, distance_list):
                        # ChromaDB returns L2 distance, lower is better
                        # Convert to similarity score (1 - normalized distance)
                        similarity = 1 - (distance / 2)  # Normalize L2 distance to [0,1]
                        if similarity >= self.search_threshold:
                            memories.append(doc)

            return memories

        except Exception as e:
            logger.error(f"Error searching memories: {e}")
            return []

    async def _store_memory(self, text: str):
        """Store a memory with its embedding."""
        try:
            # Generate embedding
            embedding = self.embedder.encode(text).tolist()

            # Store in ChromaDB with timestamp as ID
            doc_id = f"{int(time.time() * 1000)}"
            self.collection.add(
                documents=[text],
                embeddings=[embedding],
                ids=[doc_id],
                metadatas=[{
                    "user_id": self.user_id,
                    "agent_id": self.agent_id,
                    "timestamp": time.time()
                }]
            )

            logger.debug(f"💾 Stored memory: {text[:50]}...")

        except Exception as e:
            logger.error(f"Error storing memory: {e}")

    async def close(self):
        """Cleanup resources."""
        # ChromaDB client doesn't need explicit cleanup
        pass
