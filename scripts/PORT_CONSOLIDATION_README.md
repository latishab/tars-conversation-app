# TARS Daemon Port Consolidation

Consolidates daemon from 3 ports to 2 ports for simpler architecture.

## Architecture Changes

### Before (3 Ports)
- Port 8001: tars_daemon.py (WebRTC signaling + minimal REST API)
- Port 8080: dashboard (Gradio UI + management APIs)
- Port 50051: gRPC (hardware control)

### After (2 Ports)
- Port 8000: Unified HTTP server (WebRTC + Dashboard + REST API)
- Port 50051: gRPC (hardware control, unchanged)

## Benefits

1. Simpler deployment - one HTTP process instead of two
2. Fewer ports to manage and expose
3. Direct state sharing (no HTTP calls between components)
4. Built-in OpenAPI docs at `/docs`
5. Easier firewall configuration

## Deployment

### Quick Deploy (Recommended)

Run the consolidation script from your Mac:

```bash
# Option 1: Pipe to SSH
ssh tars-pi "bash -s" < scripts/consolidate_daemon_ports.sh

# Option 2: Copy and run
scp scripts/consolidate_daemon_ports.sh tars-pi:~/
ssh tars-pi "bash ~/consolidate_daemon_ports.sh"
```

The script will:
1. Create automatic backup
2. Stop running services
3. Update tars_daemon.py (import dashboard routers, change port)
4. Update dashboard frontend config
5. Rebuild frontend
6. Update startup scripts
7. Test the changes
8. Provide rollback instructions

### Manual Steps

If you prefer manual control:

#### 1. Backup

```bash
ssh tars-pi
cd ~
cp -r tars-daemon tars-daemon-backup-$(date +%Y%m%d)
```

#### 2. Stop Services

```bash
sudo systemctl stop tars
pkill -f tars_daemon.py
pkill -f start_dashboard.py
```

#### 3. Update tars_daemon.py

Edit `/home/mac/tars-daemon/tars_daemon.py`:

**a) Change default port:**

Find:
```python
def __init__(
    self,
    api_port: int = 8001,
```

Change to:
```python
def __init__(
    self,
    api_port: int = 8000,
```

**b) Add dashboard imports (top of file):**

```python
# Dashboard router imports
from dashboard.backend.routes import (
    status as status_routes,
    movements as movements_routes,
    settings as settings_routes,
    updates as updates_routes,
    wifi as wifi_routes,
    apps as apps_routes,
    setup as setup_routes,
)
from dashboard.backend.ws import router as ws_router
```

**c) Register dashboard routers in `_register_routes()` method:**

Add at end of method:
```python
# === Dashboard Routes ===

# Initialize dashboard module references (shared state)
if hasattr(self, 'battery'):
    status_routes.set_modules(
        battery=self.battery,
        display=self.display,
        camera=self.camera,
        webrtc=self.webrtc
    )

if hasattr(self, 'hardware_controller') and self.hardware_controller:
    movements_routes.set_movement_modules(
        movement_map=self.hardware_controller.get_movement_map(),
        servoctl_module=None
    )

# Register dashboard routers
app.include_router(status_routes.router, prefix="/api", tags=["Status"])
app.include_router(movements_routes.router, prefix="/api", tags=["Movements"])
app.include_router(settings_routes.router, prefix="/api", tags=["Settings"])
app.include_router(updates_routes.router, prefix="/api", tags=["Updates"])
app.include_router(wifi_routes.router, prefix="/api", tags=["WiFi"])
app.include_router(apps_routes.router, prefix="/api", tags=["Apps"])
app.include_router(setup_routes.router, prefix="/api", tags=["Setup"])
app.include_router(ws_router, tags=["WebSocket"])
```

**d) Mount static files in `_create_app()` method:**

Add after `self._register_routes(app)`:
```python
# Mount dashboard static files at /dashboard
from pathlib import Path
from fastapi.staticfiles import StaticFiles
dashboard_path = Path(__file__).parent / "dashboard" / "frontend" / "dist"
if dashboard_path.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")
    logger.info(f"Dashboard UI mounted at /dashboard")
else:
    logger.warning(f"Dashboard frontend not found at {dashboard_path}")
```

#### 4. Update Frontend Config

Edit `/home/mac/tars-daemon/dashboard/frontend/vite.config.ts`:

```typescript
export default defineConfig({
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',  // Changed from 8080
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',  // Changed from 8080
        ws: true,
      }
    }
  }
})
```

Rebuild:
```bash
cd ~/tars-daemon/dashboard/frontend
npm run build
```

#### 5. Update Startup Scripts

Edit `/home/mac/tars-daemon/start.sh`:

```bash
#!/bin/bash
# TARS Unified Daemon Startup

cd "$(dirname "$0")"
source venv/bin/activate

# Single process: HTTP (port 8000) + gRPC (port 50051)
python tars_daemon.py "$@"
```

Deprecate `/home/mac/tars-daemon/start_dashboard.py`:

```python
#!/usr/bin/env python3
"""DEPRECATED: Dashboard is now integrated into tars_daemon.py"""
import sys

print("=" * 70)
print("WARNING: Dashboard is now integrated into tars_daemon.py")
print("")
print("  Old: tars_daemon.py (:8001) + start_dashboard.py (:8080)")
print("  New: tars_daemon.py (:8000) - unified")
print("")
print("  Start with: python tars_daemon.py")
print("=" * 70)
sys.exit(1)
```

#### 6. Test

```bash
cd ~/tars-daemon
python tars_daemon.py
```

In another terminal:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/battery
curl http://localhost:8000/docs  # OpenAPI documentation
```

Open in browser: `http://tars.local:8000/dashboard`

#### 7. Restart Service

```bash
sudo systemctl restart tars
sudo systemctl status tars
```

## Verification Checklist

**On Pi:**
- [ ] `curl http://localhost:8000/health` returns daemon info
- [ ] `curl http://localhost:8000/api/battery` returns battery status
- [ ] Dashboard loads at `http://tars.local:8000/dashboard`
- [ ] OpenAPI docs at `http://tars.local:8000/docs`
- [ ] gRPC still running: `grpcurl -plaintext localhost:50051 list`
- [ ] Old ports unused: `netstat -tulpn | grep -E ':(8001|8080)'` (empty)

**From Mac:**
- [ ] `python tars_bot.py` connects successfully
- [ ] WebRTC establishes connection
- [ ] Audio streams bidirectionally
- [ ] Dashboard accessible at `http://tars.local:8000/dashboard`

## Rollback

If consolidation fails:

```bash
ssh tars-pi
sudo systemctl stop tars
cd ~
rm -rf tars-daemon
mv tars-daemon-backup-YYYYMMDD tars-daemon
sudo systemctl start tars
```

Replace `YYYYMMDD` with your backup date.

## Troubleshooting

### Port 8000 already in use

```bash
# Find what's using port 8000
sudo lsof -i :8000
# or
sudo netstat -tulpn | grep :8000

# Kill if needed
sudo kill <PID>
```

### Dashboard not accessible

```bash
# Check if frontend was built
ls -la ~/tars-daemon/dashboard/frontend/dist

# Rebuild if needed
cd ~/tars-daemon/dashboard/frontend
npm install
npm run build
```

### ImportError for dashboard modules

```bash
# Ensure dashboard package is importable
cd ~/tars-daemon
python3 -c "from dashboard.backend.routes import status; print('OK')"

# Check file structure
ls -la dashboard/backend/routes/
```

### Services still on old ports

```bash
# Kill any old processes
pkill -f tars_daemon.py
pkill -f start_dashboard.py

# Verify ports are free
python3 -c "import socket; s=socket.socket(); s.bind(('', 8000)); s.close(); print('Port 8000 free')"

# Restart
sudo systemctl restart tars
```

## URL Migration Reference

| Old URL | New URL | Notes |
|---------|---------|-------|
| `http://tars.local:8001/api/offer` | `http://tars.local:8000/api/offer` | WebRTC signaling |
| `http://tars.local:8001/api/battery` | `http://tars.local:8000/api/battery` | Battery status |
| `http://tars.local:8080/` | `http://tars.local:8000/dashboard` | Dashboard UI |
| `http://tars.local:8080/api/status` | `http://tars.local:8000/api/status` | System status |
| `tars.local:50051` | `tars.local:50051` | gRPC (unchanged) |

## Client Updates

After consolidating the daemon, update clients to use port 8000:

**tars-conversation-app:**

Edit `config.ini`:
```ini
[Connection]
# No manual override needed - defaults to :8000
```

If using manual override:
```ini
# rpi_url = http://tars.local:8000
# rpi_grpc = tars.local:50051
```

The default configuration in `src/config/__init__.py` already uses port 8000 after the update.

## Next Steps

1. Deploy consolidation to Pi
2. Test all endpoints and UI
3. Update systemd service if needed
4. Update firewall rules (remove 8001, 8080)
5. Document new architecture for users
