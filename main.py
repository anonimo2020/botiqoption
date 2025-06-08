#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Trading Bot Pro - Versión con CORS Corregido para Render
"""

import os
import sys
import logging
import warnings
import datetime
import time
import requests
import json
from threading import Thread, Lock
from functools import wraps

# Suprimir warnings problemáticos
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*websocket.*")

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Suprimir logs problemáticos
for logger_name in ['websocket', 'iqoptionapi.ws.client', 'iqoptionapi.ws', 'urllib3']:
    logging.getLogger(logger_name).setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

# Función de parcheo inline para IQOptionAPI
def apply_websocket_patches():
    """Aplica parches directamente sin archivos externos"""
    try:
        from iqoptionapi.ws.client import WebsocketClient
        
        if hasattr(WebsocketClient, '_patched_by_cors_fix'):
            return True
        
        def safe_on_message(self, ws_or_message, message=None):
            try:
                actual_message = message if message is not None else ws_or_message
                if hasattr(self, 'socket_option_opened') and self.socket_option_opened:
                    self.socket_option_opened[1](actual_message)
            except Exception:
                pass
        
        def safe_on_error(self, ws_or_error, error=None):
            pass
        
        def safe_on_close(self, ws=None, close_status_code=None, close_msg=None):
            try:
                if hasattr(self, 'socket_option_opened'):
                    self.socket_option_opened = None
            except Exception:
                pass
        
        def safe_on_open(self, ws=None):
            pass
        
        WebsocketClient.on_message = safe_on_message
        WebsocketClient.on_error = safe_on_error
        WebsocketClient.on_close = safe_on_close
        WebsocketClient.on_open = safe_on_open
        WebsocketClient._patched_by_cors_fix = True
        
        logger.info("✅ WebSocket patches applied successfully")
        return True
        
    except Exception as e:
        logger.warning(f"⚠️ Could not apply patches: {e}")
        return False

# Clase SafeIQOption
class SafeIQOption:
    """Wrapper seguro para IQ_Option"""
    
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self._iq_instance = None
        
        apply_websocket_patches()
        
        for logger_name in ['websocket', 'iqoptionapi.ws.client', 'iqoptionapi']:
            logging.getLogger(logger_name).setLevel(logging.CRITICAL)
        
        try:
            from iqoptionapi.stable_api import IQ_Option
            self._iq_instance = IQ_Option(email, password)
        except Exception as e:
            logger.error(f"Error creating IQ_Option instance: {e}")
            raise
    
    def connect(self):
        if not self._iq_instance:
            return False, "Instance not available"
        
        try:
            original_levels = {}
            loggers_to_suppress = ['websocket', 'iqoptionapi.ws.client', 'iqoptionapi.ws', 'iqoptionapi']
            
            for logger_name in loggers_to_suppress:
                logger_obj = logging.getLogger(logger_name)
                original_levels[logger_name] = logger_obj.level
                logger_obj.setLevel(logging.CRITICAL)
            
            try:
                result = self._iq_instance.connect()
                return result
            finally:
                for logger_name, level in original_levels.items():
                    logging.getLogger(logger_name).setLevel(level)
                
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False, str(e)
    
    def __getattr__(self, name):
        if self._iq_instance:
            return getattr(self._iq_instance, name)
        raise AttributeError(f"Attribute {name} not available")

# Aplicar parches automáticamente
try:
    apply_websocket_patches()
except Exception as e:
    logger.warning(f"Auto-patch failed: {e}")

# Importar Flask y dependencias
try:
    import numpy as np
    from flask import Flask, request, jsonify, session
    from flask_cors import CORS
    from flask_session import Session
    logger.info("✅ Flask dependencies loaded")
except ImportError as e:
    logger.error(f"❌ Error importing Flask dependencies: {e}")
    sys.exit(1)

# Importar IQOptionAPI
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI loaded successfully")
except ImportError as e:
    logger.error(f"❌ IQOptionAPI not available: {e}")
    IQ_AVAILABLE = False

# Configuración de la aplicación Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'binary-bot-cors-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_COOKIE_SAMESITE'] = None  # Cambiado de 'None' a None
app.config['SESSION_COOKIE_SECURE'] = False   # Cambiado a False para debugging
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Crear directorio de sesiones
os.makedirs('/tmp/flask_sessions', exist_ok=True)

Session(app)

# Configuración CORS más robusta
CORS(app, 
     origins=["*"],  # Permitir todos los orígenes temporalmente
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
     supports_credentials=True,
     expose_headers=["Content-Type"],
     max_age=86400)

# Variables globales
user_sessions = {}
sessions_lock = Lock()

# Configuración de Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def send_telegram_message(message):
    """Envía mensaje a Telegram de forma asíncrona y segura"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
        
    def send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000],
                "parse_mode": "Markdown"
            }
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.debug(f"Telegram error: {e}")
    
    Thread(target=send, daemon=True).start()

def require_auth(f):
    """Decorador de autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# Manejador CORS mejorado
@app.before_request
def before_request():
    """Manejar preflight requests y CORS"""
    if request.method == 'OPTIONS':
        # Respuesta a preflight request
        response = make_response('', 200)
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
        response.headers.add('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        response.headers.add('Access-Control-Max-Age', '86400')
        return response

@app.after_request
def after_request(response):
    """Agregar headers CORS a todas las respuestas"""
    origin = request.headers.get('Origin')
    
    # Si hay origin específico, usarlo; si no, permitir cualquiera
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = '*'
    
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With'
    response.headers['Access-Control-Expose-Headers'] = 'Content-Type'
    
    # Headers adicionales para debugging
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    
    return response

# Endpoints principales
@app.route('/health', methods=['GET', 'OPTIONS'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "iq_api_available": IQ_AVAILABLE,
        "active_sessions": len(user_sessions),
        "system": "Binary Options Trading Bot Pro",
        "cors": "enabled"
    }), 200

@app.route('/api/test', methods=['GET', 'POST', 'OPTIONS'])
def test_endpoint():
    """Endpoint de prueba para verificar conectividad"""
    return jsonify({
        "message": "Backend funcionando correctamente",
        "method": request.method,
        "timestamp": datetime.datetime.now().isoformat(),
        "headers": dict(request.headers),
        "origin": request.headers.get('Origin', 'No origin')
    }), 200

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    """Login endpoint con manejo mejorado de CORS"""
    if request.method == 'OPTIONS':
        return '', 200
    
    if not IQ_AVAILABLE:
        return jsonify({
            "success": False,
            "message": "IQOptionAPI no está disponible en el servidor"
        }), 503
    
    try:
        # Verificar que se reciben datos
        if not request.is_json:
            return jsonify({
                "success": False,
                "message": "Content-Type debe ser application/json"
            }), 400
        
        data = request.get_json()
        if not data:
            return jsonify({
                "success": False, 
                "message": "No se recibieron datos JSON"
            }), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({
                "success": False,
                "message": "Email y contraseña son requeridos"
            }), 400
        
        logger.info(f"Intento de login para: {email}")
        
        # Limpiar sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        # Crear conexión usando SafeIQOption
        iq = SafeIQOption(email, password)
        
        # Intentar conectar
        logger.info("Conectando con IQ Option...")
        try:
            check, reason = iq.connect()
        except Exception as e:
            logger.error(f"Error durante conexión: {e}")
            return jsonify({
                "success": False,
                "message": f"Error de conexión: {str(e)}"
            }), 503
        
        if not check:
            logger.error(f"Conexión fallida: {reason}")
            
            # Manejar diferentes tipos de respuesta de error
            if isinstance(reason, dict):
                code = reason.get("code", "")
                message = reason.get("message", str(reason))
            elif isinstance(reason, str):
                try:
                    parsed = json.loads(reason)
                    code = parsed.get("code", "")
                    message = parsed.get("message", reason)
                except:
                    code = ""
                    message = reason
            else:
                code = ""
                message = str(reason)
            
            if code == "2FA" or "2FA" in message:
                return jsonify({
                    "success": False,
                    "message": "Autenticación de dos factores requerida",
                    "code": "2FA_REQUIRED"
                }), 401
            elif code == "invalid_credentials" or "invalid" in message.lower():
                return jsonify({
                    "success": False,
                    "message": "Correo o contraseña incorrecta",
                    "code": "INVALID_CREDENTIALS"
                }), 401
            else:
                return jsonify({
                    "success": False,
                    "message": f"Error de conexión: {message}"
                }), 503
        
        # Verificar conexión establecida
        try:
            if not iq.check_connect():
                return jsonify({
                    "success": False,
                    "message": "No se pudo establecer conexión con IQ Option"
                }), 401
        except Exception as e:
            logger.error(f"Error verificando conexión: {e}")
            return jsonify({
                "success": False,
                "message": "Error verificando conexión"
            }), 500
        
        # Configurar cuenta y obtener datos
        try:
            iq.change_balance("PRACTICE")
            time.sleep(1)
            
            balance = iq.get_balance()
            account_type = iq.get_balance_mode()
            user_name = email.split('@')[0].title()
            
            # Guardar sesión
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            send_telegram_message(f"✅ *LOGIN EXITOSO*\n👤 {user_name}\n📧 {email}\n💰 ${balance:.2f}")
            
            return jsonify({
                "success": True,
                "user": {
                    "name": user_name,
                    "email": email,
                    "balance": float(balance),
                    "account_type": account_type,
                    "currency": "USD",
                    "trading_mode": "Binary Options"
                },
                "message": "Login exitoso - Modo Opciones Binarias"
            }), 200
            
        except Exception as e:
            logger.error(f"Error obteniendo datos de cuenta: {e}")
            
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            return jsonify({
                "success": True,
                "user": {
                    "name": email.split('@')[0].title(),
                    "email": email,
                    "balance": 0.0,
                    "account_type": "PRACTICE",
                    "currency": "USD",
                    "trading_mode": "Binary Options"
                },
                "message": "Login exitoso (datos limitados)"
            }), 200
            
    except Exception as e:
        logger.error(f"Error general en login: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "message": "Error interno del servidor"
        }), 500

@app.route('/api/logout', methods=['POST', 'OPTIONS'])
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
        send_telegram_message(f"👋 Logout: {email}")
        
        return jsonify({"success": True, "message": "Sesión cerrada"}), 200
    except Exception as e:
        logger.error(f"Error en logout: {e}")
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

@app.route('/api/balance', methods=['GET', 'OPTIONS'])
@require_auth
def get_balance():
    """Obtener balance actual"""
    try:
        email = session['user_email']
        
        with sessions_lock:
            if email not in user_sessions:
                return jsonify({"error": "Sesión no válida"}), 401
            
            iq = user_sessions[email]
            
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        return jsonify({
            "balance": float(balance),
            "account_type": account_type,
            "max_trade_amount": float(balance * 0.5),
            "currency": "USD"
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo balance: {e}")
        return jsonify({"error": "Error obteniendo balance"}), 500

# Resto de endpoints con el mismo patrón...
@app.route('/api/symbols', methods=['GET', 'OPTIONS'])
@require_auth
def get_symbols():
    symbols = [
        {"symbol": "EURUSD", "name": "EUR/USD", "type": "major_pairs", "available": True},
        {"symbol": "GBPUSD", "name": "GBP/USD", "type": "major_pairs", "available": True},
        {"symbol": "USDJPY", "name": "USD/JPY", "type": "major_pairs", "available": True},
        {"symbol": "AUDUSD", "name": "AUD/USD", "type": "major_pairs", "available": True}
    ]
    return jsonify({"symbols": symbols}), 200

@app.route('/api/strategies', methods=['GET', 'OPTIONS'])
@require_auth
def get_strategies():
    strategies = [
        {
            "id": "rsi_bollinger",
            "name": "RSI + Bollinger Bands",
            "risk_level": "LOW",
            "description": "Estrategia conservadora",
            "timeframe": 5,
            "risk_color": "#10b981"
        }
    ]
    return jsonify({"strategies": strategies}), 200

# Endpoints placeholder para compatibilidad
@app.route('/api/start_bot', methods=['POST', 'OPTIONS'])
@require_auth
def start_bot():
    return jsonify({"message": "Bot iniciado (modo demo)"}), 200

@app.route('/api/stop_bot', methods=['POST', 'OPTIONS'])
@require_auth
def stop_bot():
    return jsonify({"message": "Bot detenido"}), 200

@app.route('/api/bot_status', methods=['GET', 'OPTIONS'])
@require_auth
def bot_status():
    return jsonify({"running": False}), 200

@app.route('/api/metrics', methods=['GET', 'OPTIONS'])
@require_auth
def get_metrics():
    return jsonify({"metrics": {"total_trades": 0}}), 200

# Manejadores de error
@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error interno: {error}")
    return jsonify({"error": "Error interno del servidor"}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint no encontrado"}), 404

# Main
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info("🚀 INICIANDO BINARY OPTIONS BOT CON CORS CORREGIDO")
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🔧 IQ Option API: {'✅ Disponible' if IQ_AVAILABLE else '❌ No disponible'}")
    logger.info(f"🌐 CORS: ✅ Configurado para todos los orígenes")
    logger.info(f"🛡️ WebSocket: ✅ Parches aplicados")
    logger.info("=" * 60)
    
    if IQ_AVAILABLE:
        send_telegram_message("🚀 *BINARY OPTIONS BOT INICIADO*\n✅ CORS corregido\n🛡️ WebSocket estable")
    
    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    except Exception as e:
        logger.error(f"Error iniciando servidor: {e}")
        sys.exit(1)
