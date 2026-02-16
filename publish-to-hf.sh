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
echo "Building React landing page..."
cd landing
npm run build
cd ..

echo "✓ Build complete"
echo
echo "Preparing files for upload..."

# Create staging directory
STAGING_DIR=".hf-staging"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

# Copy app files
rsync -av \
    --exclude='.git' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.models' \
    --exclude='chroma_memory' \
    --exclude='memory_data' \
    --exclude='.env' \
    --exclude='.env.local' \
    --exclude='config.ini' \
    --exclude='.claude' \
    --exclude='.DS_Store' \
    --exclude='landing' \
    --exclude='dist' \
    --exclude='node_modules' \
    --exclude='*.log' \
    --exclude='tests' \
    --exclude='publish-to-hf.sh' \
    --exclude='test-dashboard.sh' \
    --exclude='.hf-*' \
    . "$STAGING_DIR/"

# Copy built landing page to root of staging
cp dist/index.html "$STAGING_DIR/"
cp dist/vite.svg "$STAGING_DIR/"
cp -r dist/assets "$STAGING_DIR/"

# Note: assets/ folder is already copied by rsync above

echo "✓ Staging directory prepared"
echo
echo "Uploading to latishab/tars-conversation-app..."
echo

# Upload
python3 << EOFUPLOAD
import os
from pathlib import Path
from huggingface_hub import HfApi

token = os.environ["HF_TOKEN"]
api = HfApi(token=token)

# Delete unnecessary files from Space if they exist
try:
    print("Removing publish-to-hf.sh from Space...")
    api.delete_file(
        path_in_repo="publish-to-hf.sh",
        repo_id="latishab/tars-conversation-app",
        repo_type="space",
        commit_message="Remove publish script from Space"
    )
    print("✓ Removed publish-to-hf.sh")
except Exception as e:
    print(f"Note: publish-to-hf.sh not found (this is fine)")

# Delete dist/ folder if it exists
try:
    print("Removing dist/ folder from Space...")
    api.delete_folder(
        path_in_repo="dist",
        repo_id="latishab/tars-conversation-app",
        repo_type="space",
        commit_message="Remove dist folder from Space"
    )
    print("✓ Removed dist/ folder")
except Exception as e:
    print(f"Note: dist/ folder not found (this is fine)")

print("\nUploading files...")

api.upload_folder(
    folder_path="$STAGING_DIR",
    repo_id="latishab/tars-conversation-app",
    repo_type="space",
    commit_message="Update: Professional React landing page"
)

print("\n✅ Published successfully!")
print("\nSpace URL: https://huggingface.co/spaces/latishab/tars-conversation-app")
EOFUPLOAD

echo
echo "Cleaning up staging directory..."
rm -rf "$STAGING_DIR"

echo "✓ Cleanup complete"
echo
echo "Done! Visit the Space URL to see your landing page."
