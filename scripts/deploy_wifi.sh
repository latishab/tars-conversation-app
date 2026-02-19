#!/bin/bash
# Simple WiFi detection deployment for TARS

set -e

PI_HOST="tars-pi"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Deploying WiFi detection to $PI_HOST..."

# Copy files to Pi
echo "Copying files..."
scp "$SCRIPT_DIR/wifi_detector.py" "$PI_HOST:~/tars-daemon/src/modules/"
scp "$SCRIPT_DIR/patch_daemon_wifi.py" "$PI_HOST:~/tars-daemon/"

# Run patcher on Pi
echo "Patching daemon..."
ssh "$PI_HOST" "cd ~/tars-daemon && python3 patch_daemon_wifi.py"

# Restart daemon
echo "Restarting daemon..."
ssh "$PI_HOST" "sudo systemctl restart tars"

echo ""
echo "Done! WiFi indicator should now show connection status."
echo "Check logs: ssh $PI_HOST 'sudo journalctl -u tars -n 50'"
