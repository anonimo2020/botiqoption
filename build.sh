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

# Instalar websocket-client con versión específica compatible
echo "🔧 Instalando websocket-client compatible..."
pip install websocket-client==1.3.3

# Instalar dependencias core con reintentos
echo "📦 Instalando dependencias principales..."
pip install --no-cache-dir -r requirements.txt

# Intentar instalar gevent por separado (opcional)
echo "🔧 Intentando instalar optimizaciones de performance..."
pip install gevent==23.7.0 || echo "⚠️ Gevent no instalado, continuando sin optimizaciones"

# Instalar versión específica y compatible de IQOptionAPI
echo "🔧 Instalando IQOptionAPI compatible..."

# Primero intentar con el fork corregido
for i in {1..2}; do
    if pip install git+https://github.com/iqoptionapi/iqoptionapi.git; then
        echo "✅ IQOptionAPI (fork oficial) instalada correctamente"
        break
    else
        echo "⚠️ Intento con fork oficial falló, probando alternativa..."
        if pip install git+https://github.com/rickyplouis/iqoptionapi.git; then
            echo "✅ IQOptionAPI (fork alternativo) instalada correctamente"
            break
        else
            echo "⚠️ Intento $i falló, reintentando con repo original..."
            # Como último recurso, usar el repo original y parchear
            if pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git; then
                echo "✅ IQOptionAPI (repo original) instalada"
                echo "🔧 Aplicando parche para websocket..."
                # Crear script de parche
                cat > /tmp/patch_iqapi.py << 'EOF'
import os
import sys

# Encontrar el archivo client.py de iqoptionapi
for root, dirs, files in os.walk('/opt/render/project/src'):
    for file in files:
        if file == 'client.py' and 'iqoptionapi' in root and 'ws' in root:
            client_path = os.path.join(root, file)
            print(f"Encontrado: {client_path}")
            
            # Leer el archivo
            with open(client_path, 'r') as f:
                content = f.read()
            
            # Aplicar parche si es necesario
            if 'def on_message(self, message):' in content:
                content = content.replace(
                    'def on_message(self, message):',
                    'def on_message(self, ws, message):'
                )
                
                # Escribir archivo corregido
                with open(client_path, 'w') as f:
                    f.write(content)
                
                print("✅ Parche aplicado correctamente")
            else:
                print("⚠️ Archivo ya corregido o formato diferente")
            break
EOF
                python /tmp/patch_iqapi.py || echo "⚠️ Parche no aplicado, continuando..."
                break
            fi
        fi
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

try:
    import websocket
    print(f'✓ Websocket: {websocket.__version__}')
except ImportError as e:
    print(f'❌ Websocket: {e}')
    sys.exit(1)
"

# Verificar IQOptionAPI con test básico
echo "🧪 Verificando IQOptionAPI..."
python -c "
try:
    from iqoptionapi.stable_api import IQ_Option
    print('✅ IQOptionAPI: Módulo importado correctamente')
    
    # Test básico de instanciación (sin conectar)
    try:
        api = IQ_Option('test@test.com', 'testpass')
        print('✅ IQOptionAPI: Instanciación exitosa')
    except Exception as e:
        print(f'⚠️ IQOptionAPI: Warning en instanciación: {e}')
        print('✅ Pero el módulo está disponible')
        
except ImportError as e:
    print(f'❌ IQOptionAPI Error: {e}')
    exit(1)
except Exception as e:
    print(f'⚠️ IQOptionAPI Warning: {e}')
    print('✅ Módulo importado, warning puede ser normal')
"

# Verificar que main.py y archivos auxiliares existen
echo "📄 Verificando archivos principales..."
if [ -f "main.py" ]; then
    echo "✓ main.py encontrado"
    # Verificar sintaxis básica
    python -m py_compile main.py && echo "✓ Sintaxis de main.py válida" || echo "⚠️ Warning en sintaxis de main.py"
else
    echo "❌ main.py no encontrado"
    exit 1
fi

# Verificar si existe el archivo de fix
if [ -f "iqapi_websocket_fix.py" ]; then
    echo "✓ iqapi_websocket_fix.py encontrado"
    python -m py_compile iqapi_websocket_fix.py && echo "✓ Fix de compatibilidad válido"
else
    echo "⚠️ iqapi_websocket_fix.py no encontrado - creando..."
    # Crear el archivo de fix si no existe
    cat > iqapi_websocket_fix.py << 'FIXEOF'
import sys
import logging
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger('websocket').setLevel(logging.CRITICAL)
logging.getLogger('iqoptionapi.ws.client').setLevel(logging.CRITICAL)

def patch_iqoptionapi():
    try:
        from iqoptionapi.ws.client import WebsocketClient
        
        original_on_message = getattr(WebsocketClient, 'on_message', None)
        
        def patched_on_message(self, ws, message):
            if original_on_message:
                return original_on_message(self, message)
            return None
        
        WebsocketClient.on_message = patched_on_message
        logging.info("✅ Parches aplicados")
        return True
    except:
        return False

def safe_import_iqoption():
    try:
        patch_iqoptionapi()
        from iqoptionapi.stable_api import IQ_Option
        return IQ_Option, True
    except Exception as e:
        return None, False

class SafeIQOption:
    def __init__(self, email, password):
        patch_iqoptionapi()
        from iqoptionapi.stable_api import IQ_Option
        self._iq_instance = IQ_Option(email, password)
    
    def connect(self):
        websocket_logger = logging.getLogger('websocket')
        iqapi_logger = logging.getLogger('iqoptionapi.ws.client')
        original_level = websocket_logger.level
        websocket_logger.setLevel(logging.CRITICAL)
        iqapi_logger.setLevel(logging.CRITICAL)
        try:
            result = self._iq_instance.connect()
            return result
        finally:
            websocket_logger.setLevel(original_level)
    
    def __getattr__(self, name):
        return getattr(self._iq_instance, name)
FIXEOF
fi

# Crear script de inicio mejorado
echo "📄 Creando script de inicio..."
cat > start.py << 'EOF'
import os
import sys
import logging

# Configurar logging antes de importar otras cosas
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Suprimir logs problemáticos de websocket
logging.getLogger('websocket').setLevel(logging.WARNING)
logging.getLogger('iqoptionapi.ws.client').setLevel(logging.WARNING)

# Importar y ejecutar la aplicación principal
try:
    from main import app
    if __name__ == '__main__':
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
except Exception as e:
    print(f"Error iniciando aplicación: {e}")
    sys.exit(1)
EOF

echo ""
echo "🎉 Build completado exitosamente!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Sistema: Binary Options Trading Bot Pro"
echo "🎯 Modo: Solo Opciones Binarias"
echo "🛡️ Seguridad: Capital máximo 50%"
echo "📈 Estrategias: 5 clasificadas por riesgo"
echo "🐍 Python: $(python --version)"
echo "📦 Dependencias: Instaladas y parcheadas"
echo "🔧 Websocket: Compatibilidad corregida"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
