#!/bin/bash
# Check whether all split-routed hosts are currently routed via en0 (not Tailscale).
# Exit code 0 = all routed, 1 = one or more missing/wrong.

HOSTS=(
    "stt-rt.jp.soniox.com"   # Soniox JP WebSocket STT
    "api.elevenlabs.io"       # ElevenLabs TTS
    "api.deepgram.com"        # Deepgram STT WebSocket
)

GATEWAY=$(netstat -rn -f inet 2>/dev/null | awk '/^default/ && $NF == "en0" { print $2; exit }')
if [[ -z "$GATEWAY" ]]; then
    echo "[check] ERROR: no en0 gateway found (WiFi down?)"
    exit 1
fi
echo "[check] en0 gateway: $GATEWAY"
echo ""

all_ok=true

for HOST in "${HOSTS[@]}"; do
    IPS=$(dig +short "$HOST" 2>/dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$')
    if [[ -z "$IPS" ]]; then
        echo "WARN  $HOST — DNS resolution failed, skipping"
        continue
    fi

    for IP in $IPS; do
        route_entry=$(netstat -rn -f inet 2>/dev/null | awk -v ip="$IP" '$1 == ip { print }')
        if [[ -z "$route_entry" ]]; then
            echo "MISS  $HOST ($IP) — no host route"
            all_ok=false
        else
            iface=$(echo "$route_entry" | awk '{ print $NF }')
            gw=$(echo "$route_entry" | awk '{ print $2 }')
            if [[ "$iface" == "en0" ]]; then
                echo "OK    $HOST ($IP) → $gw via en0"
            else
                echo "FAIL  $HOST ($IP) → $gw via $iface (expected en0)"
                all_ok=false
            fi
        fi
    done
done

echo ""
if $all_ok; then
    echo "All routes OK — traffic bypasses Tailscale."
    exit 0
else
    echo "Some routes missing or wrong. Run: sudo bash scripts/split-routes.sh"
    exit 1
fi
