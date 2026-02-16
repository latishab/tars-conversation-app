#!/bin/bash
set -e

APP_NAME="tars-conversation-app"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== Uninstalling $APP_NAME ==="
echo "Directory: $APP_DIR"
echo

# Stop running processes
echo "Stopping running processes..."
pkill -f "python.*tars_bot.py" || true
pkill -f "python.*bot.py" || true
pkill -f "python.*pipecat_service.py" || true
pkill -f "python.*ui/app.py" || true
sleep 1
echo "Processes stopped"
echo

# Remove virtual environment
if [ -d "$APP_DIR/venv" ]; then
    echo "Removing virtual environment..."
    rm -rf "$APP_DIR/venv"
    echo "Virtual environment removed"
else
    echo "No virtual environment found"
fi
echo

# Ask about data directories
echo "The following data directories exist:"
[ -d "$APP_DIR/chroma_memory" ] && echo "  - chroma_memory/ (vector database)"
[ -d "$APP_DIR/memory_data" ] && echo "  - memory_data/ (SQLite memory)"
[ -d "$APP_DIR/__pycache__" ] && echo "  - __pycache__/ (Python cache)"
echo

read -p "Remove data directories? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    [ -d "$APP_DIR/chroma_memory" ] && rm -rf "$APP_DIR/chroma_memory"
    [ -d "$APP_DIR/memory_data" ] && rm -rf "$APP_DIR/memory_data"
    find "$APP_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$APP_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    echo "Data directories removed"
else
    echo "Data directories preserved"
fi
echo

# Ask about configuration
if [ -f "$APP_DIR/config.ini" ] || [ -f "$APP_DIR/.env.local" ]; then
    echo "Configuration files found:"
    [ -f "$APP_DIR/config.ini" ] && echo "  - config.ini"
    [ -f "$APP_DIR/.env.local" ] && echo "  - .env.local"
    echo

    read -p "Remove configuration files? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        [ -f "$APP_DIR/config.ini" ] && rm "$APP_DIR/config.ini"
        [ -f "$APP_DIR/.env.local" ] && rm "$APP_DIR/.env.local"
        echo "Configuration files removed"
    else
        echo "Configuration files preserved"
    fi
fi
echo

echo "=== Uninstall Complete ==="
echo
echo "To reinstall: bash $APP_DIR/install.sh"
