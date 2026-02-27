#!/bin/bash
# Periodically re-runs split-routes.sh to catch Deepgram DNS rotation.
# Deepgram uses round-robin DNS and rotates IPs frequently; new IPs that
# aren't in the routing table would otherwise go through Tailscale.
#
# Run in background before starting the bot:
#   sudo bash scripts/watch-split-routes.sh &
#
# Routes accumulate in the kernel table (all pointing to the same gateway),
# so there's no harm in adding an IP that's already routed.

INTERVAL=${1:-30}   # re-resolve every N seconds (default: 30)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[watch-split-routes] Starting — interval: ${INTERVAL}s, PID: $$"

while true; do
    bash "$SCRIPT_DIR/split-routes.sh" 2>&1 | grep -v "^$"
    sleep "$INTERVAL"
done
