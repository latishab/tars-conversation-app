# Developing Apps with TARS SDK

Guide for creating TARS-compatible applications that integrate with the tars-daemon.

## Architecture

```
[Your App] <-> gRPC (50051) <-> [tars-daemon] <-> [Hardware]
                                                   |- Motors
                                                   |- Camera
                                                   +- Display
```

## App Structure

```
your-app/
|- app.json                 # App manifest (required)
|- requirements.txt         # Python dependencies
|- config.ini.example       # Configuration template
|- env.example              # Environment variables template
|- install.sh               # Installation script
|- uninstall.sh             # Cleanup script
|- main.py                  # Entry point
+- README.md
```

## App Manifest (app.json)

Required for daemon dashboard integration:

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

## Configuration

- `.env.local` for secrets (gitignored). Copy from `env.example`.
- `config.ini` for runtime settings (gitignored). Copy from `config.ini.example`.
- Load with `dotenv` and `ConfigParser`. See [Configuration Reference](CONFIGURATION.md).

## Connecting to tars-daemon

```python
import grpc
import os
from tars_sdk import TarsClient

grpc_address = os.getenv("RPI_GRPC", "tars.local:50051")
channel = grpc.insecure_channel(grpc_address)
client = TarsClient(channel)

client.set_emotion("happy")
client.execute_movement("wave_right")
```

Use `localhost:50051` when running directly on the Pi.

## Minimal App Example

```python
import grpc
from tars_sdk import TarsClient
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent / ".env.local")

grpc_address = os.getenv("RPI_GRPC", "tars.local:50051")
channel = grpc.insecure_channel(grpc_address)
client = TarsClient(channel)

try:
    status = client.get_robot_status()
    print(f"Connected to TARS: {status}")
except Exception as e:
    print(f"Connection failed: {e}")
    exit(1)

client.set_emotion("happy")
client.execute_movement("wave_right")
```

## Install/Uninstall Scripts

`install.sh` should:
- Check Python 3.10+
- Install system deps (`portaudio19-dev`, `ffmpeg`)
- Create venv and install requirements
- Copy example configs if missing

`uninstall.sh` should:
- Stop running processes
- Remove the venv
- Optionally remove data directories

## Best Practices

- Keep source in `src/`, tests in `tests/`
- Pin major versions in requirements.txt
- Never commit secrets -- use `.env.local`
- Validate config and daemon connection on startup
- Test on actual Pi hardware
- Use gRPC for low-latency commands (~5-10ms)

## Resources

- tars-daemon: `~/tars-daemon` on Pi
- TARS SDK: `pip install tars-sdk`
- Pi access: `ssh tars-pi` (`tars.local` or Tailscale hostname `tars`)
- Daemon status: `systemctl status tars-daemon`
- Daemon logs: `journalctl -u tars-daemon -f`
