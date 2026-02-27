#!/bin/bash
# Bypass Tailscale exit node for latency-sensitive services.
# Routes Soniox JP, ElevenLabs, and Deepgram directly via the real WiFi gateway (en0),
# so traffic doesn't detour through the Singapore exit node.
#
# Run manually:  sudo bash scripts/split-routes.sh
# Auto-install:  sudo bash scripts/install-split-routes.sh

set -uo pipefail

HOSTS=(
    "stt-rt.jp.soniox.com"   # Soniox JP WebSocket STT
    "api.elevenlabs.io"       # ElevenLabs TTS
    "api.deepgram.com"        # Deepgram STT WebSocket
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() { echo "[split-routes] $*"; }

get_gateway() {
    # Find the default gateway on en0 (real WiFi, not Tailscale utun*)
    netstat -rn -f inet 2>/dev/null \
        | awk '/^default/ && $NF == "en0" { print $2; exit }'
}

wait_for_network() {
    local attempts=0
    while [[ $attempts -lt 30 ]]; do
        if [[ -n "$(get_gateway)" ]]; then return 0; fi
        log "Waiting for en0 gateway... (attempt $((attempts+1))/30)"
        sleep 2
        ((attempts++))
    done
    log "ERROR: en0 gateway not available after 60s" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

wait_for_network
GATEWAY=$(get_gateway)
log "Gateway: $GATEWAY (en0)"

for HOST in "${HOSTS[@]}"; do
    # Resolve all A records, skip anything that isn't an IPv4 address
    IPS=$(dig +short "$HOST" 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$')

    if [[ -z "$IPS" ]]; then
        log "WARNING: could not resolve $HOST — skipping"
        continue
    fi

    for IP in $IPS; do
        # Remove stale route if present (ignore errors)
        route -n delete -host "$IP" > /dev/null 2>&1 || true
        # Add direct route via real gateway
        if route add -host "$IP" "$GATEWAY" > /dev/null 2>&1; then
            log "Routed $HOST ($IP) → $GATEWAY"
        else
            log "WARNING: failed to add route for $HOST ($IP)"
        fi
    done
done

log "Done."
