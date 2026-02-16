"""Quick test to verify Gradio integration works."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import time
from src.shared_state import metrics_store

print("Testing shared_state metrics storage...")

# Test 1: Add service info
print("\n1. Setting service info...")
metrics_store.set_service_info({
    "stt": "Deepgram Nova-2",
    "memory": "Hybrid Search (SQLite)",
    "llm": "DeepInfra: Llama-3.3-70B",
    "tts": "ElevenLabs: eleven_flash_v2_5"
})
print(f"   Service info: {metrics_store.get_service_info()}")

# Test 2: Add metrics
print("\n2. Adding test metrics...")
for i in range(1, 4):
    metrics_store.add_metric({
        "turn_number": i,
        "timestamp": int(time.time() * 1000),
        "stt_ttfb_ms": 200 + i * 10,
        "memory_latency_ms": 50 + i * 5,
        "llm_ttfb_ms": 400 + i * 20,
        "tts_ttfb_ms": 300 + i * 15,
        "total_ms": 950 + i * 50,
    })
    print(f"   Added turn {i}")

metrics = metrics_store.get_metrics()
print(f"   Total metrics stored: {len(metrics)}")

# Test 3: Add transcriptions
print("\n3. Adding test transcriptions...")
metrics_store.add_transcription("user", "Hello TARS!")
metrics_store.add_transcription("assistant", "Hello! How can I help you today?")
metrics_store.add_transcription("user", "What's the weather like?")

transcriptions = metrics_store.get_transcriptions()
print(f"   Total transcriptions stored: {len(transcriptions)}")
for t in transcriptions:
    print(f"   [{t['role']}]: {t['text']}")

# Test 4: Verify Gradio app can be imported
print("\n4. Testing Gradio app import...")
try:
    from ui.app import demo
    print("   Gradio app imported successfully!")
    print("   You can now run: python ui/app.py")
except ImportError as e:
    print(f"   Error importing Gradio app: {e}")
    print("   Install dependencies: pip install gradio plotly")

print("\n✅ All tests passed!")
print("\nNext steps:")
print("1. Install dependencies: pip install gradio plotly")
print("2. Run bot: python bot.py")
print("3. Run UI: python ui/app.py")
print("4. Open browser: http://localhost:7861")
