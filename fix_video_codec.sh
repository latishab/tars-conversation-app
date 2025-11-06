#!/bin/bash
# Fix Video Codec Decoding Issues on macOS
# This script updates ffmpeg/libvpx and reinstalls aiortc with proper linking

set -e

echo "🔧 Fixing Video Codec Decoding Issues..."
echo ""

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo "❌ Homebrew is not installed. Please install it first:"
    echo "   /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi

echo "📦 Step 1: Updating Homebrew and installing/upgrading ffmpeg and libvpx..."
brew update
brew upgrade ffmpeg libvpx || brew install ffmpeg libvpx

echo ""
echo "📦 Step 2: Uninstalling aiortc to force recompilation..."
pip uninstall -y aiortc av 2>/dev/null || true

echo ""
echo "📦 Step 3: Reinstalling aiortc with no cache (forces recompilation)..."
pip install --no-cache-dir aiortc

echo ""
echo "📦 Step 4: Reinstalling pipecat dependencies..."
pip install --no-cache-dir "pipecat-ai[moondream,smallwebrtc]>=0.0.48"

echo ""
echo "✅ Video codec dependencies updated!"
echo ""
echo "⚠️  Important: If you're using a virtual environment, make sure it's activated."
echo "   If issues persist, try creating a fresh virtual environment:"
echo "   python3 -m venv venv"
echo "   source venv/bin/activate"
echo "   pip install -r requirements.txt"
echo ""
echo "🚀 You can now restart your pipecat_service.py server."

