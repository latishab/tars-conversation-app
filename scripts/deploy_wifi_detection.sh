#!/bin/bash
# Deploy WiFi detection to TARS daemon on Raspberry Pi

set -e

PI_HOST="tars-pi"
DAEMON_DIR="~/tars-daemon"

echo "========================================"
echo "Deploying WiFi Detection to TARS Daemon"
echo "========================================"

# Test SSH connection
if ! ssh "$PI_HOST" "echo ok" >/dev/null 2>&1; then
    echo "Error: Cannot connect to $PI_HOST"
    exit 1
fi

echo "Connected to $PI_HOST"

# Copy WiFi detector
echo "Copying WiFi detector module..."
scp "$(dirname "$0")/wifi_detector.py" "$PI_HOST:$DAEMON_DIR/src/modules/wifi_detector.py"

# Add WiFi detection to tars_daemon.py
echo "Adding WiFi detection to daemon..."
ssh "$PI_HOST" << 'ENDSSH'
cd ~/tars-daemon

# Create backup
cp tars_daemon.py tars_daemon.py.bak

# Add import at top of file
if ! grep -q "from src.modules.wifi_detector import get_wifi_status" tars_daemon.py; then
    # Find the imports section and add our import
    sed -i '/^from src\.modules\.module_display/a from src.modules.wifi_detector import get_wifi_status' tars_daemon.py
fi

# Add WiFi update method to TarsHardware class
if ! grep -q "def _update_wifi_status" tars_daemon.py; then
    # Find the TarsHardware class and add the method before the run method
    python3 << 'ENDPYTHON'
import re

with open("tars_daemon.py", "r") as f:
    content = f.read()

# Add the WiFi update method after battery update
wifi_method = '''
    def _update_wifi_status(self):
        """Update WiFi status on display."""
        try:
            mode, ssid = get_wifi_status()
            if self.display:
                self.display.set_wifi_status(mode, ssid)
        except Exception as e:
            logger.error(f"WiFi status update failed: {e}")
'''

# Find the end of _update_battery_status and insert after it
pattern = r'(def _update_battery_status\(self\):.*?(?=\n    def |\nclass |\Z))'
match = re.search(pattern, content, re.DOTALL)

if match:
    insert_pos = match.end()
    content = content[:insert_pos] + wifi_method + content[insert_pos:]

    with open("tars_daemon.py", "w") as f:
        f.write(content)
    print("Added _update_wifi_status method")
else:
    print("Could not find insertion point for WiFi method")
ENDPYTHON
fi

# Add WiFi status call to run loop
if ! grep -q "self._update_wifi_status()" tars_daemon.py; then
    # Find where _update_battery_status is called and add WiFi update after it
    sed -i '/self\._update_battery_status()/a \                self._update_wifi_status()' tars_daemon.py
fi

echo "WiFi detection code added successfully"
ENDSSH

# Restart daemon
echo "Restarting daemon..."
ssh "$PI_HOST" "sudo systemctl restart tars"

echo ""
echo "=========================================="
echo "WiFi detection deployed successfully!"
echo "=========================================="
echo ""
echo "The WiFi indicator should now show:"
echo "  - Yellow icon: Hotspot mode"
echo "  - Blue icon: Connected to WiFi"
echo "  - Gray icon: Disconnected"
echo ""
echo "Check logs: ssh $PI_HOST 'sudo journalctl -u tars -f'"
