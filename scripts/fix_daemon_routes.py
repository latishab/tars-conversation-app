#!/usr/bin/env python3
"""Fix tars_daemon.py routing issues after consolidation."""

import re
import sys

def fix_daemon_routes(file_path):
    """Fix misplaced dashboard router registration."""

    with open(file_path, 'r') as f:
        content = f.read()

    # Remove the misplaced dashboard routes section (after _shutdown)
    # This pattern finds the wrongly placed dashboard routes
    misplaced_pattern = r'\n\s*# === Dashboard Routes ===\s*\n.*?app\.include_router\(ws_router.*?\)\s*\n'
    content = re.sub(misplaced_pattern, '\n', content, flags=re.DOTALL)

    # Find the end of _register_routes method
    # Look for the method definition and find where it ends (next method or async def)
    register_routes_pattern = r'(def _register_routes\(self, app: FastAPI\):.*?)(\n    async def _startup|$)'
    match = re.search(register_routes_pattern, content, re.DOTALL)

    if not match:
        print("ERROR: Could not find _register_routes method")
        return False

    routes_method = match.group(1)
    rest_of_file = match.group(2)

    # Check if dashboard routes are already there
    if 'app.include_router(status_routes.router' in routes_method:
        print("✓ Dashboard routes already in _register_routes (fixed)")
    else:
        # Add dashboard routes at the end of _register_routes
        dashboard_routes = '''
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
        routes_method = routes_method + dashboard_routes
        content = content.replace(match.group(0), routes_method + rest_of_file)
        print("✓ Dashboard routes added to _register_routes")

    # Write back
    with open(file_path, 'w') as f:
        f.write(content)

    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: fix_daemon_routes.py <path_to_tars_daemon.py>")
        sys.exit(1)

    try:
        if fix_daemon_routes(sys.argv[1]):
            print("✓ Successfully fixed tars_daemon.py")
        else:
            print("✗ Failed to fix tars_daemon.py")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
