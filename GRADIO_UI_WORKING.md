# Gradio UI - Working Configuration

## Summary

The integrated Gradio UI is now working successfully at http://localhost:7860.

## Fix Applied

**Issue:** Gradio 5.20.1 had a schema generation bug that caused HTTP 500 errors when accessing the UI.

**Solution:** Upgraded to Gradio 5.50.0, which fixes the schema bug while remaining compatible with fastrtc dependency.

## Requirements

- Gradio version: **>=5.50.0,<6.0**
- Compatible with fastrtc 0.0.34 requirement: `gradio<6.0,>=4.0`

## Usage

```bash
# Start TARS with Gradio UI
python src/tars_bot.py --gradio

# Custom port
python src/tars_bot.py --gradio --gradio-port 8080

# With debug logging
python src/tars_bot.py --gradio --debug
```

##Access

Open your browser to: **http://localhost:7860**

## Features

### Real-time Updates
- **Status Indicator** - Shows pipeline state (idle/listening/thinking/speaking) with emoji
- **Service Info** - Displays STT/LLM/TTS providers
- **Turn Count** - Tracks number of conversation turns

### Tabs

**1. Conversation**
- Live transcription of user and assistant messages
- Updates every 1 second
- Copy button for each message

**2. Metrics**
- STT/LLM/TTS latency statistics (Last/Avg/Min/Max)
- Total latency summary
- Line chart showing latency trends over time
- Table of recent 15 turns
- Clear metrics button

**3. Settings**
- Connection information (daemon address, audio mode, status)
- About section with architecture details

### Update Intervals
- Status: 0.5 seconds (fast)
- Conversation: 1 second (medium)
- Metrics: 1 second (medium)
- Service info: 2 seconds (slow)
- Charts: 2 seconds (slow)
- Connection info: 2 seconds (slow)

## Implementation Details

### Modern Gradio Pattern

The UI uses the modern Gradio Timer pattern instead of deprecated `every` parameter:

```python
# Create timers
timer_fast = gr.Timer(value=0.5)
timer_medium = gr.Timer(value=1)
timer_slow = gr.Timer(value=2)

# Attach update functions
timer_medium.tick(fn=self.get_conversation_history, outputs=chatbot)
timer_slow.tick(fn=self.create_latency_chart, outputs=latency_chart)
```

### Data Flow

```
Pipeline → Observers → shared_state.metrics_store → Gradio UI (polling)
```

- **StateObserver** updates pipeline_status in shared_state
- **TranscriptionObserver** adds user messages to transcriptions
- **AssistantObserver** adds assistant messages to transcriptions
- **MetricsObserver** adds latency data to metrics
- **Gradio UI** polls shared_state via Timer events

### Thread Architecture

```
Main Thread (asyncio)
├─ Pipeline (WebRTC, STT, LLM, TTS)
├─ Observers (update shared_state)
└─ Gradio Thread (daemon)
   └─ Uvicorn Server (port 7860)
      └─ Timer events (poll shared_state)
```

## Testing Results

### Verified Working
- ✓ HTTP 200 response from http://127.0.0.1:7860
- ✓ Server listens on port 7860
- ✓ Gradio UI loads in browser
- ✓ No schema generation errors
- ✓ Compatible with fastrtc dependency

### Not Yet Tested (requires robot connection)
- Real-time status updates during conversation
- Transcription display
- Metrics collection and display
- Chart updates

## Known Issues

### Resolved
- ~~HTTP 500 errors due to Gradio schema bug~~ - Fixed by upgrading to 5.50.0
- ~~Import path conflicts between root ui/ and src/ui/~~ - Fixed by ensuring src/ is first in sys.path
- ~~Chatbot deprecation warning~~ - Using type="tuples" (will migrate to "messages" later)

### Dependency Conflicts (warnings only, non-blocking)
- `qwen-tts` wants `accelerate==1.12.0`, but `1.10.1` is installed
  - Status: Warning only, doesn't affect Gradio UI

## Browser Compatibility

Should work in:
- Chrome/Edge (Chromium)
- Firefox
- Safari
- Mobile browsers

## Performance

- Minimal CPU overhead (Timer-based polling)
- Memory-bounded (deques with maxlen limits)
- Thread-safe access to shared state
- Non-blocking daemon thread

## Next Steps

To test with actual robot:
1. Ensure TARS daemon running on Pi: `python tars_daemon.py`
2. Start bot with UI: `python src/tars_bot.py --gradio`
3. Open http://localhost:7860 in browser
4. Have a conversation with TARS
5. Observe real-time updates in UI

## Troubleshooting

### UI shows "Site can't be reached"
- Check Gradio version: `python -c "import gradio; print(gradio.__version__)"`
- Should be >= 5.50.0
- If lower, upgrade: `pip install 'gradio>=5.50.0,<6.0'`

### Port already in use
- Change port: `python src/tars_bot.py --gradio --gradio-port 8080`
- Or kill process: `lsof -ti:7860 | xargs kill`

### Import errors
- Ensure running from project root: `/Users/mac/Desktop/tars-conversation-app`
- Check sys.path includes src/: `python -c "import sys; print(sys.path)"`

### No data in UI
- Pipeline must be connected to robot for data to appear
- Status will show "Disconnected" until connection established
- Service info shows "Waiting for connection..." until pipeline starts

## Files Modified

1. **src/shared_state.py** - Added pipeline_status, daemon_address, audio_mode fields
2. **src/observers/state_observer.py** - Updates shared_state on state changes
3. **src/ui/gradio_app.py** - Refactored to use Timer pattern, reads from shared_state
4. **src/tars_bot.py** - Added CLI arguments, launches Gradio in daemon thread
5. **ui/app.py** - Added deprecation warning
6. **ui/README.md** - Updated documentation

## Version Info

- **Gradio:** 5.50.0
- **Python:** 3.12.9
- **Pipecat:** 0.0.102
- **Platform:** macOS (Darwin 25.3.0)

## Success!

The Gradio UI integration is complete and working. The UI can now be launched with:

```bash
python src/tars_bot.py --gradio
```

And accessed at http://localhost:7860 for real-time monitoring of the TARS conversation pipeline.
