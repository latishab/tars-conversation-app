#!/bin/bash
set -e

APP_NAME="tars-conversation-app"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Installing $APP_NAME ==="
echo "Directory: $APP_DIR"
echo

# Check Python version
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Error: Python $REQUIRED_VERSION or higher required (found $PYTHON_VERSION)"
    exit 1
fi
echo "Python $PYTHON_VERSION OK"
echo

# Install system dependencies
echo "Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y portaudio19-dev ffmpeg build-essential python3-dev python3-venv libspa-0.2-modules pipewire-pulse
echo "System dependencies installed"
echo

# Configure PipeWire echo cancellation
echo "Configuring PipeWire echo cancellation..."

PIPEWIRE_CONFDIR="$HOME/.config/pipewire/pipewire.conf.d"
mkdir -p "$PIPEWIRE_CONFDIR"

# Echo cancel module: monitor.mode taps default sink monitor as AEC reference
# so apps (aplay, aiortc) don't need to route through a virtual sink
cat > "$PIPEWIRE_CONFDIR/60-echo-cancel.conf" << 'PWEOF'
context.modules = [
  { name = libpipewire-module-echo-cancel
    args = {
      library.name  = aec/libspa-aec-webrtc
      monitor.mode  = true
      capture.props = {
        node.name        = "echo-cancel-capture"
        node.description = "Echo Cancellation Capture"
      }
      source.props = {
        node.name        = "echo-cancel-source"
        node.description = "Echo Cancelled Microphone"
        media.class      = "Audio/Source"
      }
      sink.props = {
        node.name        = "echo-cancel-sink"
        node.description = "Echo Cancellation Sink"
      }
      playback.props = {
        node.name        = "echo-cancel-playback"
        node.description = "Echo Cancellation Playback"
      }
    }
  }
]
PWEOF

# Required for headless Pi: allow user services to run without an active login session
loginctl enable-linger "$USER" 2>/dev/null || true

# Systemd service to set echo-cancel-source as default after PipeWire starts.
# context.exec in pipewire-pulse.conf.d fires before echo-cancel-source is loaded,
# so a separate After= unit is more reliable.
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/pipewire-set-default-source.service" << 'SVCEOF'
[Unit]
Description=Set PipeWire default source to echo-cancel-source
After=pipewire-pulse.service wireplumber.service
Wants=pipewire-pulse.service wireplumber.service

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/pactl set-default-source echo-cancel-source
RemainAfterExit=yes

[Install]
WantedBy=default.target
SVCEOF

# Restart PipeWire user services
if command -v systemctl &>/dev/null; then
    systemctl --user daemon-reload
    systemctl --user enable pipewire-set-default-source.service 2>/dev/null || true
    systemctl --user restart pipewire pipewire-pulse wireplumber 2>/dev/null || true

    # Wait up to 10s for echo-cancel-source to appear
    echo "Waiting for echo-cancel-source..."
    for i in $(seq 1 20); do
        sleep 0.5
        if pactl list sources short 2>/dev/null | grep -q "echo-cancel-source"; then
            echo "echo-cancel-source active"
            break
        fi
        if [ "$i" -eq 20 ]; then
            echo "Warning: echo-cancel-source not detected. Verify with: pactl list sources short"
        fi
    done

    systemctl --user start pipewire-set-default-source.service 2>/dev/null || true
fi
echo "PipeWire echo cancellation configured"
echo

# Create virtual environment
if [ ! -d "$APP_DIR/venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$APP_DIR/venv"
    echo "Virtual environment created"
else
    echo "Virtual environment already exists"
fi
echo

# Activate virtual environment
source "$APP_DIR/venv/bin/activate"

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip -q
echo

# Install Python dependencies
echo "Installing Python dependencies..."
echo "This may take several minutes..."
pip install -r "$APP_DIR/requirements.txt" -q
echo "Python dependencies installed"
echo

# Setup configuration files
if [ ! -f "$APP_DIR/config.ini" ]; then
    echo "Creating config.ini from template..."
    cp "$APP_DIR/config.ini.example" "$APP_DIR/config.ini"
    echo "Created config.ini"
    CONFIG_CREATED=true
else
    echo "config.ini already exists"
    CONFIG_CREATED=false
fi
echo

if [ ! -f "$APP_DIR/.env.local" ]; then
    echo "Creating .env.local from template..."
    cp "$APP_DIR/env.example" "$APP_DIR/.env.local"
    echo "Created .env.local"
    ENV_CREATED=true
else
    echo ".env.local already exists"
    ENV_CREATED=false
fi
echo

# Run video codec fix if needed
if [ -f "$APP_DIR/fix_video_codec.sh" ]; then
    echo "Applying video codec fixes..."
    bash "$APP_DIR/fix_video_codec.sh" || true
fi

echo "=== Installation Complete ==="
echo
echo "Next steps:"
if [ "$CONFIG_CREATED" = true ] || [ "$ENV_CREATED" = true ]; then
    echo "1. Edit configuration files:"
    [ "$ENV_CREATED" = true ] && echo "   - Add API keys to: $APP_DIR/.env.local"
    [ "$CONFIG_CREATED" = true ] && echo "   - Configure settings: $APP_DIR/config.ini"
    echo "2. Activate environment: source $APP_DIR/venv/bin/activate"
    echo "3. Run the app: python $APP_DIR/src/tars_bot.py"
else
    echo "1. Activate environment: source $APP_DIR/venv/bin/activate"
    echo "2. Run the app: python $APP_DIR/src/tars_bot.py"
fi
echo
echo "For browser mode: python $APP_DIR/src/bot.py"
echo "For dashboard: python $APP_DIR/ui/app.py"
