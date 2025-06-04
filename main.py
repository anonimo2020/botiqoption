import os
from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import logging
import datetime
import time
import requests
import numpy as np
from iqoptionapi.stable_api import IQ_Option
from flask_session import Session
import json
import eventlet

eventlet.monkey_patch()

# --- Configuración de la aplicación Flask ---
app = Flask(__name__)
CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'https://iqoptionbot.ct.ws'])

# Configuración de SECRET_KEY desde variables de entorno
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'super_secret_key_dev_fallback_please_change')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_FILE_DIR'] = '/tmp/session_data'
app.config['SESSION_COOKIE_NAME'] = 'trading_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
Session(app)

# Crear directorio de sesiones si no existe
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# Inicialización de SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', logger=True, engineio_logger=True)

# --- Configuración de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Variables Globales ---
user_sessions = {}
active_bots = {}

# --- Configuración de Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("No se puede enviar mensaje a Telegram: Token o Chat ID no configurados.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        logger.info(f"Mensaje enviado a Telegram: {message[:50]}...")
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al enviar mensaje a Telegram: {e}")

# --- Endpoints HTTP REST ---

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}), 200

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({"success": False, "message": "Email y contraseña son requeridos"}), 400

        email = data['email'].strip()
        password = data['password']

        logger.info(f"Iniciando sesión para: {email}")

        if email in user_sessions:
            user_sessions[email].close_websocket()
            del user_sessions[email]

        iq = IQ_Option(email, password)
        if not iq.connect() or not iq.check_connect():
            return jsonify({"success": False, "message": "Credenciales incorrectas o error de conexión."}), 401

        profile = iq.get_profile() or {"name": "Usuario", "email": email}
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()

        user_sessions[email] = iq
        session['user_email'] = email
        session.permanent = True

        send_telegram_message(f"Nuevo login exitoso: {profile['name']} ({email}) - Balance: ${balance:.2f}")

        return jsonify({"success": True, "user": {"name": profile['name'], "email": email, "balance": balance, "account_type": account_type}}), 200

    except Exception as e:
        logger.error(f"Error en login: {e}")
        return jsonify({"success": False, "message": "Error interno del servidor."}), 500

@app.route('/logout', methods=['POST'])
def logout():
    try:
        email = session.get('user_email')
        if not email:
            return jsonify({"success": False, "message": "No hay sesión activa."}), 400

        if email in user_sessions:
            user_sessions[email].close_websocket()
            del user_sessions[email]

        session.clear()
        send_telegram_message(f"Logout: {email}")
        return jsonify({"success": True, "message": "Sesión cerrada correctamente."}), 200

    except Exception as e:
        logger.error(f"Error en logout: {e}")
        return jsonify({"success": False, "message": "Error al cerrar sesión."}), 500

@app.route('/symbols', methods=['GET'])
def get_symbols():
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"]
    return jsonify({"symbols": symbols}), 200

@app.route('/start_bot', methods=['POST'])
def start_bot():
    try:
        email = session.get('user_email')
        if not email:
            return jsonify({"error": "Usuario no autenticado"}), 403

        iq = user_sessions.get(email)
        if not iq or not iq.check_connect():
            return jsonify({"error": "Sesión expirada o inválida."}), 403

        data = request.get_json()
        symbol = data.get('symbol', 'EURUSD').upper()
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE').upper()

        if amount <= 0 or amount > 10000 or martingalas < 0:
            return jsonify({"error": "Datos inválidos."}), 400

        if active_bots.get(email, False):
            return jsonify({"error": "Ya hay un bot activo."}), 400

        iq.change_balance(account_type)
        if iq.get_balance_mode() != account_type:
            return jsonify({"error": "No se pudo cambiar el tipo de cuenta."}), 400

        balance = iq.get_balance()
        if amount > balance:
            return jsonify({"error": "Fondos insuficientes."}), 400

        active_bots[email] = True
        socketio.start_background_task(run_bot, iq, symbol, amount, martingalas, email)

        return jsonify({"message": "Bot iniciado correctamente."}), 200

    except Exception as e:
        logger.error(f"Error al iniciar bot: {e}")
        return jsonify({"error": "Error interno al iniciar el bot."}), 500

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    try:
        email = session.get('user_email')
        if not email or not active_bots.get(email, False):
            return jsonify({"error": "No hay un bot activo."}), 400

        active_bots[email] = False
        return jsonify({"message": "Señal para detener el bot enviada."}), 200

    except Exception as e:
        logger.error(f"Error deteniendo bot: {e}")
        return jsonify({"error": "Error interno al detener el bot."}), 500

# --- Lógica del Bot y Funciones Auxiliares ---

def run_bot(iq_api_instance, symbol, initial_amount, martingalas_limit, email):
    # Implementación de la lógica del bot aquí
    pass

# --- Inicio de la aplicación Flask y SocketIO ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
