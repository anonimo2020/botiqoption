#!/usr/bin/env bash
# build.sh - Simplificado para Render

echo "=== Starting build process ==="

# Instala dependencias desde requirements.txt
pip install --upgrade pip
pip install -r requirements.txt

echo "✅ Build completo. Usando iqoptionapi local (no se instalará desde GitHub)."
