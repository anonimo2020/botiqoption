#!/bin/bash
# start.sh - Script de inicio optimizado para Render
# Trading Bot Pro v2.0 - Render Deployment

echo "🚀 Iniciando Trading Bot Pro v2.0 en Render..."

# Verificar variables de entorno críticas
if [ -z "$PORT" ]; then
    echo "⚠️ PORT no definido, usando 10000 por defecto"
    export PORT=10000
fi

# Crear directorios necesarios en filesystem efímero
mkdir -p /tmp/flask_sessions
mkdir -p /tmp/bot_logs

echo "📁 Directorios temporales creados"

# Configurar variables de entorno para optimización
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Configuración específica para Render
export RENDER_INTERNAL_HOST=0.0.0.0

# Si no está definida, usar URL de Render por defecto
if [ -z "$RENDER_EXTERNAL_URL" ]; then
    export RENDER_EXTERNAL_URL="https://$(echo $RENDER_SERVICE_NAME).onrender.com"
fi

echo "🌐 Configuración Render:"
echo "   - Puerto: $PORT"
echo "   - Host interno: $RENDER_INTERNAL_HOST"
echo "   - URL externa: $RENDER_EXTERNAL_URL"

# Verificar dependencias críticas
echo "🔍 Verificando dependencias..."

python -c "import flask; print(f'Flask: {flask.__version__}')" || {
    echo "❌ Error: Flask no está instalado"
    exit 1
}

python -c "import flask_socketio; print(f'Flask-SocketIO: {flask_socketio.__version__}')" || {
    echo "❌ Error: Flask-SocketIO no está instalado"
    exit 1
}

python -c "import numpy; print(f'NumPy: {numpy.__version__}')" || {
    echo "❌ Error: NumPy no está instalado"
    exit 1
}

# Verificar IQOptionAPI (opcional)
python -c "
try:
    from iqoptionapi.stable_api import IQ_Option
    print('✅ IQOptionAPI: Disponible')
except ImportError:
    print('⚠️ IQOptionAPI: No disponible (modo demo)')
"

echo "✅ Verificación de dependencias completada"

# Configurar límites de recursos para Render
ulimit -n 1024  # Límite de archivos abiertos
ulimit -u 512   # Límite de procesos

echo "🛡️ Límites de recursos configurados"

# Limpiar procesos anteriores si existen
pkill -f "python.*main.py" 2>/dev/null || true

echo "🧹 Limpieza previa completada"

# Mostrar información del sistema
echo "📊 Información del sistema:"
echo "   - Python: $(python --version)"
echo "   - PID actual: $"
echo "   - Memoria disponible: $(free -h 2>/dev/null | grep Mem | awk '{print $7}' || echo 'N/A')"
echo "   - Espacio en disco /tmp: $(df -h /tmp 2>/dev/null | tail -1 | awk '{print $4}' || echo 'N/A')"

# Función de cleanup en caso de error
cleanup() {
    echo "🛑 Ejecutando cleanup..."
    pkill -f "python.*main.py" 2>/dev/null || true
    rm -rf /tmp/flask_sessions/* 2>/dev/null || true
    rm -rf /tmp/bot_logs/* 2>/dev/null || true
    exit 1
}

# Configurar trap para cleanup
trap cleanup EXIT INT TERM

# Configurar variables adicionales para estabilidad
export FLASK_ENV=production
export FLASK_APP=main.py

# Configurar logging para Render
export PYTHONPATH=/app:$PYTHONPATH

echo "🔧 Variables de entorno configuradas"

# Verificar que el archivo principal existe
if [ ! -f "main.py" ]; then
    echo "❌ Error: main.py no encontrado"
    exit 1
fi

echo "✅ Archivo principal encontrado"

# Mostrar configuración final
echo "🎯 Configuración final:"
echo "   - FLASK_APP: $FLASK_APP"
echo "   - FLASK_ENV: $FLASK_ENV"
echo "   - PORT: $PORT"
echo "   - RENDER_EXTERNAL_URL: $RENDER_EXTERNAL_URL"
echo "   - Telegram configurado: $([ -n "$TELEGRAM_BOT_TOKEN" ] && echo '✅ Sí' || echo '❌ No')"

# Iniciar la aplicación con manejo de errores
echo "🚀 Iniciando aplicación..."
echo "======================================"

# Ejecutar con timeout y reintentos
for i in {1..3}; do
    echo "🔄 Intento $i de iniciar la aplicación..."
    
    timeout 300 python main.py &
    APP_PID=$!
    
    # Esperar un momento para ver si la app inicia correctamente
    sleep 5
    
    if kill -0 $APP_PID 2>/dev/null; then
        echo "✅ Aplicación iniciada correctamente (PID: $APP_PID)"
        wait $APP_PID
        EXIT_CODE=$?
        
        if [ $EXIT_CODE -eq 0 ]; then
            echo "✅ Aplicación terminó correctamente"
            exit 0
        else
            echo "⚠️ Aplicación terminó con código $EXIT_CODE"
        fi
    else
        echo "❌ La aplicación no pudo iniciarse en el intento $i"
    fi
    
    # Limpiar proceso anterior si aún existe
    kill $APP_PID 2>/dev/null || true
    sleep 2
done

echo "❌ No se pudo iniciar la aplicación después de 3 intentos"
exit 1
