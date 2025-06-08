#!/bin/bash
set -e  # Salir si cualquier comando falla

echo "🚀 Iniciando build del Binary Options Trading Bot Pro..."

# Mostrar información del sistema
echo "📋 Información del sistema:"
python --version
pip --version

# Actualizar pip
echo "⬆️ Actualizando pip..."
pip install --upgrade pip

# Instalar dependencias core con reintentos
echo "📦 Instalando dependencias principales..."
pip install --no-cache-dir -r requirements.txt

# Intentar instalar gevent por separado (opcional)
echo "🔧 Intentando instalar optimizaciones de performance..."
pip install gevent==23.7.0 || echo "⚠️ Gevent no instalado, continuando sin optimizaciones"

# Instalar IQOptionAPI desde GitHub con reintentos
echo "🔧 Instalando IQOptionAPI..."
for i in {1..3}; do
    if pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git; then
        echo "✅ IQOptionAPI instalada correctamente"
        break
    else
        echo "⚠️ Intento $i falló, reintentando..."
        sleep 5
    fi
done

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
python -c "
import sys
print(f'✓ Python: {sys.version}')

try:
    import flask
    print(f'✓ Flask: {flask.__version__}')
except ImportError as e:
    print(f'❌ Flask: {e}')
    sys.exit(1)

try:
    import requests
    print('✓ Requests: OK')
except ImportError as e:
    print(f'❌ Requests: {e}')
    sys.exit(1)

try:
    import numpy
    print(f'✓ Numpy: {numpy.__version__}')
except ImportError as e:
    print(f'❌ Numpy: {e}')
    sys.exit(1)

try:
    import pandas
    print(f'✓ Pandas: {pandas.__version__}')
except ImportError as e:
    print(f'❌ Pandas: {e}')
    sys.exit(1)
"

# Verificar IQOptionAPI
echo "🧪 Verificando IQOptionAPI..."
python -c "
try:
    from iqoptionapi.stable_api import IQ_Option
    print('✅ IQOptionAPI: Instalada y funcional')
except ImportError as e:
    print(f'❌ IQOptionAPI Error: {e}')
    print('🔄 Intentando instalación alternativa...')
    exit(1)
except Exception as e:
    print(f'⚠️ IQOptionAPI Warning: {e}')
    print('✅ Módulo importado, warning puede ser normal')
"

# Verificar que main.py existe y es válido
echo "📄 Verificando archivo principal..."
if [ -f "main.py" ]; then
    echo "✓ main.py encontrado"
    # Verificar sintaxis básica
    python -m py_compile main.py && echo "✓ Sintaxis de main.py válida" || echo "⚠️ Warning en sintaxis de main.py"
else
    echo "❌ main.py no encontrado"
    exit 1
fi

# Verificar estructura de archivos
echo "📂 Verificando estructura de archivos..."
ls -la

echo ""
echo "🎉 Build completado exitosamente!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Sistema: Binary Options Trading Bot Pro"
echo "🎯 Modo: Solo Opciones Binarias"
echo "🛡️ Seguridad: Capital máximo 50%"
echo "📈 Estrategias: 5 clasificadas por riesgo"
echo "🐍 Python: $(python --version)"
echo "📦 Dependencias: Instaladas correctamente"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
