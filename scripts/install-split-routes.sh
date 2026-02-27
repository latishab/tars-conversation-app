#!/bin/bash
# Installs split-routes as a LaunchDaemon so it runs automatically
# at boot and whenever the network changes (resolv.conf is updated).
#
# Usage: sudo bash scripts/install-split-routes.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/com.tars.split-routes.plist"
PLIST_DST="/Library/LaunchDaemons/com.tars.split-routes.plist"
SCRIPT="$SCRIPT_DIR/split-routes.sh"

if [[ "$EUID" -ne 0 ]]; then
    echo "Run with sudo: sudo bash scripts/install-split-routes.sh"
    exit 1
fi

chmod +x "$SCRIPT"

# Unload existing job if present
if launchctl list | grep -q "com.tars.split-routes"; then
    echo "Unloading existing job..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

cp "$PLIST_SRC" "$PLIST_DST"
chown root:wheel "$PLIST_DST"
chmod 644 "$PLIST_DST"

launchctl load "$PLIST_DST"

echo "Installed. Running now..."
bash "$SCRIPT"
echo ""
echo "Logs: tail -f /tmp/tars-split-routes.log"
