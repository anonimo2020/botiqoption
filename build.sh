#!/usr/bin/env bash
# build.sh - Script de construcción para Render

echo "=== Starting build process ==="

# Instalar dependencias básicas
echo "Installing base dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Instalar websocket-client específico primero
echo "Installing websocket-client 0.56..."
pip uninstall -y websocket-client
pip install websocket-client==0.56

# Intentar instalar IQOptionAPI de diferentes formas
echo "Installing IQOptionAPI..."

# Método 1: Desde GitHub directamente
if ! pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git; then
    echo "Method 1 failed, trying alternative..."
    
    # Método 2: Descargar y instalar manualmente
    echo "Downloading IQOptionAPI manually..."
    wget https://github.com/Lu-Yi-Hsun/iqoptionapi/archive/master.zip -O iqoptionapi.zip
    unzip -q iqoptionapi.zip
    cd iqoptionapi-master
    python setup.py install
    cd ..
    rm -rf iqoptionapi-master iqoptionapi.zip
fi

# Verificar instalación
echo "Verifying installation..."
python -c "from iqoptionapi.stable_api import IQ_Option; print('✅ IQOptionAPI installed successfully!')" || echo "❌ IQOptionAPI installation failed"

echo "=== Build complete ==="
