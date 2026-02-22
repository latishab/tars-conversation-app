#!/bin/bash
# TARS Daemon Port Consolidation Script
# Consolidates 3 ports (8001, 8080, 50051) to 2 ports (8000, 50051)
#
# Usage:
#   ssh tars-pi "bash -s" < scripts/consolidate_daemon_ports.sh
#   OR
#   scp scripts/consolidate_daemon_ports.sh tars-pi:~/
#   ssh tars-pi "bash ~/consolidate_daemon_ports.sh"

set -e  # Exit on error

DAEMON_DIR="/home/mac/tars-daemon"
BACKUP_DIR="/home/mac/tars-daemon-backup-$(date +%Y%m%d-%H%M%S)"

echo "======================================================================="
echo "TARS Daemon Port Consolidation: 3 Ports → 2 Ports"
echo "======================================================================="
echo ""
echo "Target architecture:"
echo "  Port 8000: Unified HTTP (WebRTC + Dashboard + REST API)"
echo "  Port 50051: gRPC (hardware control)"
echo ""

# Check if daemon directory exists
if [ ! -d "$DAEMON_DIR" ]; then
    echo "ERROR: Daemon directory not found at $DAEMON_DIR"
    exit 1
fi

# Backup current daemon
echo "Creating backup at $BACKUP_DIR..."
cp -r "$DAEMON_DIR" "$BACKUP_DIR"
echo "✓ Backup created"
echo ""

cd "$DAEMON_DIR"

# Stop running services
echo "Stopping TARS services..."
sudo systemctl stop tars 2>/dev/null || true
pkill -f tars_daemon.py 2>/dev/null || true
pkill -f start_dashboard.py 2>/dev/null || true
sleep 2
echo "✓ Services stopped"
echo ""

# Phase 1: Update tars_daemon.py
echo "Phase 1: Updating tars_daemon.py..."

# Check if file exists
if [ ! -f "tars_daemon.py" ]; then
    echo "ERROR: tars_daemon.py not found"
    exit 1
fi

# Create Python script to modify tars_daemon.py
cat > /tmp/patch_daemon.py << 'PYTHON_SCRIPT'
#!/usr/bin/env python3
"""Patch tars_daemon.py to integrate dashboard routers."""

import re
import sys

def patch_daemon(file_path):
    with open(file_path, 'r') as f:
        content = f.read()

    original_content = content

    # 1. Update default port from 8001 to 8000
    content = re.sub(
        r'api_port: int = 8001',
        r'api_port: int = 8000',
        content
    )

    # 2. Add dashboard router imports (after other imports)
    if 'from dashboard.backend.routes import' not in content:
        # Find the last import statement
        import_section = re.search(r'(from\s+\w+.*\n)+', content)
        if import_section:
            last_import_pos = import_section.end()
            dashboard_imports = '''
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
'''
            content = content[:last_import_pos] + dashboard_imports + content[last_import_pos:]

    # 3. Add dashboard router registration in _register_routes
    if 'app.include_router(status_routes.router' not in content:
        # Find _register_routes method
        register_routes_match = re.search(
            r'(def _register_routes\(self, app: FastAPI\):.*?)(\n    def |\Z)',
            content,
            re.DOTALL
        )

        if register_routes_match:
            routes_method = register_routes_match.group(1)
            next_method = register_routes_match.group(2)

            # Add dashboard router registration at the end of the method
            dashboard_registration = '''
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
'''

            new_routes_method = routes_method + dashboard_registration
            content = content.replace(routes_method + next_method, new_routes_method + next_method)

    # 4. Add static file mounting in _create_app
    if 'Mount dashboard static files' not in content:
        create_app_match = re.search(
            r'(def _create_app\(self\).*?self\._register_routes\(app\))',
            content,
            re.DOTALL
        )

        if create_app_match:
            create_app_section = create_app_match.group(1)

            static_mount = '''

        # Mount dashboard static files at /dashboard
        from pathlib import Path
        from fastapi.staticfiles import StaticFiles
        dashboard_path = Path(__file__).parent / "dashboard" / "frontend" / "dist"
        if dashboard_path.exists():
            app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")
            logger.info(f"Dashboard UI mounted at /dashboard")
        else:
            logger.warning(f"Dashboard frontend not found at {dashboard_path}")'''

            new_create_app = create_app_section + static_mount
            content = content.replace(create_app_section, new_create_app)

    # Only write if changes were made
    if content != original_content:
        with open(file_path, 'w') as f:
            f.write(content)
        print("✓ tars_daemon.py patched successfully")
        return True
    else:
        print("⚠ No changes needed in tars_daemon.py (may already be patched)")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: patch_daemon.py <path_to_tars_daemon.py>")
        sys.exit(1)

    try:
        patch_daemon(sys.argv[1])
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
PYTHON_SCRIPT

chmod +x /tmp/patch_daemon.py
python3 /tmp/patch_daemon.py tars_daemon.py
echo ""

# Phase 2: Update dashboard frontend config
echo "Phase 2: Updating dashboard frontend config..."

if [ -f "dashboard/frontend/vite.config.ts" ]; then
    # Update proxy target from 8080 to 8000
    sed -i "s|target: 'http://localhost:8080'|target: 'http://localhost:8000'|g" dashboard/frontend/vite.config.ts
    sed -i "s|target: 'ws://localhost:8080'|target: 'ws://localhost:8000'|g" dashboard/frontend/vite.config.ts
    echo "✓ vite.config.ts updated"

    # Rebuild frontend
    echo "Rebuilding dashboard frontend..."
    cd dashboard/frontend
    if [ -d "node_modules" ]; then
        npm run build
        echo "✓ Frontend rebuilt"
    else
        echo "⚠ node_modules not found, skipping frontend build"
        echo "  Run manually: cd dashboard/frontend && npm install && npm run build"
    fi
    cd "$DAEMON_DIR"
else
    echo "⚠ vite.config.ts not found, skipping frontend update"
fi
echo ""

# Phase 3: Update startup scripts
echo "Phase 3: Updating startup scripts..."

# Update start.sh to remove separate dashboard startup
if [ -f "start.sh" ]; then
    cat > start.sh << 'STARTSH'
#!/bin/bash
# TARS Unified Daemon Startup

cd "$(dirname "$0")"
source venv/bin/activate

# Single process: HTTP (port 8000) + gRPC (port 50051)
python tars_daemon.py "$@"
STARTSH
    chmod +x start.sh
    echo "✓ start.sh updated"
else
    echo "⚠ start.sh not found"
fi

# Deprecate start_dashboard.py
if [ -f "start_dashboard.py" ]; then
    cat > start_dashboard.py << 'DEPRECATED'
#!/usr/bin/env python3
"""
DEPRECATED: Dashboard is now integrated into tars_daemon.py
"""
import sys

print("=" * 70)
print("WARNING: Dashboard is now integrated into tars_daemon.py")
print("")
print("  Old architecture (3 ports):")
print("    - tars_daemon.py → :8001")
print("    - start_dashboard.py → :8080")
print("    - gRPC → :50051")
print("")
print("  New architecture (2 ports):")
print("    - tars_daemon.py → :8000 (HTTP + WebRTC + Dashboard)")
print("    - gRPC → :50051")
print("")
print("  Start with: python tars_daemon.py")
print("=" * 70)
sys.exit(1)
DEPRECATED
    chmod +x start_dashboard.py
    echo "✓ start_dashboard.py deprecated"
else
    echo "⚠ start_dashboard.py not found"
fi
echo ""

# Phase 4: Verify port availability
echo "Phase 4: Verifying port 8000 is available..."
if python3 -c "import socket; s=socket.socket(); s.bind(('', 8000)); s.close()" 2>/dev/null; then
    echo "✓ Port 8000 is available"
else
    echo "⚠ Port 8000 may be in use"
fi
echo ""

# Phase 5: Test unified daemon (optional)
echo "Phase 5: Testing unified daemon..."
echo "Starting daemon for 10 seconds to test..."

timeout 10 python3 tars_daemon.py &
DAEMON_PID=$!
sleep 5

# Test endpoints
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✓ Health endpoint working (port 8000)"
else
    echo "⚠ Health endpoint not responding"
fi

if [ -d "dashboard/frontend/dist" ]; then
    if curl -s http://localhost:8000/dashboard > /dev/null 2>&1; then
        echo "✓ Dashboard UI accessible"
    else
        echo "⚠ Dashboard UI not accessible"
    fi
fi

# Stop test daemon
kill $DAEMON_PID 2>/dev/null || true
wait $DAEMON_PID 2>/dev/null || true
sleep 2
echo ""

# Summary
echo "======================================================================="
echo "Port Consolidation Complete!"
echo "======================================================================="
echo ""
echo "Changes made:"
echo "  ✓ Updated tars_daemon.py default port: 8001 → 8000"
echo "  ✓ Integrated dashboard routers into daemon"
echo "  ✓ Mounted dashboard static files at /dashboard"
echo "  ✓ Updated frontend proxy configuration"
echo "  ✓ Updated startup scripts"
echo "  ✓ Deprecated start_dashboard.py"
echo ""
echo "New architecture:"
echo "  Port 8000: HTTP + WebRTC + Dashboard + REST API"
echo "  Port 50051: gRPC (hardware control)"
echo ""
echo "Backup location: $BACKUP_DIR"
echo ""
echo "To start daemon:"
echo "  sudo systemctl start tars"
echo "  OR"
echo "  python tars_daemon.py"
echo ""
echo "Verify endpoints:"
echo "  curl http://localhost:8000/health"
echo "  curl http://localhost:8000/api/battery"
echo "  Open http://tars.local:8000/dashboard"
echo ""
echo "To rollback if needed:"
echo "  sudo systemctl stop tars"
echo "  rm -rf $DAEMON_DIR"
echo "  mv $BACKUP_DIR $DAEMON_DIR"
echo "  sudo systemctl start tars"
echo ""
