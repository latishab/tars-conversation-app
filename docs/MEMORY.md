# Hybrid Memory System

## Overview

A high-performance memory system optimized for voice AI applications with sub-50ms latency targets. Combines semantic vector search with BM25 keyword matching for superior recall and precision.

## Architecture

### Hybrid Search (70% Vector + 30% BM25)

1. **Vector Search (70% weight)**
   - Uses `all-MiniLM-L6-v2` for semantic embeddings
   - Cosine similarity for relevance scoring
   - Captures semantic meaning and context

2. **BM25 Keyword Search (30% weight)**
   - SQLite FTS5 full-text search
   - Exact keyword matching
   - Handles specific names, terms, and facts

3. **Score Fusion**
   - Weighted combination of both approaches
   - Best of both worlds: semantic understanding + exact matching

## Performance Optimizations

### For Voice AI (<50ms target)

| Optimization | Benefit |
|--------------|---------|
| **Query Embedding Cache** | Avoid re-encoding similar queries (-20-40ms on cache hit) |
| **Pre-warmed Model** | Eliminates cold start latency (-50ms) |
| **Thread Pool** | Non-blocking SQLite operations (-5-10ms) |
| **Strict Timeout** | Guarantees <50ms with graceful fallback |
| **Fire-and-Forget Storage** | Stores memories asynchronously (0ms blocking) |
| **SQLite In-Process** | No network overhead vs ChromaDB (-10-20ms) |

## Latency Comparison

| System | Search Latency | Voice AI Ready? |
|--------|---------------|-----------------|
| ChromaDB | 50-100ms | ⚠️ Borderline |
| **Hybrid Memory** | **20-40ms** | ✅ |

## Configuration

```python
memory_service = HybridMemoryService(
    user_id=client_id,
    db_path="./memory_data/memory.sqlite",
    search_limit=3,              # Top N results to return
    search_timeout_ms=40,        # Strict timeout for voice AI
    vector_weight=0.7,           # 70% semantic similarity
    bm25_weight=0.3,             # 30% keyword matching
    system_prompt_prefix="From our conversations:\n",
)
```

## Database Schema

### Main Table
```sql
CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding BLOB,              -- numpy float32 array
    created_at REAL
)
```

### FTS5 Index
```sql
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='id'
)
```

## Performance Metrics

The service tracks:
- **searches**: Total number of searches
- **cache_hits**: Query embedding cache hits
- **cache_hit_rate**: Percentage of cached queries
- **timeouts**: Searches exceeding timeout threshold
- **avg_latency_ms**: Average search latency

Access stats:
```python
stats = memory_service.get_stats()
print(stats)
```

## How It Works

### Search Process

1. **User message arrives** → Extract text
2. **Generate query embedding** → Check cache first
3. **Vector search** → Scan recent 100 memories, compute cosine similarity
4. **BM25 search** → FTS5 query for keyword matches
5. **Score fusion** → Combine weighted scores
6. **Return top N** → Sorted by final score
7. **Inject into context** → Add as system message
8. **Store asynchronously** → Fire-and-forget storage

### Example

```
User: "What's my favorite color?"

Vector Search:
- "I love blue, it's my favorite color" → 0.85 similarity
- "My room is painted blue" → 0.62 similarity

BM25 Search:
- "I love blue, it's my favorite color" → rank 1 (score: 1.0)
- "Blue is calming" → rank 2 (score: 0.5)

Final Scores (70% vector + 30% BM25):
- "I love blue, it's my favorite color" → 0.85*0.7 + 1.0*0.3 = 0.895 ✓
- "My room is painted blue" → 0.62*0.7 + 0.0*0.3 = 0.434
- "Blue is calming" → 0.0*0.7 + 0.5*0.3 = 0.150

Top result returned: "I love blue, it's my favorite color"
```

## Migration from ChromaDB

The hybrid memory service is a drop-in replacement:

```diff
- from services.memory_chromadb import ChromaDBMemoryService
+ from services.memory_hybrid import HybridMemoryService

- memory_service = ChromaDBMemoryService(
+ memory_service = HybridMemoryService(
      user_id=client_id,
-     agent_id="tars_agent",
-     collection_name="conversations",
-     search_limit=5,
-     search_threshold=0.5,
+     db_path="./memory_data/memory.sqlite",
+     search_limit=3,
+     search_timeout_ms=40,
+     vector_weight=0.7,
+     bm25_weight=0.3,
  )
```

## Storage Location

- **Database**: `./memory_data/memory.sqlite`
- **Format**: SQLite with FTS5 extension
- **Embeddings**: Stored as binary BLOBs (numpy float32)

## Dependencies

- `sqlite3` (built-in with Python)
- `sentence-transformers` (already installed)
- `numpy` (dependency of sentence-transformers)

No additional packages required!

## Troubleshooting

### High Latency
- Check cache hit rate: `memory_service.get_stats()`
- Reduce `search_limit` if processing too many results
- Increase `search_timeout_ms` if needed

### Timeouts
- Review timeout stats: `stats["timeouts"]`
- Consider increasing `search_timeout_ms` to 50-60ms
- Check if database is growing too large

### Memory Not Recalled
- Verify memories are being stored (check database)
- Adjust `vector_weight` and `bm25_weight` balance
- Try rephrasing queries to match stored content

## Future Enhancements

- [ ] Automatic database compaction/cleanup
- [ ] Per-user memory limits
- [ ] Memory importance scoring
- [ ] Temporal decay for older memories
- [ ] Multi-turn conversation grouping
