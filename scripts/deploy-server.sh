#!/usr/bin/env sh
# Image Localization Tool server (Linux): deploy components, then headless API.
set -eu
cd "$(dirname "$0")"
if [ ! -x ./ImageLocalizationTool ]; then
    echo "ImageLocalizationTool binary not found" >&2
    exit 1
fi
echo "Deploying components (models, torch, argos)..."
./ImageLocalizationTool --deploy all
echo "Starting headless server on port 8765 (Ctrl+C to stop)..."
exec ./ImageLocalizationTool --headless --remote
