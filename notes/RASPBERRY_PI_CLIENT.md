# Raspberry Pi Client for Pipecat Server

This guide explains how to connect a Raspberry Pi to your Pipecat server as a WebRTC client.

## Overview

The Raspberry Pi client connects to the Pipecat server using WebRTC, streaming audio from the microphone and video from the camera. The server processes the audio/video, performs transcription, LLM processing, and TTS, then streams the response back.

## Prerequisites

### Hardware
- Raspberry Pi (3B+ or newer recommended)
- USB microphone or built-in microphone
- USB camera or Raspberry Pi Camera Module

### Software
- Raspberry Pi OS (or any Linux distribution)
- Python 3.9+
- Camera and microphone drivers configured

## Installation

### 1. Install System Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install audio/video dependencies
sudo apt install -y \
    python3-pip \
    python3-dev \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libswscale-dev \
    libswresample-dev \
    libavfilter-dev \
    pkg-config \
    libasound2-dev \
    portaudio19-dev \
    python3-opencv

# For camera support (if using Pi Camera Module)
sudo apt install -y python3-picamera2
```

### 2. Install Python Dependencies

```bash
pip3 install aiortc aiohttp av opencv-python-headless
```

**Note:** If you encounter issues with `av`, you may need to install it from source or use a pre-built wheel.

### 3. Configure Audio (if needed)

Test your microphone:

```bash
# List audio devices
arecord -l

# Test recording (press Ctrl+C to stop)
arecord -d 5 test.wav
aplay test.wav
```

If using ALSA, you may need to configure `.asoundrc`:

```bash
# Create/edit ~/.asoundrc
nano ~/.asoundrc
```

Example configuration:
```
pcm.!default {
    type hw
    card 1
}
ctl.!default {
    type hw
    card 1
}
```

### 4. Configure Camera

Test your camera:

```bash
# Test USB camera
lsusb | grep -i camera

# Test with fswebcam (if installed)
sudo apt install fswebcam
fswebcam test.jpg

# Or test with Python
python3 -c "import cv2; cap = cv2.VideoCapture(0); print('Camera OK' if cap.isOpened() else 'Camera FAILED'); cap.release()"
```

## Usage

### Basic Usage

```bash
# Connect to local server
python3 raspberry_pi_client.py --server http://localhost:7860

# Connect to remote server
python3 raspberry_pi_client.py --server http://192.168.1.100:7860
```

### Command Line Options

```bash
python3 raspberry_pi_client.py --help
```

Options:
- `--server`: Pipecat server URL (default: `http://localhost:7860`)

## How It Works

1. **Connection Setup**: Client creates a WebRTC peer connection and sends an offer to the server
2. **Media Streaming**: Audio and video are captured from the Pi's hardware and streamed via WebRTC
3. **Server Processing**: Server processes audio (STT), generates responses (LLM), and synthesizes speech (TTS)
4. **Data Channel**: Transcriptions and status messages are received via WebRTC data channel
5. **Audio Output**: TTS audio from server is received (you can configure playback)

## Troubleshooting

### Camera Issues

**Problem**: Camera not detected
```bash
# Check camera permissions
ls -l /dev/video*

# Test camera access
python3 -c "import cv2; cap = cv2.VideoCapture(0); print(cap.isOpened()); cap.release()"
```

**Solution**: 
- Ensure camera is connected and detected: `lsusb` or `vcgencmd get_camera`
- Check permissions: `sudo usermod -a -G video $USER` (logout/login)
- Try different camera index: Change `cv2.VideoCapture(0)` to `cv2.VideoCapture(1)`

### Audio Issues

**Problem**: Microphone not working
```bash
# List audio devices
arecord -l

# Test microphone
arecord -d 3 -f cd test.wav && aplay test.wav
```

**Solution**:
- Check ALSA configuration: `alsamixer`
- Set default audio device in `.asoundrc`
- Try different audio format/device in the code

### WebRTC Connection Issues

**Problem**: Connection fails
- Check server is running: `curl http://SERVER_URL:7860/api/status`
- Check network connectivity: `ping SERVER_IP`
- Check firewall: Ensure port 7860 is accessible
- Check STUN server: The client uses Google's STUN server (`stun:stun.l.google.com:19302`)

### Performance Issues

**Problem**: High CPU usage or dropped frames
- Reduce video resolution in `PiCameraVideoTrack.__init__()`:
  ```python
  self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
  self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
  self.cap.set(cv2.CAP_PROP_FPS, 15)
  ```
- Use hardware acceleration if available
- Close other applications

## Advanced Configuration

### Custom Video Resolution

Edit `raspberry_pi_client.py`:

```python
class PiCameraVideoTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.cap = cv2.VideoCapture(0)
        # Custom resolution
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 15)
```

### Custom Audio Device

Edit `raspberry_pi_client.py`:

```python
class PiMicrophoneAudioTrack(AudioStreamTrack):
    def __init__(self):
        super().__init__()
        # Use specific ALSA device
        self.player = MediaPlayer(
            "hw:1,0",  # Card 1, Device 0
            format="alsa",
            options={
                "channels": "1",
                "sample_rate": "16000",
            }
        )
```

### Play TTS Audio

To play the TTS audio received from the server, you can modify the `on_track` handler:

```python
@self.pc.on("track")
async def on_track(track):
    if track.kind == "audio":
        # Save audio to file and play
        # Or use a media player library
        pass
```

## Alternative: Using MediaPlayer (Simpler)

For a simpler setup, you can use `MediaPlayer` for both audio and video:

```python
from aiortc.contrib.media import MediaPlayer

# Video from camera
video_player = MediaPlayer("/dev/video0", format="v4l2", options={
    "video_size": "1280x720",
    "framerate": "30",
})

# Audio from microphone
audio_player = MediaPlayer("default", format="alsa", options={
    "channels": "1",
    "sample_rate": "16000",
})

# Add tracks
pc.addTrack(video_player.video)
pc.addTrack(audio_player.audio)
```

## Network Configuration

### Local Network

If server and Pi are on the same network:
```bash
python3 raspberry_pi_client.py --server http://192.168.1.100:7860
```

### Remote Access

For remote access, ensure:
1. Server is accessible (firewall, port forwarding if needed)
2. Use public IP or domain name
3. Consider using TURN server for NAT traversal (if STUN fails)

## Example Output

When running, you should see:

```
INFO:__main__:Connecting to Pipecat server at http://localhost:7860...
INFO:__main__:Camera initialized: 1280x720 @ 30fps
INFO:__main__:✓ Video track created
INFO:__main__:Microphone initialized
INFO:__main__:✓ Audio track created
INFO:__main__:Sending WebRTC offer to server...
INFO:__main__:Received answer with pc_id: abc123...
INFO:__main__:WebRTC connection established!
INFO:__main__:Connection state: connecting
INFO:__main__:Connection state: connected
INFO:__main__:✓ Connected to Pipecat server!
INFO:__main__:Data channel opened
INFO:__main__:System: Connection established
🎤 Hello, how are you?
🎤 [Speaker 1] I'm doing well, thank you!
```

## Integration with Other Projects

You can integrate this client into your own projects:

```python
from raspberry_pi_client import PipecatClient

async def main():
    client = PipecatClient("http://your-server:7860")
    await client.connect()
    # Your code here
    await client.disconnect()
```

## Security Notes

- The client connects to the server over HTTP/WebRTC
- For production, consider using HTTPS/WSS
- Ensure server has proper authentication if exposed to internet
- WebRTC uses DTLS for encryption, but signaling (HTTP) should also be secured

## Support

For issues:
1. Check server logs: `python3 pipecat_service.py --verbose`
2. Check client logs: Run with Python logging enabled
3. Test server status: `curl http://SERVER:7860/api/status`
4. Verify network connectivity between Pi and server

