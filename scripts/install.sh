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
sudo apt-get install -y portaudio19-dev ffmpeg build-essential python3-dev python3-venv
echo "System dependencies installed"
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
    echo "3. Run the app: python $APP_DIR/tars_bot.py"
else
    echo "1. Activate environment: source $APP_DIR/venv/bin/activate"
    echo "2. Run the app: python $APP_DIR/tars_bot.py"
fi
echo
echo "For browser mode: python $APP_DIR/bot.py"
echo "For dashboard: python $APP_DIR/ui/app.py"
