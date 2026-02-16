#!/bin/bash
# TARS Robot Mode Startup Script

echo "╔════════════════════════════════════════════════════════════╗"
echo "║        TARS Omni - Robot Mode Startup                     ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check if config.ini exists
if [ ! -f "config.ini" ]; then
    echo "❌ Error: config.ini not found"
    echo "   Please copy config.ini.example to config.ini and configure it"
    exit 1
fi

# Check connection mode
MODE=$(grep -A1 "\[Connection\]" config.ini | grep "mode" | cut -d'=' -f2 | tr -d ' ')
if [ "$MODE" != "robot" ]; then
    echo "⚠️  Warning: Connection mode is '$MODE', not 'robot'"
    echo "   Set mode=robot in [Connection] section of config.ini"
    read -p "   Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get RPi URL from config
RPI_URL=$(grep -A2 "\[Connection\]" config.ini | grep "rpi_url" | cut -d'=' -f2 | tr -d ' ')
echo "📡 RPi URL: $RPI_URL"
echo ""

# Test RPi connectivity
echo "🔍 Testing RPi connectivity..."
if command -v curl &> /dev/null; then
    if curl -s --max-time 2 "$RPI_URL/health" > /dev/null 2>&1; then
        echo "✅ RPi is reachable"
    else
        echo "⚠️  Warning: Cannot reach RPi at $RPI_URL"
        echo "   Make sure:"
        echo "   1. RPi is powered on"
        echo "   2. tars_daemon.py is running on RPi"
        echo "   3. Network connection is working"
        echo ""
        read -p "   Continue anyway? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi
echo ""

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    echo "🐍 Activating virtual environment..."
    source .venv/bin/activate
fi

# Check if tars_bot.py exists
if [ ! -f "tars_bot.py" ]; then
    echo "❌ Error: tars_bot.py not found"
    exit 1
fi

# Display mode selection
echo "╔════════════════════════════════════════════════════════════╗"
echo "║  Select Mode:                                              ║"
echo "║  1. Test Connection Only (no audio)                        ║"
echo "║  2. Full Robot Mode                                        ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""
read -p "Choice (1/2): " -n 1 -r
echo ""
echo ""

if [[ $REPLY =~ ^1$ ]]; then
    echo "🧪 Running connection test..."
    echo ""
    python test_webrtc_connection.py
else
    echo "🤖 Starting Robot Mode..."
    echo ""
    echo "⚠️  Note: Audio bridge integration is in progress"
    echo "   See IMPLEMENTATION_SUMMARY.md for current status"
    echo ""
    python tars_bot.py
fi
