#!/usr/bin/env python3
"""
Patch TARS daemon to add WiFi status detection.

This script modifies tars_daemon.py on the Raspberry Pi to periodically
update the display with WiFi connection status.
"""

import re
import shutil
from pathlib import Path


def patch_daemon():
    """Add WiFi detection to tars_daemon.py."""
    daemon_file = Path.home() / "tars-daemon" / "tars_daemon.py"

    if not daemon_file.exists():
        print(f"Error: {daemon_file} not found")
        return False

    # Read current content
    with open(daemon_file, "r") as f:
        content = f.read()

    # Create backup
    backup_file = daemon_file.with_suffix(".py.bak")
    shutil.copy2(daemon_file, backup_file)
    print(f"Backup created: {backup_file}")

    modified = False

    # 1. Add import for get_wifi_status
    if "from src.modules.wifi_detector import get_wifi_status" not in content:
        # Find the module_display import and add after it
        import_pattern = r"(from src\.modules\.module_display import .*)\n"
        replacement = r"\1\nfrom src.modules.wifi_detector import get_wifi_status\n"
        content = re.sub(import_pattern, replacement, content)
        modified = True
        print("Added WiFi detector import")

    # 2. Add _update_wifi_display method to TarsHardware class
    if "def _update_wifi_display" not in content:
        wifi_method = '''    async def _update_wifi_display(self):
        """Periodically update WiFi display"""
        while self._running:
            try:
                if self.display:
                    mode, ssid = get_wifi_status()
                    self.display.set_wifi_status(mode, ssid)
                await asyncio.sleep(5.0)  # Update every 5 seconds
            except Exception as e:
                logger.error(f"WiFi display update error: {e}")
                await asyncio.sleep(10.0)

'''
        # Find _update_battery_display method and add WiFi method after it
        pattern = r'(    async def _update_battery_display\(self\):.*?(?=\n    def |\n    async def |\nclass |\Z))'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + "\n" + wifi_method + content[insert_pos:]
            modified = True
            print("Added _update_wifi_display method")
        else:
            print("Warning: Could not find _update_battery_display method")

    # 3. Start WiFi update task in __init__
    if "asyncio.create_task(self._update_wifi_display())" not in content:
        # Find where battery display task is created and add WiFi task on same line
        pattern = r'(                        asyncio\.create_task\(self\._update_battery_display\(\)\))'
        if re.search(pattern, content):
            content = re.sub(
                pattern,
                r'\1\n                        asyncio.create_task(self._update_wifi_display())',
                content
            )
            modified = True
            print("Added WiFi display task to startup")
        else:
            print("Warning: Could not find battery display task creation")

    if modified:
        # Write modified content
        with open(daemon_file, "w") as f:
            f.write(content)
        print(f"\nSuccessfully patched {daemon_file}")
        print("Restart the daemon to apply changes:")
        print("  sudo systemctl restart tars")
        return True
    else:
        print("\nNo changes needed - WiFi detection already present")
        return True


if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("TARS Daemon WiFi Detection Patcher")
    print("=" * 60)

    success = patch_daemon()
    sys.exit(0 if success else 1)
