# backend.py – Versión mínima funcional (sin errores de sintaxis y Limiter corregido)
# Compatible con el frontend Trading Bot Pro
# -----------------------------------------------------------------------------
# requirements.txt:
# flask
# flask-session
# flask-cors
# flask-socketio
# eventlet
# flask-limiter
# iqoptionapi
# numpy
# requests
# -----------------------------------------------------------------------------

import os
import time
import logging
import datetime
import json
import eventlet
import numpy as np
from threading import Thread, Lock
from functools import wraps

# Parcheo para sockets/eventlet
eventlet.monkey_patch()

from iqoptionapi.stable_api import IQ_Option
import requests
from flask import Flask, request, jsonify, session, make_response
from flask_session import Session
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, join_room, leave_room

# -----------------------------------------------------------------------------
# CONFIGURACIÓN GENERAL
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "dev-key"),
    SESSION_TYPE="filesystem",
    SESSION_PERMANENT=False,
    SESSION_COOKIE_NAME="tbp_session",
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
)
Session(app)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)

# Limiter: usar solo kwargs para evitar collision
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200/day", "50/hour"]
)

socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS)

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# VARIABLES GLOBALES
# -----------------------------------------------------------------------------
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# -----------------------------------------------------------------------------
# DECORADORES
# -----------------------------------------------------------------------------
def require_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado"}), 401
        return f(*args, **kwargs)
    return wrapped

# -----------------------------------------------------------------------------
# ENDPOINTS
# -----------------------------------------------------------------------------
@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    pwd = data.get('password', '')
    if not email or not pwd:
        return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
    # Timeout para conectar IQ Option
    iq = IQ_Option(email, pwd)
    try:
        with eventlet.Timeout(15, False):
            ok = iq.connect()
        if not ok:
            return jsonify({"success": False, "message": "No se pudo conectar a IQ Option"}), 503
    except Exception:
        return jsonify({"success": False, "message": "Timeout conectando a IQ Option"}), 504
    session['user_email'] = email
    user_sessions[email] = iq
    return jsonify({"success": True}), 200

@app.route('/api/logout', methods=['POST'])
@require_auth
def logout():
    email = session.pop('user_email')
    user_sessions.pop(email, None)
    return jsonify({"success": True}), 200

@app.route('/api/balance', methods=['GET'])
@require_auth
def balance():
    iq = user_sessions.get(session['user_email'])
    bal = iq.get_balance()
    return jsonify({"balance": bal}), 200

@app.route('/api/symbols', methods=['GET'])
def symbols():
    syms = ["EURUSD","GBPUSD","USDJPY"]
    return jsonify({"symbols": syms}), 200

@app.route('/api/start_bot', methods=['POST'])
@require_auth
@limiter.limit("3 per minute")
def start_bot():
    # Ejemplo simple de arranque de bot en hilo
    def bot_job(email):
        iq = user_sessions[email]
        time.sleep(5)  # simulación
        with bots_lock:
            active_bots[email] = False
        socketio.emit('bot_stopped', {'msg': 'Bot terminado'})
    email = session['user_email']
    with bots_lock:
        if active_bots.get(email):
            return jsonify({"error": "Bot ya activo"}), 400
        active_bots[email] = True
    Thread(target=bot_job, args=(email,), daemon=True).start()
    return jsonify({"success": True}), 200

@app.route('/api/stop_bot', methods=['POST'])
@require_auth
def stop_bot():
    email = session['user_email']
    with bots_lock:
        active_bots[email] = False
    return jsonify({"success": True}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

# -----------------------------------------------------------------------------
# INICIO
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
