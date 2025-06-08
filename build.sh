#!/usr/bin/env bash
# build.sh - Script de construcción para Render

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing IQOptionAPI from GitHub..."
pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git

echo "Build complete!"
