# TARS Hardware Tests

Test scripts for validating TARS robot hardware functionality.

## Test Scripts

### `test_gesture.py`
Tests TARS physical movements and gestures.

**Tests:**
- `side_side` - Side-to-side head movement
- `wave_right` - Right arm wave gesture
- `bow` - Bow gesture

**Usage:**
```bash
python tests/test_gesture.py
```

### `test_speaker.py`
Tests audio hardware: speaker output and microphone input.

**Tests:**
1. Speaker device detection
2. Friendly test melody playback (C-E-G)
3. Microphone device detection
4. 5-second audio recording
5. Playback of recorded audio

**Usage:**
```bash
python tests/test_speaker.py
```

### `test_expressions.py`
Tests TARS facial expressions: emotions and eye states.

**Emotions tested:**
- default, happy, angry, tired, surprised, confused

**Eye states tested:**
- idle, listening, thinking, speaking

**Usage:**
```bash
python tests/test_expressions.py
```

## Requirements

- TARS daemon must be running on Raspberry Pi
- SSH access configured to `tars-pi`
- Python dependencies installed (see `requirements.txt`)

## Configuration

Tests connect to Pi at `100.84.133.74:50051` (gRPC) and `100.84.133.74:8001` (HTTP).

Update the IP address in test files if your Pi has a different address.
