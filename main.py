# main.py - Backend Corregido para Bot de Trading Opciones Binarias Pro

import os
import sys
import logging
import datetime
import time
import requests
import numpy as np
from functools import wraps
from threading import Thread, Lock, Event
import json
import math
import signal
import atexit
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

# Configuración de logging detallado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Agregar path para IQOptionAPI local si existe
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# PARCHE PARA WEBSOCKET - SOLUCIONA ERROR DE ARGUMENTOS
# ============================================================================

def apply_websocket_patch():
    """Aplica parche para solucionar errores de WebSocket"""
    try:
        logger.info("🔧 Aplicando parche de WebSocket...")
        
        import websocket
        from websocket import WebSocketApp
        
        class CompatibleWebSocketApp(WebSocketApp):
            """WebSocketApp compatible con diferentes versiones de websocket-client"""
            
            def __init__(self, url, **kwargs):
                def wrap_callback(callback):
                    if callback is None:
                        return None
                    
                    def wrapper(*args, **kwargs_inner):
                        try:
                            return callback(*args, **kwargs_inner)
                        except TypeError as e:
                            if "positional argument" in str(e):
                                try:
                                    return callback(args[0])
                                except:
                                    logger.debug(f"Callback wrapper handled: {e}")
                                    pass
                            else:
                                raise
                    return wrapper
                
                # Wrappear todos los callbacks
                for callback_name in ['on_open', 'on_close', 'on_error', 'on_message']:
                    if callback_name in kwargs:
                        kwargs[callback_name] = wrap_callback(kwargs[callback_name])
                
                super().__init__(url, **kwargs)
        
        # Reemplazar WebSocketApp original
        websocket.WebSocketApp = CompatibleWebSocketApp
        
        logger.info("✅ Parche de WebSocket aplicado correctamente")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error aplicando parche de WebSocket: {e}")
        return False

# Aplicar parches antes de importar IQOptionAPI
apply_websocket_patch()

# Flask y extensiones
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Importar IQOptionAPI con parche aplicado
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando IQOptionAPI: {e}")
    IQ_AVAILABLE = False
    raise Exception("IQOptionAPI no está instalada")

# Configuración Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'trading-bot-secret-key-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_COOKIE_NAME'] = 'trading_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24  # 24 horas

# Crear directorio de sesiones
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# Inicializar extensiones
Session(app)

# CORS configuración completa
CORS(app, 
     resources={r"/*": {
         "origins": "*",
         "methods": ["GET", "POST", "OPTIONS"],
         "allow_headers": ["Content-Type", "Authorization"],
         "expose_headers": ["Content-Type"],
         "supports_credentials": True
     }})

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["200 per day", "50 per hour"]
)

# Variables globales con thread safety
user_sessions = {}  # {email: IQ_Option instance}
active_bots = {}    # {email: Bot instance}
sessions_lock = Lock()
bots_lock = Lock()

# Configuración Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# Funciones auxiliares
def send_telegram_message(message):
    """Envía mensaje a Telegram de forma asíncrona"""
    def send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                logger.error(f"Error Telegram: {response.text}")
        except Exception as e:
            logger.error(f"Error enviando a Telegram: {e}")
    
    Thread(target=send, daemon=True).start()

def require_auth(f):
    """Decorador para requerir autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
            
            iq = user_sessions[email]
            try:
                if not iq.check_connect():
                    logger.warning(f"Conexión perdida para {email}, reintentando...")
                    if not iq.connect():
                        del user_sessions[email]
                        session.clear()
                        return jsonify({"error": "Conexión perdida", "code": "CONNECTION_LOST"}), 401
            except:
                del user_sessions[email]
                session.clear()
                return jsonify({"error": "Error de conexión", "code": "CONNECTION_ERROR"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# CORS headers
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# Endpoints principales
@app.route('/', methods=['GET'])
def serve_frontend():
    """Servir el frontend HTML"""
    frontend_html = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Pro - Opciones Binarias</title>
    <style>
        body {
            font-family: 'Arial', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 600px;
            width: 100%;
        }
        .logo {
            font-size: 48px;
            margin-bottom: 20px;
        }
        h1 {
            color: #333;
            margin-bottom: 20px;
        }
        .status {
            background: #d4edda;
            color: #155724;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            border: 1px solid #c3e6cb;
        }
        .btn {
            background: #007bff;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            margin: 10px;
        }
        .btn:hover {
            background: #0056b3;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🚀</div>
        <h1>Trading Bot Pro - Opciones Binarias</h1>
        
        <div class="status">
            ✅ Servidor activo y funcionando correctamente
        </div>
        
        <p>Sistema especializado en opciones binarias con gestión de capital avanzada</p>
        
        <div style="margin-top: 30px;">
            <a href="/health" class="btn">📊 Health Check</a>
        </div>
    </div>
</body>
</html>'''
    return frontend_html, 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "iq_api_available": IQ_AVAILABLE,
            "active_sessions": len(user_sessions),
            "active_bots": len([b for b in active_bots.values() if hasattr(b, 'running') and b.running]),
            "websocket_patch": "applied"
        }
        
        return jsonify(health_data), 200
        
    except Exception as e:
        logger.error(f"Error en health check: {e}")
        return jsonify({
            "status": "error",
            "timestamp": datetime.datetime.now().isoformat(),
            "error": str(e)
        }), 500

@app.route('/api/login', methods=['POST', 'OPTIONS'])
@limiter.limit("5 per minute")
def login():
    """Login endpoint con reintentos automáticos"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No se recibieron datos"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña son requeridos"}), 400
        
        logger.info(f"Intento de login para: {email}")
        
        # Limpiar sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        # Función para intentar conexión con reintentos
        def attempt_connection(max_retries=3):
            for attempt in range(max_retries):
                try:
                    logger.info(f"Intento de conexión {attempt + 1}/{max_retries}")
                    
                    iq = IQ_Option(email, password)
                    logger.info("Conectando con IQ Option...")
                    
                    # Usar threading para timeout
                    connection_result = {'check': False, 'reason': 'Timeout'}
                    connection_event = Event()
                    
                    def connect_thread():
                        try:
                            check, reason = iq.connect()
                            connection_result['check'] = check
                            connection_result['reason'] = reason
                            connection_event.set()
                        except Exception as e:
                            connection_result['check'] = False
                            connection_result['reason'] = str(e)
                            connection_event.set()
                    
                    connect_worker = Thread(target=connect_thread, daemon=True)
                    connect_worker.start()
                    
                    if connection_event.wait(timeout=30):
                        check = connection_result['check']
                        reason = connection_result['reason']
                    else:
                        logger.warning(f"Timeout en conexión (intento {attempt + 1})")
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return False, "Timeout de conexión"
                    
                    if not check:
                        logger.error(f"Error de conexión (intento {attempt + 1}): {reason}")
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        
                        # Analizar tipo de error
                        reason_str = str(reason)
                        if "2FA" in reason_str:
                            return False, {"message": "2FA requerido", "code": "2FA_REQUIRED"}
                        elif "credentials" in reason_str.lower():
                            return False, {"message": "Credenciales incorrectas", "code": "INVALID_CREDENTIALS"}
                        
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return False, f"Error de conexión: {reason_str}"
                    
                    # Verificar conexión establecida
                    time.sleep(1)
                    if not iq.check_connect():
                        logger.warning(f"Conexión no verificada (intento {attempt + 1})")
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return False, "No se pudo establecer conexión estable"
                    
                    logger.info("Conexión establecida correctamente")
                    return True, iq
                    
                except Exception as e:
                    logger.error(f"Excepción en intento {attempt + 1}: {str(e)}")
                    if attempt == max_retries - 1:
                        return False, f"Error de conexión: {str(e)}"
            
            return False, "No se pudo establecer conexión"
        
        # Intentar conexión
        success, result = attempt_connection()
        
        if not success:
            if isinstance(result, dict):
                return jsonify({"success": False, **result}), 401
            else:
                return jsonify({"success": False, "message": result}), 503
        
        iq = result
        
        # Obtener información del usuario
        try:
            user_name = email.split('@')[0].title()
            balance = 0.0
            account_type = "PRACTICE"
            
            # Intentar obtener balance
            for i in range(3):
                try:
                    balance = iq.get_balance()
                    account_type = iq.get_balance_mode()
                    break
                except:
                    if i < 2:
                        time.sleep(1)
            
            # Guardar sesión
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            send_telegram_message(f"""🎯 *LOGIN EXITOSO*
👤 Usuario: {user_name}
📧 Email: {email}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}""")
            
            return jsonify({
                "success": True,
                "user": {
                    "name": user_name,
                    "email": email,
                    "balance": float(balance),
                    "account_type": account_type,
                    "currency": "USD"
                },
                "message": "Conexión exitosa"
            }), 200
            
        except Exception as e:
            logger.error(f"Error obteniendo datos: {e}")
            # Guardar sesión básica
            with sessions_lock:
                user_sessions[email] = iq
            session['user_email'] = email
            
            return jsonify({
                "success": True,
                "user": {
                    "name": email.split('@')[0],
                    "email": email,
                    "balance": 0.0,
                    "account_type": "PRACTICE",
                    "currency": "USD"
                },
                "message": "Conexión exitosa (datos limitados)"
            }), 200
            
    except Exception as e:
        logger.error(f"Error en login: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Error del servidor: {str(e)}"
        }), 500

@app.route('/api/logout', methods=['POST'])
@require_auth
def logout():
    """Logout endpoint"""
    try:
        email = session['user_email']
        
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        session.clear()
        send_telegram_message(f"👋 *LOGOUT*\n📧 {email}")
        
        return jsonify({"success": True, "message": "Sesión cerrada"}), 200
        
    except Exception as e:
        logger.error(f"Error en logout: {str(e)}")
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

@app.route('/api/balance', methods=['GET'])
@require_auth
def get_balance():
    """Obtener balance actual"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        return jsonify({
            "balance": float(balance),
            "account_type": account_type
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo balance: {str(e)}")
        return jsonify({"error": "Error obteniendo balance"}), 500

# Main
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info(f"🚀 INICIANDO BOT DE TRADING OPCIONES BINARIAS PRO")
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🔧 IQ Option API: {'Disponible' if IQ_AVAILABLE else 'No disponible'}")
    logger.info(f"📱 Telegram: {'Configurado' if TELEGRAM_BOT_TOKEN else 'No configurado'}")
    logger.info("=" * 60)
    
    if not IQ_AVAILABLE:
        logger.error("IQOptionAPI no está disponible")
    
    send_telegram_message(f"""🚀 *BOT OPCIONES BINARIAS PRO INICIADO*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🔧 API: {'OK' if IQ_AVAILABLE else 'ERROR'}""")
    
    # Ejecutar servidor
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
