#!/bin/bash
# Publish tars-conversation-app to HuggingFace Space

set -e

echo "Publishing tars-conversation-app to HuggingFace Space..."
echo

# Check for HF_TOKEN
if [ -z "$HF_TOKEN" ]; then
    echo "❌ Error: HF_TOKEN not set"
    echo
    echo "Get a token from: https://huggingface.co/settings/tokens"
    echo "Then run:"
    echo "  export HF_TOKEN=hf_your_token_here"
    echo "  bash publish-to-hf.sh"
    exit 1
fi

echo "✓ HF_TOKEN is set"

# Check for huggingface_hub
python3 << 'EOFCHECK'
try:
    from huggingface_hub import HfApi
    print("✓ huggingface_hub is installed")
except ImportError:
    print("❌ huggingface_hub not installed")
    print("\nInstall with:")
    print("  pip install huggingface_hub")
    exit(1)
EOFCHECK

if [ $? -ne 0 ]; then
    exit 1
fi

echo
echo "Uploading to latishab/tars-conversation-app..."
echo

# Upload
python3 << 'EOFUPLOAD'
import os
from pathlib import Path
from huggingface_hub import HfApi

token = os.environ["HF_TOKEN"]
api = HfApi(token=token)

print("Uploading files...")

api.upload_folder(
    folder_path=".",
    repo_id="latishab/tars-conversation-app",
    repo_type="space",
    ignore_patterns=[
        ".git", ".git/*",
        "venv", "venv/*",
        "__pycache__", "**/__pycache__",
        "*.pyc", "**/*.pyc",
        ".pytest_cache",
        ".models", ".models/*",
        "chroma_memory", "chroma_memory/*",
        "memory_data", "memory_data/*",
        ".env", ".env.local", ".env.*",
        "config.ini",
        ".claude", ".claude/*",
        ".DS_Store", "**/.DS_Store",
        "space-landing", "space-landing/*",  # Source files (we use dist/)
        "node_modules", "**/node_modules",
        "*.log",
        "tests", "tests/*",
        "scripts", "scripts/*",
        "publish-to-hf.sh",  # Publishing script
        "preview-landing.sh",  # Dev preview script
        "test-dashboard.sh",  # Dev test script
        "start_robot_mode.sh",  # Robot-specific script
        "IMPLEMENTATION_SUMMARY.md",  # Dev documentation
    ],
    commit_message="TARS Conversation App - Professional React landing page"
)

print("\n✅ Published successfully!")
print("\nSpace URL: https://huggingface.co/spaces/latishab/tars-conversation-app")
print("\nNext steps:")
print("1. Visit the Space URL to verify it's working")
print("2. Test installation on TARS robot:")
print("   - Open dashboard at http://your-pi:8000")
print("   - Go to App Store tab")
print("   - Enter Space ID: latishab/tars-conversation-app")
print("   - Click 'Install from HuggingFace'")
print("3. Click Start and verify Gradio dashboard at :7860")
EOFUPLOAD

echo
echo "Done!"
