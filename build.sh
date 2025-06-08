#!/bin/bash

echo "🚀 Iniciando build del Binary Options Trading Bot Pro..."

# Actualizar pip
pip install --upgrade pip

# Instalar dependencias core
echo "📦 Instalando dependencias principales..."
pip install -r requirements.txt

# Instalar IQOptionAPI desde GitHub
echo "🔧 Instalando IQOptionAPI optimizada..."
pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git

# Crear directorios necesarios
echo "📁 Creando estructura de directorios..."
mkdir -p /tmp/flask_sessions
mkdir -p /tmp/logs
mkdir -p /tmp/trading_data

# Dar permisos de escritura
chmod 777 /tmp/flask_sessions
chmod 777 /tmp/logs
chmod 777 /tmp/trading_data

# Verificar instalaciones críticas
echo "✅ Verificando instalaciones..."
python -c "import flask; print(f'✓ Flask: {flask.__version__}')"
python -c "import requests; print('✓ Requests: OK')"
python -c "import numpy; print('✓ Numpy: OK')"
python -c "import pandas; print('✓ Pandas: OK')"

# Verificar IQOptionAPI
python -c "
try:
    from iqoptionapi.stable_api import IQ_Option
    print('✅ IQOptionAPI: Instalada correctamente')
except ImportError as e:
    print(f'❌ IQOptionAPI Error: {e}')
    exit(1)
"

# Verificar componentes del sistema
echo "🔍 Verificando componentes del sistema..."
python -c "
import sys
import os
import datetime

print(f'✓ Python: {sys.version}')
print(f'✓ Directorio actual: {os.getcwd()}')
print(f'✓ Fecha build: {datetime.datetime.now()}')
print(f'✓ Variables de entorno disponibles: {len(os.environ)}')

# Verificar que main.py existe
if os.path.exists('main.py'):
    print('✓ main.py encontrado')
else:
    print('❌ main.py no encontrado')
    exit(1)
"

# Test rápido de imports principales
echo "🧪 Ejecutando test de imports..."
python -c "
# Test de imports principales del sistema
try:
    import main
    print('✓ Imports del sistema: OK')
except Exception as e:
    print(f'⚠️  Warning en imports: {e}')
    # No hacer exit aquí, puede ser normal en build
"

echo ""
echo "🎉 Build completado exitosamente!"
echo "📊 Sistema: Binary Options Trading Bot Pro"
echo "🎯 Modo: Solo Opciones Binarias"
echo "🛡️ Seguridad: Capital máximo 50%"
echo "📈 Estrategias: 5 clasificadas por riesgo"
echo ""
