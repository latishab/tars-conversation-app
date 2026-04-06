# Daemon Dashboard Integration

How tars-conversation-app integrates with tars-daemon for app management.

## Overview

The tars-daemon dashboard at `http://tars.local:8000/dashboard` provides install/uninstall/start buttons for TARS apps. Apps are installed to `~/tars-apps/` via `git clone`, with `install.sh` running automatically after cloning.

## Daemon Ports

- **8000**: HTTP -- WebRTC signaling, REST API, dashboard UI
- **50051**: gRPC -- hardware control

## App Discovery

The daemon scans `~/tars-apps/` for directories containing an `app.json` manifest. Each manifest defines the app name, entry point, install/uninstall scripts, dependencies, and required environment variables. See [app.json format](DEVELOPING_APPS.md#app-manifest-appjson).

## Installation Flow

1. User clicks "Install" in the dashboard
2. Daemon clones the repo into `~/tars-apps/<app-name>/`
3. Daemon runs the `install_script` from `app.json` (default: `install.sh`)
4. Dashboard shows install output and updates status

## Uninstallation Flow

1. User clicks "Uninstall"
2. Daemon runs the `uninstall_script` from `app.json` (default: `uninstall.sh`)
3. Optionally removes the app directory

## Running Apps

The daemon reads the `main` field from `app.json` to determine the entry point. It activates the app's venv and runs the script. Mode-specific commands can be defined in `app.json` under `modes`.

## Directory Structure

```
/home/mac/
|- tars-daemon/              # Main daemon
|  |- tars_daemon.py
|  +- dashboard.py
|
+- tars-apps/                # Apps directory
   |- tars-conversation-app/
   |  |- app.json
   |  |- install.sh
   |  +- ...
   +- another-app/
      +- app.json
```

## Testing

```bash
cd ~/tars-apps/tars-conversation-app
bash install.sh
source venv/bin/activate
python -c "import pipecat; print('OK')"
```
