#!/usr/bin/env python3
"""
Complete dashboard integration for TARS daemon.
Integrates dashboard into tars_daemon.py on port 8000 following Reachy Mini pattern.
"""

import subprocess
import sys
from pathlib import Path

def backup_file(filepath):
    """Create backup of file."""
    backup = Path(str(filepath) + '.backup')
    with open(filepath, 'r') as f:
        content = f.read()
    with open(backup, 'w') as f:
        f.write(content)
    return backup

def validate_syntax(filepath):
    """Validate Python syntax."""
    try:
        subprocess.run(['python3', '-m', 'py_compile', filepath],
                      check=True, capture_output=True, text=True)
        return True, None
    except subprocess.CalledProcessError as e:
        return False, e.stderr

def integrate_dashboard(daemon_path):
    """Integrate dashboard into tars_daemon.py."""

    daemon_path = Path(daemon_path)
    if not daemon_path.exists():
        print(f"ERROR: {daemon_path} not found")
        return False

    # Create backup
    backup = backup_file(daemon_path)
    print(f"✓ Created backup: {backup}")

    # Read file
    with open(daemon_path, 'r') as f:
        content = f.read()

    original = content

    # ===== STEP 1: Add imports =====
    print("\n[1/6] Adding dashboard imports...")

    if 'from dashboard.backend.routes import' not in content:
        # Find position after imports (before first class/async def)
        import_section_end = content.find('\n\n# === ')
        if import_section_end < 0:
            import_section_end = content.find('\n\nclass ')
        if import_section_end < 0:
            import_section_end = content.find('\n\nasync def')

        if import_section_end < 0:
            print("ERROR: Could not find insertion point for imports")
            return False

        dashboard_imports = '''
# === Dashboard Integration (Reachy Mini pattern) ===
try:
    from fastapi.staticfiles import StaticFiles
    from fastapi.websockets import WebSocketDisconnect
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
    print(f"[WARN] Dashboard not available: {e}")
    DASHBOARD_AVAILABLE = False

'''
        content = content[:import_section_end] + dashboard_imports + content[import_section_end:]

        with open(daemon_path, 'w') as f:
            f.write(content)

        valid, error = validate_syntax(daemon_path)
        if not valid:
            print(f"ERROR: Syntax error after adding imports:\n{error}")
            with open(daemon_path, 'w') as f:
                f.write(original)
            return False
        print("  ✓ Imports added")
    else:
        print("  ⚠ Imports already present")

    # Re-read
    with open(daemon_path, 'r') as f:
        content = f.read()

    # ===== STEP 2: Change default port =====
    print("\n[2/6] Changing default port to 8000...")

    if 'api_port: int = 8001' in content:
        content = content.replace('api_port: int = 8001', 'api_port: int = 8000')

        with open(daemon_path, 'w') as f:
            f.write(content)

        valid, error = validate_syntax(daemon_path)
        if not valid:
            print(f"ERROR: Syntax error after changing port:\n{error}")
            with open(daemon_path, 'w') as f:
                f.write(original)
            return False
        print("  ✓ Port changed to 8000")
    else:
        print("  ⚠ Port already set to 8000")

    # Re-read
    with open(daemon_path, 'r') as f:
        content = f.read()

    # ===== STEP 3: Initialize ConnectionManager =====
    print("\n[3/6] Initializing ConnectionManager...")

    if 'self.ws_manager = ConnectionManager' not in content:
        # Find self.app = self._create_app() and add before it
        target = '        self.app = self._create_app()'
        if target in content:
            ws_init = '        # Dashboard WebSocket manager\n        self.ws_manager = ConnectionManager() if DASHBOARD_AVAILABLE else None\n\n'
            content = content.replace(target, ws_init + target)

            with open(daemon_path, 'w') as f:
                f.write(content)

            valid, error = validate_syntax(daemon_path)
            if not valid:
                print(f"ERROR: Syntax error after adding ConnectionManager:\n{error}")
                with open(daemon_path, 'w') as f:
                    f.write(original)
                return False
            print("  ✓ ConnectionManager initialized")
        else:
            print("  ERROR: Could not find self.app = self._create_app()")
            return False
    else:
        print("  ⚠ ConnectionManager already initialized")

    # Re-read
    with open(daemon_path, 'r') as f:
        content = f.read()

    # ===== STEP 4: Add dashboard routes in _register_routes =====
    print("\n[4/6] Registering dashboard routes...")

    if 'app.include_router(status_routes.router' not in content:
        # Find the end of _register_routes method (before async def _startup)
        target = '    async def _startup(self):'
        if target in content:
            dashboard_routes = '''
        # === Dashboard Routes ===
        if DASHBOARD_AVAILABLE:
            try:
                # Initialize shared state references
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

                # Register API routers with /api prefix
                app.include_router(status_routes.router, prefix="/api", tags=["Status"])
                app.include_router(movements_routes.router, prefix="/api", tags=["Movements"])
                app.include_router(settings_routes.router, prefix="/api", tags=["Settings"])
                app.include_router(updates_routes.router, prefix="/api", tags=["Updates"])
                app.include_router(wifi_routes.router, prefix="/api", tags=["WiFi"])
                app.include_router(apps_routes.router, prefix="/api", tags=["Apps"])
                app.include_router(setup_routes.router, prefix="/api", tags=["Setup"])

                # WebSocket endpoint
                @app.websocket("/ws")
                async def websocket_endpoint(websocket):
                    \"\"\"Real-time updates via WebSocket.\"\"\"
                    if not self.ws_manager:
                        await websocket.close()
                        return
                    await self.ws_manager.connect(websocket)
                    try:
                        while True:
                            data = await websocket.receive_text()
                            logger.debug(f"WebSocket rx: {data}")
                    except WebSocketDisconnect:
                        self.ws_manager.disconnect(websocket)

                logger.info("✓ Dashboard routes registered")
            except Exception as e:
                logger.error(f"Failed to register dashboard routes: {e}")

    '''
            content = content.replace(target, dashboard_routes + target)

            with open(daemon_path, 'w') as f:
                f.write(content)

            valid, error = validate_syntax(daemon_path)
            if not valid:
                print(f"ERROR: Syntax error after adding routes:\n{error}")
                with open(daemon_path, 'w') as f:
                    f.write(original)
                return False
            print("  ✓ Dashboard routes registered")
        else:
            print("  ERROR: Could not find async def _startup")
            return False
    else:
        print("  ⚠ Dashboard routes already registered")

    # Re-read
    with open(daemon_path, 'r') as f:
        content = f.read()

    # ===== STEP 5: Mount static files =====
    print("\n[5/6] Mounting dashboard static files...")

    if 'app.mount("/dashboard"' not in content:
        # Find self._register_routes(app) and add after
        target = '        self._register_routes(app)'
        if target in content:
            static_mount = '''

        # Mount dashboard UI
        if DASHBOARD_AVAILABLE:
            from pathlib import Path
            dashboard_path = Path(__file__).parent / "dashboard" / "frontend" / "dist"
            if dashboard_path.exists():
                app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")
                logger.info("✓ Dashboard UI: http://0.0.0.0:8000/dashboard")
            else:
                logger.warning(f"Dashboard not built: {dashboard_path}")
                logger.warning("Build with: cd dashboard/frontend && npm run build")
'''
            content = content.replace(target, target + static_mount)

            with open(daemon_path, 'w') as f:
                f.write(content)

            valid, error = validate_syntax(daemon_path)
            if not valid:
                print(f"ERROR: Syntax error after mounting static:\n{error}")
                with open(daemon_path, 'w') as f:
                    f.write(original)
                return False
            print("  ✓ Static files mounted")
        else:
            print("  ERROR: Could not find self._register_routes(app)")
            return False
    else:
        print("  ⚠ Static files already mounted")

    # ===== STEP 6: Update start.sh default port =====
    print("\n[6/6] Updating start.sh...")

    start_sh = daemon_path.parent / "start.sh"
    if start_sh.exists():
        with open(start_sh, 'r') as f:
            start_content = f.read()

        if 'API_PORT=${API_PORT:-8001}' in start_content:
            start_content = start_content.replace(
                'API_PORT=${API_PORT:-8001}',
                'API_PORT=${API_PORT:-8000}'
            )
            with open(start_sh, 'w') as f:
                f.write(start_content)
            print("  ✓ start.sh updated")
        else:
            print("  ⚠ start.sh already set to 8000")
    else:
        print("  ⚠ start.sh not found")

    # Final validation
    print("\n[Final] Validating complete integration...")
    valid, error = validate_syntax(daemon_path)
    if not valid:
        print(f"ERROR: Final syntax check failed:\n{error}")
        with open(daemon_path, 'w') as f:
            f.write(original)
        return False

    print("\n" + "="*70)
    print("✓ DASHBOARD INTEGRATION COMPLETE!")
    print("="*70)
    print("\nUnified daemon on port 8000:")
    print("  - REST API:    http://tars:8000/api/*")
    print("  - Dashboard:   http://tars:8000/dashboard")
    print("  - WebSocket:   ws://tars:8000/ws")
    print("  - gRPC:        tars:50051")
    print("\nNext steps:")
    print("  1. Stop old dashboard: sudo pkill -f start_dashboard.py")
    print("  2. Restart daemon:     sudo systemctl restart tars")
    print("  3. Verify health:      curl http://localhost:8000/health")
    print("  4. Open dashboard:     http://tars:8000/dashboard")
    print()

    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: integrate_dashboard_complete.py <path_to_tars_daemon.py>")
        sys.exit(1)

    success = integrate_dashboard(sys.argv[1])
    sys.exit(0 if success else 1)
