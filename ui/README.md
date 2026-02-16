# TARS Gradio UI

Real-time dashboard for monitoring TARS conversation metrics and transcriptions.

## Features

### Latency Dashboard
- **Service Info**: Shows STT, Memory, LLM, TTS providers
- **Stats Cards**: Min/Max/Avg/Last values for each metric
- **Line Chart**: TTFB latency trends over time
- **Bar Chart**: Stacked latency breakdown for recent turns
- **Metrics Table**: Last 15 turns with detailed timings

### Conversation Tab
- Live transcription history
- User and assistant messages
- Auto-updates every second

### Connection Tab
- Architecture documentation
- Usage instructions

## Running the UI

### Prerequisites
```bash
pip install gradio plotly
```

### Launch
```bash
# From project root
python ui/app.py
```

Then open http://localhost:7861

### With Bot Pipeline

Terminal 1:
```bash
python bot.py
```

Terminal 2:
```bash
python ui/app.py
```

## Architecture

The UI reads from `src/shared_state.py`, which is populated by observers in the Pipecat pipeline:

```
bot.py (Pipecat Pipeline)
    ↓
src/observers/ (metrics, transcription, assistant)
    ↓
src/shared_state.py (in-memory storage)
    ↓
ui/app.py (Gradio dashboard)
```

## Data Sources

### Metrics (from MetricsObserver)
- STT TTFB (Time To First Byte)
- Memory latency
- LLM TTFB
- TTS TTFB
- Total latency

### Transcriptions
- User messages (from TranscriptionObserver)
- Assistant responses (from AssistantResponseObserver)

### Service Info
- STT provider (e.g., "Deepgram Nova-2")
- Memory system (e.g., "Hybrid Search (SQLite)")
- LLM model (e.g., "DeepInfra: Llama-3.3-70B")
- TTS provider (e.g., "ElevenLabs: eleven_flash_v2_5")

## Customization

### Update Frequency
Change polling intervals in `app.py`:
```python
# Current settings
service_info = gr.Markdown(get_service_badges, every=2)  # Every 2 seconds
turn_count = gr.Markdown(get_turn_count, every=1)        # Every 1 second
```

### Data Retention
Modify limits in `src/shared_state.py`:
```python
metrics: deque = field(default_factory=lambda: deque(maxlen=100))       # Keep 100 turns
transcriptions: deque = field(default_factory=lambda: deque(maxlen=50)) # Keep 50 messages
```

### Theme
Change Gradio theme in `app.py`:
```python
theme=gr.themes.Soft(primary_hue="cyan", neutral_hue="slate")
```

## Development

### Testing
```bash
python tests/gradio/test_gradio.py
```

### Adding New Charts
1. Create function that reads from `metrics_store`
2. Return Plotly figure
3. Add to Gradio interface with `gr.Plot(your_function, every=2)`

### Adding New Stats
1. Create function that reads from `metrics_store`
2. Return formatted markdown string
3. Add to Gradio interface with `gr.Markdown(your_function, every=1)`

## Troubleshooting

### No data showing
- Ensure bot.py is running
- Check that WebRTC client is connected
- Verify at least one conversation turn has completed

### Import errors
```bash
pip install gradio plotly
```

### Charts not updating
- Check that observers are enabled in bot.py
- Verify shared_state.py is being imported correctly
- Check console for errors

## Performance

- Polling every 1-2 seconds (no WebSocket overhead)
- Deques auto-limit memory usage
- Thread-safe concurrent access
- Minimal CPU impact on bot pipeline
