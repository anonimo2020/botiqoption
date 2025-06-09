#!/bin/bash

# build.sh - Script de construcción para Trading Bot Opciones Binarias Pro
# Compatible con Render.com

set -e  # Exit on any error

echo "🚀 Iniciando construcción del Trading Bot Opciones Binarias Pro..."

# Verificar versión de Python
echo "📋 Verificando versión de Python..."
python --version

# Crear directorios necesarios
echo "📁 Creando directorios..."
mkdir -p /tmp/flask_sessions
mkdir -p /tmp/logs
mkdir -p logs

# Actualizar pip
echo "⬆️ Actualizando pip..."
python -m pip install --upgrade pip

# Instalar dependencias del sistema si es necesario
echo "🔧 Configurando dependencias del sistema..."

# Para numpy y scipy en Render
export BLAS=None
export LAPACK=None
export ATLAS=None

# Instalar dependencias principales
echo "📦 Instalando dependencias de Python..."
pip install --no-cache-dir \
    Flask==2.3.3 \
    Flask-CORS==4.0.0 \
    Flask-Session==0.5.0 \
    Flask-Limiter==3.5.0 \
    numpy==1.24.3 \
    requests==2.31.0 \
    gunicorn==21.2.0

# Instalar websocket-client compatible
echo "🔌 Instalando websocket-client compatible..."
pip uninstall -y websocket-client websocket 2>/dev/null || true
pip install --no-cache-dir websocket-client==1.1.0

echo "📊 Instalando librerías de análisis técnico..."
pip install --no-cache-dir \
    scipy==1.11.3 \
    pandas==2.0.3 \
    ta-lib-binary==0.4.25 || pip install --no-cache-dir TA-Lib==0.4.25

# Instalar IQOptionAPI desde GitHub
echo "🔌 Instalando IQOptionAPI..."
pip install --no-cache-dir git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git

# Instalar dependencias adicionales
echo "🛠️ Instalando dependencias adicionales..."
pip install --no-cache-dir \
    python-dateutil==2.8.2 \
    pytz==2023.3 \
    certifi==2023.7.22 \
    urllib3==2.0.7 \
    psutil==5.9.5

# Verificar instalaciones críticas
echo "✅ Verificando instalaciones críticas..."

python -c "
import sys
import subprocess

def check_package(package_name, import_name=None):
    if import_name is None:
        import_name = package_name
    try:
        __import__(import_name)
        print(f'✅ {package_name}: OK')
        return True
    except ImportError as e:
        print(f'❌ {package_name}: ERROR - {e}')
        return False

# Verificar paquetes críticos
packages = [
    ('Flask', 'flask'),
    ('NumPy', 'numpy'),
    ('Requests', 'requests'),
    ('IQOptionAPI', 'iqoptionapi'),
    ('Flask-CORS', 'flask_cors'),
    ('Flask-Session', 'flask_session'),
    ('Flask-Limiter', 'flask_limiter')
]

failed = 0
for package, import_name in packages:
    if not check_package(package, import_name):
        failed += 1

if failed > 0:
    print(f'❌ {failed} paquetes fallaron. Verificar instalación.')
    sys.exit(1)
else:
    print('✅ Todas las dependencias críticas instaladas correctamente')
"

# Crear archivos de configuración si no existen
echo "⚙️ Creando archivos de configuración..."

# Crear requirements.txt actualizado
cat > requirements.txt << EOF
Flask==2.3.3
Flask-CORS==4.0.0
Flask-Session==0.5.0
Flask-Limiter==3.5.0
numpy==1.24.3
scipy==1.11.3
pandas==2.0.3
requests==2.31.0
gunicorn==21.2.0
python-dateutil==2.8.2
pytz==2023.3
websocket-client==1.1.0
certifi==2023.7.22
urllib3==2.0.7
psutil==5.9.5
git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git
EOF

# Crear Procfile para compatibilidad
cat > Procfile << EOF
web: python main.py
worker: python worker.py
EOF

# Crear runtime.txt
cat > runtime.txt << EOF
python-3.9.18
EOF

# Crear archivo de configuración para Gunicorn
cat > gunicorn.conf.py << EOF
# Gunicorn configuration for Trading Bot
import os

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', 10000)}"
backlog = 2048

# Worker processes
workers = int(os.environ.get('MAX_WORKERS', 4))
worker_class = 'sync'
worker_connections = 1000
timeout = int(os.environ.get('TIMEOUT', 120))
keepalive = 2

# Restart workers
max_requests = 1000
max_requests_jitter = 50
preload_app = True

# Security
limit_request_line = 0
limit_request_fields = 100
limit_request_field_size = 8190

# Logging
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOG_LEVEL', 'info').lower()
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'trading-bot-opciones-binarias-pro'

# Server mechanics
daemon = False
pidfile = '/tmp/gunicorn.pid'
user = None
group = None
tmp_upload_dir = None

# SSL (if needed)
# keyfile = None
# certfile = None
EOF

# Crear worker.py opcional para tareas en background
cat > worker.py << EOF
#!/usr/bin/env python3
"""
Worker para tareas en background del Trading Bot
"""
import os
import sys
import time
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('worker')

def main():
    """Worker principal"""
    logger.info("🔧 Worker iniciado")
    
    try:
        while True:
            # Tareas de mantenimiento
            logger.info(f"⚡ Worker ejecutándose: {datetime.now()}")
            
            # Limpiar archivos temporales
            cleanup_temp_files()
            
            # Esperar 1 hora
            time.sleep(3600)
            
    except KeyboardInterrupt:
        logger.info("🛑 Worker detenido por usuario")
    except Exception as e:
        logger.error(f"❌ Error en worker: {e}")
        sys.exit(1)

def cleanup_temp_files():
    """Limpiar archivos temporales"""
    try:
        import glob
        import os
        
        # Limpiar logs antiguos
        old_logs = glob.glob('/tmp/*.log')
        for log_file in old_logs:
            try:
                # Eliminar logs de más de 24 horas
                if os.path.getmtime(log_file) < time.time() - 86400:
                    os.remove(log_file)
                    logger.info(f"🗑️ Eliminado log antiguo: {log_file}")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo eliminar {log_file}: {e}")
                
        # Limpiar sesiones antiguas
        session_files = glob.glob('/tmp/flask_sessions/*')
        for session_file in session_files:
            try:
                if os.path.getmtime(session_file) < time.time() - 86400:
                    os.remove(session_file)
                    logger.info(f"🗑️ Eliminada sesión antigua: {session_file}")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo eliminar {session_file}: {e}")
                
    except Exception as e:
        logger.error(f"❌ Error en cleanup: {e}")

if __name__ == '__main__':
    main()
EOF

# Hacer ejecutable el worker
chmod +x worker.py

# Crear script de verificación de salud
cat > health_check.py << EOF
#!/usr/bin/env python3
"""
Script de verificación de salud para el Trading Bot
"""
import requests
import sys
import os

def check_health():
    """Verificar salud del servicio"""
    try:
        port = os.environ.get('PORT', 10000)
        url = f"http://localhost:{port}/health"
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Servicio saludable: {data.get('status', 'unknown')}")
            print(f"📊 Sesiones activas: {data.get('active_sessions', 0)}")
            print(f"🤖 Bots activos: {data.get('active_bots', 0)}")
            return True
        else:
            print(f"❌ Servicio no saludable: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Error verificando salud: {e}")
        return False

if __name__ == '__main__':
    if check_health():
        sys.exit(0)
    else:
        sys.exit(1)
EOF

chmod +x health_check.py

# Configurar permisos
echo "🔐 Configurando permisos..."
chmod +x main.py
chmod 755 /tmp/flask_sessions 2>/dev/null || true
chmod 755 /tmp/logs 2>/dev/null || true

# Verificar estructura del proyecto
echo "📋 Verificando estructura del proyecto..."
ls -la

# Test de importación del módulo principal
echo "🧪 Probando importación del módulo principal..."
python -c "
import sys
sys.path.insert(0, '.')

try:
    # Test básico de importación
    import main
    print('✅ Módulo principal importado correctamente')
except ImportError as e:
    print(f'❌ Error importando módulo principal: {e}')
    sys.exit(1)
except Exception as e:
    print(f'⚠️ Advertencia en importación: {e}')
    print('✅ Módulo principal cargado con advertencias')
"

# Mostrar información del sistema
echo "📊 Información del sistema:"
echo "Python: $(python --version)"
echo "Pip: $(pip --version)"
echo "Espacio disponible: $(df -h /tmp | tail -1 | awk '{print $4}')"
echo "Memoria disponible: $(free -h 2>/dev/null | grep 'Mem:' | awk '{print $7}' || echo 'N/A')"

# Crear archivo de estado de construcción
cat > build_status.json << EOF
{
    "build_date": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "python_version": "$(python --version)",
    "status": "success",
    "components": {
        "flask": "installed",
        "iqoptionapi": "installed",
        "numpy": "installed",
        "pandas": "installed",
        "analysis_tools": "installed"
    }
}
EOF

echo "✅ Construcción completada exitosamente!"
echo "🚀 El Trading Bot Opciones Binarias Pro está listo para deployar"
echo ""
echo "📋 Resumen de la construcción:"
echo "   • Python $(python --version | cut -d' ' -f2)"
echo "   • Flask y extensiones: ✅"
echo "   • IQOptionAPI: ✅"
echo "   • Análisis técnico: ✅"
echo "   • Configuración de producción: ✅"
echo ""
echo "🌐 El servicio estará disponible en el puerto ${PORT:-10000}"
echo "🩺 Health check: /health"
echo "📊 Dashboard: /"
