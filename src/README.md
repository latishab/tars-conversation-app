# TARS Source Code

Python source code for TARS voice AI.

## Structure

```
src/
├── tools/           # LLM callable functions (robot, persona, vision)
├── services/        # Backend services (STT, TTS, memory, robot control)
├── processors/      # Pipeline frame processors
├── observers/       # Pipeline observers
├── transport/       # WebRTC transport layer
├── character/       # TARS personality and prompts
└── config/          # Configuration management
```

## Entry Points

Entry point scripts are in the project root:

- `bot.py` - Browser mode (web UI)
- `tars_bot.py` - Robot mode (RPi connection)
- `pipecat_service.py` - FastAPI backend for browser mode

## Imports

All entry points add `src/` to the Python path automatically:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Now you can import from src/ directories
from tools import execute_movement
from services import tars_robot
from config import DEEPGRAM_API_KEY
```

## Documentation

Each directory contains a README.md explaining its purpose:

- [tools/README.md](tools/README.md) - LLM callable functions
- [services/README.md](services/README.md) - Backend services

## Not Source

This directory is for Python source code only:

- Web UI files are in `web/`
- Documentation is in `docs/`
- Scripts are in `scripts/`
- Assets are in `assets/`
