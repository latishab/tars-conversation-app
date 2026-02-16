# Developing Apps with TARS SDK

Guide for creating TARS-compatible applications that integrate with the tars-daemon.

## Architecture Overview

TARS apps connect to the tars-daemon running on Raspberry Pi:

```
[Your App] ←→ gRPC (50051) ←→ [tars-daemon] ←→ [Hardware]
                                                  ├─ Motors
                                                  ├─ Camera
                                                  └─ Display
```

## App Structure

### Minimal Structure

```
your-app/
├── app.json                 # App manifest (required)
├── requirements.txt         # Python dependencies
├── config.ini.example       # Configuration template
├── env.example              # Environment variables template
├── install.sh               # Installation script
├── uninstall.sh             # Cleanup script
├── main.py                  # Entry point
└── README.md                # Documentation
```

## App Manifest (app.json)

Required file for daemon dashboard integration:

```json
{
  "name": "tars-conversation-app",
  "version": "1.0.0",
  "description": "Real-time conversational AI with WebRTC",
  "author": "Your Name",
  "repository": "https://github.com/yourusername/your-app.git",
  "main": "tars_bot.py",
  "install_script": "install.sh",
  "uninstall_script": "uninstall.sh",
  "dependencies": {
    "python": ">=3.10",
    "system": ["portaudio19-dev", "ffmpeg"]
  },
  "environment": [
    "DEEPINFRA_API_KEY",
    "SPEECHMATICS_API_KEY"
  ],
  "configuration": {
    "file": "config.ini",
    "example": "config.ini.example"
  },
  "ports": {
    "grpc": 50051,
    "http": 8765
  }
}
```

## Configuration System

### Environment Variables (.env.local)

Store secrets only, never commit:

```bash
# API Keys
DEEPINFRA_API_KEY=your_key_here
SPEECHMATICS_API_KEY=your_key_here
ELEVENLABS_API_KEY=your_key_here
```

### User Configuration (config.ini)

Runtime settings users can modify:

```ini
[Connection]
mode = robot
rpi_url = http://100.84.133.74:8765
rpi_grpc = 100.84.133.74:50051
auto_connect = false

[LLM]
model = openai/gpt-oss-20b
gating_model = meta-llama/Llama-3.2-3B-Instruct
```

### Loading Configuration

```python
from pathlib import Path
from configparser import ConfigParser
from dotenv import load_dotenv
import os

# Load secrets
env_local = Path(__file__).parent / ".env.local"
load_dotenv(env_local, override=True)

# Load config
config = ConfigParser()
config.read("config.ini")

# Runtime reload without restart
def get_fresh_config():
    config = ConfigParser()
    config.read("config.ini")
    return config
```

## Connecting to tars-daemon

### gRPC Client

```python
import grpc
from tars_sdk import TarsClient

# Singleton client
_client = None

def get_tars_client():
    global _client
    if _client is None:
        grpc_address = os.getenv("RPI_GRPC", "100.84.133.74:50051")
        channel = grpc.insecure_channel(grpc_address)
        _client = TarsClient(channel)
    return _client

# Use the client
client = get_tars_client()
client.execute_movement("wave_right")
client.set_emotion("happy")
```

### Deployment Mode Detection

Auto-detect if running locally on Pi or remotely:

```python
def detect_deployment_mode():
    # Check if running on Raspberry Pi
    try:
        with open("/proc/cpuinfo", "r") as f:
            if "Raspberry Pi" in f.read():
                return "local"
    except FileNotFoundError:
        pass

    # Check if daemon running on localhost
    try:
        import grpc
        channel = grpc.insecure_channel("localhost:50051")
        grpc.channel_ready_future(channel).result(timeout=1)
        return "local"
    except:
        return "remote"

def get_grpc_address():
    if detect_deployment_mode() == "local":
        return "localhost:50051"
    return os.getenv("RPI_GRPC", "100.84.133.74:50051")
```

## Installation Scripts

### install.sh

```bash
#!/bin/bash
set -e

APP_NAME="your-app"
APP_DIR="$HOME/$APP_NAME"

echo "Installing $APP_NAME..."

# Check Python version
python3 --version | grep -q "3.1[0-9]" || {
    echo "Error: Python 3.10+ required"
    exit 1
}

# Install system dependencies
sudo apt-get update
sudo apt-get install -y portaudio19-dev ffmpeg

# Create virtual environment
python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Setup configuration
if [ ! -f config.ini ]; then
    cp config.ini.example config.ini
    echo "Created config.ini - please configure before running"
fi

if [ ! -f .env.local ]; then
    cp env.example .env.local
    echo "Created .env.local - please add API keys"
fi

echo "Installation complete!"
echo "Next steps:"
echo "1. Edit .env.local with your API keys"
echo "2. Edit config.ini if needed"
echo "3. Run: python main.py"
```

### uninstall.sh

```bash
#!/bin/bash
set -e

APP_NAME="your-app"
APP_DIR="$HOME/$APP_NAME"

echo "Uninstalling $APP_NAME..."

# Stop running processes
pkill -f "python.*$APP_NAME" || true

# Remove virtual environment
rm -rf "$APP_DIR/venv"

# Remove generated data (optional)
read -p "Remove data directories? (y/N) " -n 1 -r
echo
if [[ $REPL =~ ^[Yy]$ ]]; then
    rm -rf chroma_memory memory_data
fi

echo "Uninstall complete!"
```

## Best Practices

### 1. Project Structure

- Keep source code in `src/` directory
- Separate configuration from code
- Provide example configs (never commit secrets)
- Include tests in `tests/` directory

### 2. Configuration

- Use `.env.local` for secrets (gitignore it)
- Use `config.ini` for user settings (gitignore it)
- Provide `.example` templates
- Support runtime config reload when possible

### 3. Dependencies

- Pin major versions in requirements.txt
- Document system dependencies in README
- Test on fresh Pi OS installation
- Keep dependencies minimal

### 4. Error Handling

- Validate configuration on startup
- Provide clear error messages
- Test connection to daemon before running
- Graceful degradation if hardware unavailable

### 5. Performance

- Use gRPC for low-latency commands (~5-10ms)
- Batch operations when possible
- Monitor resource usage on Pi
- Optimize for Raspberry Pi 4 (4GB RAM)

### 6. Testing

- Test on actual hardware
- Provide test scripts for gestures/expressions
- Document expected behavior
- Include connection tests

## Example: Minimal TARS App

```python
# main.py
import grpc
from tars_sdk import TarsClient
from pathlib import Path
from dotenv import load_dotenv
import os

# Load configuration
load_dotenv(Path(__file__).parent / ".env.local")

# Connect to daemon
grpc_address = os.getenv("RPI_GRPC", "100.84.133.74:50051")
channel = grpc.insecure_channel(grpc_address)
client = TarsClient(channel)

# Test connection
try:
    status = client.get_robot_status()
    print(f"Connected to TARS: {status}")
except Exception as e:
    print(f"Connection failed: {e}")
    exit(1)

# Use robot
client.set_emotion("happy")
client.execute_movement("wave_right")
print("TARS says hello!")
```

## Integration with Claude Code

Structure your app for easy AI-assisted development:

1. **Clear directory structure** - AI can navigate easily
2. **Documented configuration** - AI understands settings
3. **Type hints** - AI provides better suggestions
4. **Docstrings** - AI understands intent
5. **README.md** - AI reads project context

See CLAUDE.md for project-specific guidelines.

## Common Patterns

### Startup Validation

```python
def validate_startup():
    """Check all requirements before running"""
    errors = []

    # Check API keys
    if not os.getenv("DEEPINFRA_API_KEY"):
        errors.append("Missing DEEPINFRA_API_KEY in .env.local")

    # Check config file
    if not Path("config.ini").exists():
        errors.append("config.ini not found")

    # Test daemon connection
    try:
        client = get_tars_client()
        client.get_robot_status()
    except Exception as e:
        errors.append(f"Cannot connect to daemon: {e}")

    if errors:
        print("Startup validation failed:")
        for error in errors:
            print(f"  - {error}")
        exit(1)
```

### Graceful Shutdown

```python
import signal
import sys

def signal_handler(sig, frame):
    """Clean shutdown on Ctrl+C"""
    print("\nShutting down...")

    # Reset robot state
    try:
        client = get_tars_client()
        client.set_emotion("neutral")
        client.set_eye_state(True, True)
    except:
        pass

    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
```

## Resources

- tars-daemon: `~/tars-daemon` on Pi
- TARS SDK: Install via pip `pip install tars-sdk`
- Example Apps: This repository (tars-conversation-app)
- Pi Access: `ssh tars-pi` (100.84.133.74)

## Support

- Check daemon status: `systemctl status tars-daemon`
- View daemon logs: `journalctl -u tars-daemon -f`
- Test gRPC connection: `grpcurl -plaintext 100.84.133.74:50051 list`
