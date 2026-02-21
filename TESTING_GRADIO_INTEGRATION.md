# Gradio Integration Testing Guide

## Implementation Summary

Successfully integrated Gradio UI into `tars_bot.py` with the following changes:

### Modified Files

1. **src/shared_state.py** - Added pipeline status fields and methods
2. **src/observers/state_observer.py** - Updates pipeline status on state changes
3. **src/ui/gradio_app.py** - Refactored to read from shared_state
4. **src/tars_bot.py** - Added CLI arguments and Gradio launch
5. **ui/app.py** - Added deprecation warning
6. **ui/README.md** - Updated documentation

### New Features

- `--gradio` flag launches integrated UI at http://localhost:7860
- `--gradio-port` specifies custom port
- `--debug` enables debug logging
- `--local-audio` flag (not implemented, shows error)
- Real-time pipeline status updates (idle/listening/thinking/speaking)
- Connection info display (daemon address, audio mode)
- Service info display (STT/LLM/TTS providers)

## Manual Testing Checklist

### 1. Console Mode (No Changes)

```bash
python src/tars_bot.py
```

**Expected Behavior:**
- [ ] Pipeline starts normally
- [ ] No Gradio UI launches
- [ ] Console logs appear as before
- [ ] Robot connection works
- [ ] Conversation flow works

### 2. Gradio Mode

```bash
python src/tars_bot.py --gradio
```

**Expected Behavior:**
- [ ] Gradio UI starts at http://localhost:7860 (NOT 7861)
- [ ] Console shows: "🌐 Gradio UI starting at http://localhost:7860"
- [ ] Pipeline starts in background
- [ ] Both UI and pipeline run simultaneously

### 3. Custom Port

```bash
python src/tars_bot.py --gradio --gradio-port 8080
```

**Expected Behavior:**
- [ ] Gradio UI starts at http://localhost:8080
- [ ] Console shows correct port number
- [ ] UI is accessible at custom port

### 4. Debug Mode

```bash
python src/tars_bot.py --gradio --debug
```

**Expected Behavior:**
- [ ] Debug log level enabled
- [ ] More verbose console output
- [ ] State transitions logged (e.g., "State transition: idle → listening")

### 5. Unsupported Flag

```bash
python src/tars_bot.py --local-audio
```

**Expected Behavior:**
- [ ] Error message: "ERROR: --local-audio not implemented yet. Use robot mode only."
- [ ] Exit code: 1
- [ ] Pipeline does not start

### 6. Help Text

```bash
python src/tars_bot.py --help
```

**Expected Behavior:**
- [ ] Shows usage: "TARS Conversation App - Robot Mode"
- [ ] Lists all flags: --gradio, --gradio-port, --local-audio, --debug
- [ ] Descriptions are clear and accurate

## UI Functionality Testing

### Status Indicator

**Test:** Start pipeline and speak to robot

**Expected Behavior:**
- [ ] Status starts as "Disconnected" (❌)
- [ ] Changes to "Idle" (⚪) after connection
- [ ] Changes to "Listening" (🎤) when user speaks
- [ ] Changes to "Thinking" (🤔) when LLM processes
- [ ] Changes to "Speaking" (🗣️) when TTS outputs
- [ ] Returns to "Idle" after TTS stops
- [ ] Updates every 0.5 seconds

### Service Badges

**Test:** Check service info display

**Expected Behavior:**
- [ ] Shows "⏳ Waiting for connection..." initially
- [ ] Updates to show actual services after pipeline starts
- [ ] Format: "STT: {provider} | LLM: DeepInfra: {model} | TTS: {provider}"
- [ ] Examples:
  - STT: "Speechmatics" or "Deepgram Nova-2" or "Deepgram Flux"
  - LLM: "DeepInfra: Llama-3.3-70B" (or configured model)
  - TTS: "ElevenLabs: eleven_flash_v2_5" or "Qwen3-TTS: {model}"
- [ ] Updates every 2 seconds

### Turn Count

**Test:** Have a conversation with robot

**Expected Behavior:**
- [ ] Shows "Turns: 0" initially
- [ ] Increments after each conversation turn
- [ ] Updates every 1 second

### Conversation Tab

**Test:** Have a conversation with robot

**Expected Behavior:**
- [ ] User messages appear on the left
- [ ] Assistant messages appear on the right
- [ ] Messages appear in real-time as they're spoken
- [ ] Chatbot height is 500px
- [ ] Copy button works for each message
- [ ] Updates every 1 second
- [ ] Shows message: "Audio handled via robot WebRTC connection"

### Metrics Tab

**Test:** Have a conversation with robot

**Expected Behavior:**
- [ ] STT stats show Last/Avg/Min/Max latency
- [ ] LLM stats show Last/Avg/Min/Max latency
- [ ] TTS stats show Last/Avg/Min/Max latency
- [ ] Total latency shows summary
- [ ] Latency chart displays line graph with 3 traces (STT, LLM, TTS)
- [ ] Chart colors: STT=#00D4FF, LLM=#4ECDC4, TTS=#FFE66D
- [ ] Chart uses dark theme
- [ ] Updates every 1-2 seconds
- [ ] Metrics table shows last 15 turns
- [ ] Table columns: Turn | STT | LLM | TTS | Total
- [ ] "N/A" shown for missing values

### Clear Metrics Button

**Test:** Click "Clear Metrics" button

**Expected Behavior:**
- [ ] All metrics cleared from table
- [ ] Chart resets to "No data yet"
- [ ] Stats cards show "N/A"
- [ ] Turn count resets to 0
- [ ] Status message shows "Metrics cleared"
- [ ] Conversation history NOT cleared (only metrics)

### Settings Tab

**Test:** Open Settings tab

**Expected Behavior:**
- [ ] Connection info shows:
  - Daemon: "{RPI_URL} / gRPC: {address}"
  - Audio Mode: "Robot (WebRTC to Pi)"
  - Status: Current pipeline status
- [ ] About section displays
- [ ] Information is accurate
- [ ] Updates every 2 seconds

## Error Handling

### Connection Failure

**Test:** Start bot when RPi is not available

**Expected Behavior:**
- [ ] Console shows: "❌ Failed to connect to RPi. Exiting."
- [ ] Pipeline status set to "disconnected"
- [ ] UI shows status as "Disconnected" (❌)
- [ ] Pipeline exits gracefully

### Pipeline Error

**Test:** Trigger an error during pipeline execution

**Expected Behavior:**
- [ ] Error logged to console
- [ ] Pipeline status set to "error"
- [ ] UI shows status as "Error" (⚠️)
- [ ] Error message includes stack trace
- [ ] Exception is re-raised after status update

### Invalid Status

**Test:** Observer tries to set invalid status

**Expected Behavior:**
- [ ] Warning logged: "Invalid pipeline status: {status}"
- [ ] Pipeline status unchanged
- [ ] No crash or exception

## Integration Testing

### Concurrent Operation

**Test:** Run pipeline and UI together

**Expected Behavior:**
- [ ] UI thread runs as daemon
- [ ] Main asyncio loop runs pipeline
- [ ] Both operate independently
- [ ] UI polls shared_state without blocking pipeline
- [ ] No race conditions or deadlocks
- [ ] Ctrl+C stops both cleanly

### State Synchronization

**Test:** Trigger state changes and verify UI updates

**Expected Behavior:**
- [ ] StateObserver updates shared_state
- [ ] UI polls shared_state and displays changes
- [ ] Latency < 1 second between state change and UI update
- [ ] No stale data displayed
- [ ] Thread-safe access to shared state

### Data Flow

**Test:** Verify complete data flow

**Expected Behavior:**
```
Pipeline → Observers → shared_state → Gradio UI
   ↓          ↓            ↓              ↓
WebRTC    Monitor     Store          Display
           Events      Data           Data
```

- [ ] Audio flows through pipeline
- [ ] Observers capture events
- [ ] shared_state stores data
- [ ] UI displays data in real-time

## Performance Testing

### Memory

**Test:** Run long conversation (100+ turns)

**Expected Behavior:**
- [ ] Memory usage stable (deques limit size)
- [ ] Max 100 metrics stored
- [ ] Max 50 transcriptions stored
- [ ] Old data automatically evicted
- [ ] No memory leaks

### CPU

**Test:** Monitor CPU usage with UI running

**Expected Behavior:**
- [ ] UI adds < 5% CPU overhead
- [ ] Pipeline performance unaffected
- [ ] Polling every 0.5-2 seconds is efficient
- [ ] No spinning or busy-waiting

### Thread Safety

**Test:** Multiple concurrent UI clients (if possible)

**Expected Behavior:**
- [ ] Locks prevent race conditions
- [ ] No corrupted data
- [ ] No crashes or deadlocks
- [ ] All clients see consistent data

## Regression Testing

### Backward Compatibility

**Test:** Ensure existing functionality still works

**Expected Behavior:**
- [ ] Console mode unchanged (python src/tars_bot.py)
- [ ] All observers still function
- [ ] Robot control (gRPC) still works
- [ ] WebRTC connection still works
- [ ] Audio pipeline unchanged
- [ ] Tool functions still work
- [ ] Persona loading still works

### Deprecated UI

**Test:** Run old standalone UI

```bash
python ui/app.py
```

**Expected Behavior:**
- [ ] Deprecation warning appears
- [ ] UI still works (for legacy compatibility)
- [ ] Port 7861 used (not 7860)
- [ ] Console shows warning message

## Edge Cases

### No Data

**Test:** Open UI before having any conversation

**Expected Behavior:**
- [ ] Status: "Disconnected"
- [ ] Service info: "⏳ Waiting for connection..."
- [ ] Turns: 0
- [ ] Metrics table: "No metrics recorded yet."
- [ ] Chart: "No data yet"
- [ ] No errors or crashes

### Rapid State Changes

**Test:** Speak rapidly to robot

**Expected Behavior:**
- [ ] Status updates keep pace
- [ ] No lost state transitions
- [ ] UI remains responsive
- [ ] No flickering or jumping

### Long Messages

**Test:** Send very long user message

**Expected Behavior:**
- [ ] Conversation display wraps text properly
- [ ] No UI overflow or breaking
- [ ] Copy button still works
- [ ] Message fully visible

## Browser Compatibility

**Test:** Open UI in different browsers

**Expected Behavior:**
- [ ] Chrome: Works correctly
- [ ] Firefox: Works correctly
- [ ] Safari: Works correctly
- [ ] Mobile browsers: Responsive layout

## Documentation

**Test:** Verify all documentation is accurate

**Expected Behavior:**
- [ ] ui/README.md reflects new changes
- [ ] Deprecation notice clear
- [ ] Usage examples correct
- [ ] Port numbers accurate (7860 for integrated, 7861 for deprecated)

## Known Limitations

1. **--local-audio not implemented** - Shows error message as expected
2. **UI runs in daemon thread** - Exits when main pipeline exits
3. **Polling-based updates** - Not WebSocket (by design for simplicity)
4. **Port conflict** - If 7860 in use, need to use --gradio-port

## Testing Report Template

```
Date: YYYY-MM-DD
Tester: [Name]
Environment:
- OS: [macOS/Linux]
- Python: [Version]
- Gradio: [Version]
- Robot: [Available/Not Available]

Test Results:
[ ] Console Mode
[ ] Gradio Mode
[ ] Status Updates
[ ] Conversation Display
[ ] Metrics Display
[ ] Error Handling
[ ] Documentation

Issues Found:
1. [Description]
2. [Description]

Notes:
[Additional observations]
```

## Automated Testing (Future)

Consider adding:
- Unit tests for shared_state methods
- Mock pipeline for UI testing
- Integration tests with mock robot
- Screenshot regression tests
- Load testing for concurrent users

## Success Criteria

Implementation is successful if:
- [ ] All manual tests pass
- [ ] No regressions in existing functionality
- [ ] UI updates in real-time (< 2 second latency)
- [ ] No performance degradation
- [ ] Documentation is accurate
- [ ] Deprecation warnings are clear
- [ ] Error handling is robust
