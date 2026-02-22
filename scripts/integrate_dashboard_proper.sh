#!/bin/bash
# Properly integrate dashboard into tars_daemon.py following Reachy Mini pattern

set -e

DAEMON_PATH="$1"

if [ -z "$DAEMON_PATH" ]; then
    echo "Usage: $0 <path_to_tars_daemon.py>"
    exit 1
fi

if [ ! -f "$DAEMON_PATH" ]; then
    echo "ERROR: File not found: $DAEMON_PATH"
    exit 1
fi

echo "Integrating dashboard into tars_daemon.py..."

# Create Python script to do the integration
python3 << 'EOF'
import sys
import re

DAEMON_PATH = sys.argv[1]

with open(DAEMON_PATH, 'r') as f:
    content = f.read()

# 1. Add dashboard imports after other imports (find the imports section)
dashboard_imports = '''
# Dashboard integration
from fastapi.staticfiles import StaticFiles
from fastapi.websockets import WebSocketDisconnect
try:
    from dashboard.backend.routes import (
        status as status_routes,
        movements as movements_routes,
        settings as settings_routes,
        updates as updates_routes,
        wifi as wifi_routes,
        apps as apps_routes,
        setup as setup_routes,
    )
    from dashboard.backend.ws import ConnectionManager
    DASHBOARD_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Dashboard not available: {e}")
    DASHBOARD_AVAILABLE = False
'''

# Find where to insert imports (after the last 'from' statement before class definitions)
# Look for the pattern of imports ending
import_pattern = r'(from [^\n]+ import [^\n]+\n)(\n+class |asyncio\.run)'
match = re.search(import_pattern, content)
if match and 'dashboard.backend.routes' not in content:
    insert_pos = match.start(2)
    content = content[:insert_pos] + dashboard_imports + '\n' + content[insert_pos:]
    print("✓ Added dashboard imports")
elif 'dashboard.backend.routes' in content:
    print("⚠ Dashboard imports already present")
else:
    print("✗ Could not find import section")
    sys.exit(1)

# 2. Initialize ConnectionManager in __init__
if 'self.ws_manager = ConnectionManager()' not in content:
    init_pattern = r'(def __init__\(self,.*?\):.*?)(self\.app = self\._create_app\(\))'
    match = re.search(init_pattern, content, re.DOTALL)
    if match:
        ws_init = '\n        # WebSocket manager for dashboard\n        self.ws_manager = ConnectionManager() if DASHBOARD_AVAILABLE else None\n        '
        content = content.replace(match.group(2), ws_init + match.group(2))
        print("✓ Added ConnectionManager initialization")
    else:
        print("⚠ Could not find __init__ method")
else:
    print("⚠ ConnectionManager already initialized")

# 3. Add dashboard routes registration in _register_routes (at the end of the method)
dashboard_routes = '''
        # === Dashboard Routes Integration ===
        if DASHBOARD_AVAILABLE:
            try:
                # Initialize dashboard module references (shared state)
                status_routes.set_modules(
                    battery=self.battery if hasattr(self, 'battery') else None,
                    display=self.display if hasattr(self, 'display') else None,
                    camera=self.camera if hasattr(self, 'camera') else None,
                    webrtc=self.webrtc if hasattr(self, 'webrtc') else None
                )

                if hasattr(self, 'hardware_controller') and self.hardware_controller:
                    movements_routes.set_movement_modules(
                        movement_map=self.hardware_controller.get_movement_map(),
                        servoctl_module=None
                    )

                # Register dashboard API routers
                app.include_router(status_routes.router, prefix="/api", tags=["Status"])
                app.include_router(movements_routes.router, prefix="/api", tags=["Movements"])
                app.include_router(settings_routes.router, prefix="/api", tags=["Settings"])
                app.include_router(updates_routes.router, prefix="/api", tags=["Updates"])
                app.include_router(wifi_routes.router, prefix="/api", tags=["WiFi"])
                app.include_router(apps_routes.router, prefix="/api", tags=["Apps"])
                app.include_router(setup_routes.router, prefix="/api", tags=["Setup"])

                # WebSocket endpoint for real-time updates
                @app.websocket("/ws")
                async def websocket_endpoint(websocket):
                    if not self.ws_manager:
                        await websocket.close()
                        return
                    await self.ws_manager.connect(websocket)
                    try:
                        while True:
                            data = await websocket.receive_text()
                            logger.debug(f"WebSocket received: {data}")
                    except WebSocketDisconnect:
                        self.ws_manager.disconnect(websocket)

                logger.info("✓ Dashboard routes registered")
            except Exception as e:
                logger.error(f"Failed to register dashboard routes: {e}")
        else:
            logger.warning("Dashboard not available - skipping route registration")
'''

# Find the end of _register_routes method (before next method definition)
register_routes_pattern = r'(def _register_routes\(self, app: FastAPI\):.*?)(    async def |    def (?!_register))'
match = re.search(register_routes_pattern, content, re.DOTALL)
if match and 'Dashboard Routes Integration' not in content:
    insert_pos = match.start(2)
    content = content[:insert_pos] + '\n' + dashboard_routes + '\n' + content[insert_pos:]
    print("✓ Added dashboard routes registration")
elif 'Dashboard Routes Integration' in content:
    print("⚠ Dashboard routes already registered")
else:
    print("⚠ Could not find _register_routes method end")

# 4. Mount static files in _create_app (after _register_routes call)
static_mount = '''
        # Mount dashboard static files (following Reachy Mini pattern)
        if DASHBOARD_AVAILABLE:
            from pathlib import Path
            dashboard_path = Path(__file__).parent / "dashboard" / "frontend" / "dist"
            if dashboard_path.exists():
                app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")
                logger.info(f"✓ Dashboard UI mounted at /dashboard")
            else:
                logger.warning(f"Dashboard frontend not built at {dashboard_path}")
                logger.warning("Run: cd dashboard/frontend && npm install && npm run build")
'''

create_app_pattern = r'(self\._register_routes\(app\))'
if 'Mount dashboard static files' not in content:
    content = re.sub(create_app_pattern, r'\1\n' + static_mount, content)
    print("✓ Added static files mounting")
else:
    print("⚠ Static files mounting already present")

# Write back
with open(DAEMON_PATH, 'w') as f:
    f.write(content)

print("\n✓ Dashboard integration complete!")

EOF

python3 - "$DAEMON_PATH"

echo ""
echo "Dashboard integration successful!"
echo ""
echo "Next steps:"
echo "1. Build dashboard frontend: cd dashboard/frontend && npm run build"
echo "2. Restart daemon: sudo systemctl restart tars"
echo "3. Access dashboard: http://tars.local:8000/dashboard"
echo ""
