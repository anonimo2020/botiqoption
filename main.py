# main.py - Backend FUNCIONANDO sin bloqueos

# OPCIÓN 1: Sin eventlet (RECOMENDADO para tu caso)
# Comenta las siguientes líneas si quieres usar threading en lugar de eventlet
# import eventlet
# eventlet.monkey_patch()

import os
import sys
import logging
import datetime
import time
import requests
import numpy as np
from functools import wraps
from threading import Thread, Lock
import json

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Path para IQOptionAPI
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Flask imports
from flask import Flask, request, jsonify, session, make_response
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from flask_session import Session

# Intentar importar IQOptionAPI
IQ_AVAILABLE = False
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI imported successfully!")
except ImportError as e:
    logger.error(f"❌ Failed to import IQOptionAPI: {e}")
    
    # Mock simple cuando no está disponible
    class IQ_Option:
        def __init__(self, email, password):
            self.email = email
            self.password = password
            self.connected = False
            self.balance = 10000.0
            
        def connect(self):
            time.sleep(0.5)
            self.connected = True
            return True
            
        def check_connect(self):
            return self.connected
            
        def get_profile(self):
            return {"name": self.email.split('@')[0], "email": self.email, "currency": "USD"}
            
        def get_balance(self):
            return self.balance
            
        def get_balance_mode(self):
            return "PRACTICE"
            
        def close_websocket(self):
            self.connected = False
            
        def change_balance(self, mode):
            return True

# Flask App
app = Flask(__name__)

# Configuración
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/sessions'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True

# Inicializar Session
Session(app)

# CORS configuración completa
CORS(app, 
     resources={r"/*": {
         "origins": "*",
         "allow_headers": ["Content-Type", "Authorization"],
         "expose_headers": ["Content-Type"],
         "supports_credentials": True,
         "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
     }})

# SocketIO con threading (NO eventlet)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',  # IMPORTANTE: Usar threading, no eventlet
    cors_credentials=True,
    logger=True,
    engineio_logger=True
)

# Variables globales
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

def send_telegram_message(message):
    """Envía mensaje a Telegram de forma asíncrona"""
    def send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram error: {e}")
    
    # Enviar en thread separado para no bloquear
    Thread(target=send, daemon=True).start()

# Middleware para agregar headers CORS
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# Health check
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "iq_api_available": IQ_AVAILABLE,
        "server_mode": "threading"
    }), 200

# Test endpoint
@app.route('/test', methods=['GET', 'POST', 'OPTIONS'])
def test():
    if request.method == 'OPTIONS':
        return '', 204
        
    return jsonify({
        "message": "Test endpoint working",
        "method": request.method,
        "iq_available": IQ_AVAILABLE,
        "timestamp": datetime.datetime.now().isoformat()
    }), 200

# Login endpoint
@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    """Login endpoint optimizado"""
    if request.method == 'OPTIONS':
        return '', 204
    
    logger.info("=== LOGIN REQUEST RECEIVED ===")
    
    try:
        # Obtener datos
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data received"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        logger.info(f"Login attempt for: {email}")
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
        
        # Limpiar sesión anterior si existe
        with sessions_lock:
            if email in user_sessions:
                try:
                    old_session = user_sessions[email]
                    old_session.close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        # Crear nueva instancia de IQ Option
        try:
            iq = IQ_Option(email, password)
            logger.info("IQ_Option instance created")
            
            # Conectar
            connect_result = iq.connect()
            logger.info(f"Connect result: {connect_result}")
            
            if not connect_result:
                return jsonify({
                    "success": False,
                    "message": "No se pudo conectar con IQ Option. Verifica tu conexión."
                }), 503
            
            # Verificar conexión
            if not iq.check_connect():
                return jsonify({
                    "success": False,
                    "message": "Credenciales incorrectas"
                }), 401
            
            # Obtener datos del usuario
            profile = iq.get_profile()
            balance = iq.get_balance()
            account_type = iq.get_balance_mode()
            
            # Guardar en sesión
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            # Preparar respuesta
            user_data = {
                "name": profile.get('name', email.split('@')[0]),
                "email": email,
                "balance": float(balance),
                "account_type": account_type,
                "currency": profile.get('currency', 'USD')
            }
            
            # Enviar notificación (async)
            mode = "DEMO" if not IQ_AVAILABLE else "REAL"
            send_telegram_message(f"🎯 *LOGIN {mode}*\n👤 {email}\n💰 ${balance:.2f}")
            
            logger.info(f"Login successful for {email}")
            
            # Retornar respuesta exitosa
            return jsonify({
                "success": True,
                "user": user_data,
                "message": "Login exitoso"
            }), 200
            
        except Exception as e:
            logger.error(f"Error during IQ Option operations: {str(e)}")
            
            # Si falla IQ Option, usar modo demo
            if not IQ_AVAILABLE or "IQOptionAPI no está instalada" in str(e):
                session['user_email'] = email
                
                demo_user = {
                    "name": email.split('@')[0],
                    "email": email,
                    "balance": 10000.00,
                    "account_type": "PRACTICE",
                    "currency": "USD"
                }
                
                return jsonify({
                    "success": True,
                    "user": demo_user,
                    "demo_mode": True,
                    "message": "Modo DEMO activado"
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "message": f"Error: {str(e)}"
                }), 500
                
    except Exception as e:
        logger.error(f"Unexpected error in login: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "message": "Error interno del servidor"
        }), 500

# Logout
@app.route('/api/logout', methods=['POST'])
def logout():
    try:
        if 'user_email' in session:
            email = session['user_email']
            
            # Detener bot si está activo
            with bots_lock:
                if email in active_bots:
                    active_bots[email] = False
            
            # Cerrar sesión IQ Option
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
        logger.error(f"Logout error: {str(e)}")
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

# Get balance
@app.route('/api/balance', methods=['GET'])
def get_balance():
    if 'user_email' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    email = session['user_email']
    
    with sessions_lock:
        if email not in user_sessions:
            return jsonify({"error": "Sesión expirada"}), 401
        
        iq = user_sessions[email]
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
    
    return jsonify({
        "balance": balance,
        "account_type": account_type
    }), 200

# Get symbols
@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    weekend = datetime.datetime.today().weekday() >= 5
    
    if weekend:
        symbols = [
            {"symbol": "EURUSD-OTC", "name": "EUR/USD OTC", "type": "otc"},
            {"symbol": "GBPUSD-OTC", "name": "GBP/USD OTC", "type": "otc"},
            {"symbol": "USDJPY-OTC", "name": "USD/JPY OTC", "type": "otc"}
        ]
    else:
        symbols = [
            {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
            {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
            {"symbol": "USDJPY", "name": "USD/JPY", "type": "forex"}
        ]
    
    return jsonify({"symbols": symbols}), 200

# Start bot
@app.route('/api/start_bot', methods=['POST'])
def start_bot():
    if 'user_email' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    email = session['user_email']
    
    # Verificar si hay bot activo
    with bots_lock:
        if active_bots.get(email, False):
            return jsonify({"error": "Ya hay un bot activo"}), 400
    
    data = request.get_json()
    symbol = data.get('symbol', 'EURUSD')
    amount = float(data.get('amount', 1))
    martingalas = int(data.get('martingalas', 0))
    account_type = data.get('account_type', 'PRACTICE')
    
    # Validaciones
    if amount <= 0:
        return jsonify({"error": "Monto debe ser mayor a 0"}), 400
    
    with sessions_lock:
        if email not in user_sessions:
            return jsonify({"error": "Sesión expirada"}), 401
        
        iq = user_sessions[email]
        iq.change_balance(account_type)
        balance = iq.get_balance()
        
        if amount > balance:
            return jsonify({"error": f"Fondos insuficientes. Balance: ${balance:.2f}"}), 400
    
    # Marcar bot como activo
    with bots_lock:
        active_bots[email] = True
    
    # Configuración
    bot_config = {
        'symbol': symbol,
        'amount': amount,
        'martingalas': martingalas,
        'account_type': account_type
    }
    
    # TODO: Implementar lógica del bot
    send_telegram_message(f"🚀 *BOT INICIADO*\n👤 {email}\n📈 {symbol}\n💰 ${amount:.2f}")
    
    return jsonify({"message": "Bot iniciado correctamente"}), 200

# Stop bot
@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    if 'user_email' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    email = session['user_email']
    
    with bots_lock:
        if email in active_bots and active_bots[email]:
            active_bots[email] = False
            send_telegram_message(f"🛑 *BOT DETENIDO*\n👤 {email}")
            return jsonify({"message": "Bot detenido"}), 200
        else:
            return jsonify({"error": "No hay bot activo"}), 400

# WebSocket events
@socketio.on('connect')
def handle_connect():
    join_room(request.sid)
    emit('connected', {'sid': request.sid})
    logger.info(f"WebSocket client connected: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    leave_room(request.sid)
    logger.info(f"WebSocket client disconnected: {request.sid}")

# Main
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting server on port {port}")
    logger.info(f"📊 Mode: {'IQ Option API' if IQ_AVAILABLE else 'Demo Mode'}")
    logger.info("🔧 Using threading mode (no eventlet)")
    
    # Usar el servidor de desarrollo de Flask con threading
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
