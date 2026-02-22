#!/usr/bin/env python3
"""
Minimal dashboard integration following Reachy Mini pattern.
Makes surgical changes to tars_daemon.py with syntax validation.
"""

import re
import sys
import subprocess
from pathlib import Path

def validate_python_syntax(filepath):
    """Validate Python file syntax."""
    try:
        subprocess.run(['python3', '-m', 'py_compile', filepath],
                      check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Syntax error: {e.stderr.decode()}")
        return False

def integrate_dashboard(daemon_path):
    """Integrate dashboard into tars_daemon.py."""

    daemon_path = Path(daemon_path)
    if not daemon_path.exists():
        print(f"ERROR: {daemon_path} not found")
        return False

    # Read file
    with open(daemon_path, 'r') as f:
        lines = f.readlines()

    content = ''.join(lines)
    original_content = content

    print("Step 1: Add imports...")
    # Find last import and add dashboard imports after it
    if 'from dashboard.backend' not in content:
        # Find the last 'from' or 'import' statement
        last_import_idx = max(
            (i for i, line in enumerate(lines)
             if line.strip().startswith(('from ', 'import ')) and not line.strip().startswith('#')),
            default=-1
        )

        if last_import_idx >= 0:
            # Insert after the last import with blank line
            dashboard_imports = '''
# Dashboard integration (following Reachy Mini pattern)
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
    print(f"Dashboard not available: {e}")
    DASHBOARD_AVAILABLE = False

'''
            lines.insert(last_import_idx + 1, dashboard_imports)
            print("✓ Added dashboard imports")
        else:
            print("ERROR: Could not find import section")
            return False
    else:
        print("⚠ Dashboard imports already present")

    # Write and validate
    with open(daemon_path, 'w') as f:
        f.writelines(lines)

    if not validate_python_syntax(daemon_path):
        print("ERROR: Syntax error after adding imports")
        with open(daemon_path, 'w') as f:
            f.write(original_content)
        return False

    # Re-read for next step
    with open(daemon_path, 'r') as f:
        content = f.read()

    print("\nStep 2: Initialize ConnectionManager...")
    if 'self.ws_manager' not in content:
        # Find self.app = self._create_app() and add ws_manager before it
        content = re.sub(
            r'(        )(self\.app = self\._create_app\(\))',
            r'\1self.ws_manager = ConnectionManager() if DASHBOARD_AVAILABLE else None\n        \2',
            content
        )
        with open(daemon_path, 'w') as f:
            f.write(content)

        if not validate_python_syntax(daemon_path):
            print("ERROR: Syntax error after adding ConnectionManager")
            with open(daemon_path, 'w') as f:
                f.write(original_content)
            return False
        print("✓ Added ConnectionManager initialization")
    else:
        print("⚠ ConnectionManager already initialized")

    print("\nStep 3: Mount static files...")
    if 'Mount dashboard static' not in content:
        # Find self._register_routes(app) and add mounting after
        static_mount = '''
        # Mount dashboard static files (following Reachy Mini pattern)
        if DASHBOARD_AVAILABLE:
            from pathlib import Path
            dashboard_path = Path(__file__).parent / "dashboard" / "frontend" / "dist"
            if dashboard_path.exists():
                app.mount("/dashboard", StaticFiles(directory=str(dashboard_path), html=True), name="dashboard")
                logger.info("✓ Dashboard UI mounted at http://localhost:8000/dashboard")
            else:
                logger.warning(f"Dashboard frontend not built at {dashboard_path}")
'''
        content = re.sub(
            r'(        self\._register_routes\(app\))',
            r'\1\n' + static_mount,
            content
        )

        with open(daemon_path, 'w') as f:
            f.write(content)

        if not validate_python_syntax(daemon_path):
            print("ERROR: Syntax error after mounting static files")
            with open(daemon_path, 'w') as f:
                f.write(original_content)
            return False
        print("✓ Added static file mounting")
    else:
        print("⚠ Static file mounting already present")

    print("\n✓ Dashboard integration complete!")
    print("\nThe dashboard frontend will be available at: http://tars:8000/dashboard")
    print("Dashboard API routes remain on port 8080 for now (phase 2 will integrate them)")

    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: integrate_dashboard_minimal.py <path_to_tars_daemon.py>")
        sys.exit(1)

    success = integrate_dashboard(sys.argv[1])
    sys.exit(0 if success else 1)
