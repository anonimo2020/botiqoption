#!/bin/bash
# start.sh - Script de inicio para Render con WebSockets

echo "🚀 Iniciando IQ Option Bot en Render..."
echo "📊 Puerto: $PORT"
echo "🔧 Modo: Producción + WebSockets (eventlet)"

# Verificar variables de entorno
if [ -z "$REDIS_URL" ]; then
    echo "⚠️ REDIS_URL no configurado"
fi

if [ -z "$FRONTEND_URL" ]; then
    echo "⚠️ FRONTEND_URL no configurado"
fi

# Iniciar con Gunicorn + Eventlet para WebSockets
exec gunicorn main:app \
    --workers 1 \
    --worker-class eventlet \
    --worker-connections 1000 \
    --timeout 120 \
    --bind 0.0.0.0:$PORT \
    --log-level info \
    --access-logfile - \
    --error-logfile - \
    --max-requests 500 \
    --max-requests-jitter 50
