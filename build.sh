#!/usr/bin/env bash
# build.sh - Simplificado para Render

echo "=== Starting build process ==="

# Instala dependencias desde requirements.txt
pip install --upgrade pip
pip install -r requirements.txt
pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git

echo "✅ Build completo. Usando iqoptionapi local (no se instalará desde GitHub)."
