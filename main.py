# main.py – API REST + WebSocket para Trading Bot Pro con IQ Option y Telegram
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
from flask_socketio import SocketIO, emit, join_room

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

# CORS (dominio del frontend)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS",
    "http://iqoptionbot.ct.ws").split(",")
CORS(app,
     supports_credentials=True,
     resources={r"/*": {"origins": ALLOWED_ORIGINS}})

# Rate limiter
limiter = Limiter(app=app,
                  key_func=get_remote_address,
                  default_limits=["200/day", "50/hour"])

# SocketIO
socketio = SocketIO(app,
                    cors_allowed_origins=ALLOWED_ORIGINS,
                    async_mode='eventlet')

# Logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# Sesiones e instancias por usuario
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# Telegram
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID")
def send_telegram(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": TG_CHAT,
        "text": msg,
        "parse_mode": "Markdown"
    })

# -----------------------------------------------------------------------------
# UTILIDADES
# -----------------------------------------------------------------------------
def require_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "AUTH_REQUIRED"}), 401
        email = session['user_email']
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "SESSION_EXPIRED"}), 401
        return f(*args, **kwargs)
    return wrapped

def calc_indicators(candles):
    # Indicadores simples: SMA20 y RSI
    closes = np.array([c['close'] for c in candles], dtype=float)
    if len(closes) < 20:
        return None
    sma20 = float(np.mean(closes[-20:]))
    # RSI sencillo
    deltas = np.diff(closes)
    up = deltas[deltas>=0].sum() / 14
    down = -deltas[deltas<0].sum() / 14
    rs = up/down if down>0 else 0
    rsi = float(100 - 100/(1+rs)) if down>0 else 100.0
    return {
        "price": float(closes[-1]),
        "sma20": sma20,
        "rsi": rsi
    }

# -----------------------------------------------------------------------------
# ENDPOINTS HTTP
# -----------------------------------------------------------------------------
@app.before_request
def preflight():
    if request.method == 'OPTIONS':
        return make_response()

@app.route('/api/login', methods=['POST'])
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email','').strip()
    pwd   = data.get('password','')
    if not email or not pwd:
        return jsonify({
            "success": False,
            "message": "Email y contraseña son obligatorios"
        }), 400

    iq = IQ_Option(email, pwd)
    try:
        # Timeout de 15s para no colgar la petición
        with eventlet.Timeout(15, False):
            if not iq.connect():
                return jsonify({
                    "success": False,
                    "message": "Error conectando IQ Option"
                }), 503
    except Exception:
        return jsonify({
            "success": False,
            "message": "Timeout al conectar IQ Option"
        }), 504

    # Guardar sesión
    with sessions_lock:
        user_sessions[email] = iq
    session['user_email'] = email
    session.permanent = True

    send_telegram(f"🎯 Login: `{email}` – {datetime.datetime.now().isoformat()}")
    return jsonify({"success": True, "user": {"email": email}})

@app.route('/api/logout', methods=['POST'])
@app.route('/logout', methods=['POST'])
@require_auth
def logout():
    email = session['user_email']
    with bots_lock:
        active_bots[email] = False
    with sessions_lock:
        user_sessions.pop(email, None)
    session.clear()
    send_telegram(f"👋 Logout: `{email}` – {datetime.datetime.now().isoformat()}")
    return jsonify({"success": True})

@app.route('/api/balance', methods=['GET'])
@app.route('/balance', methods=['GET'])
@require_auth
def get_balance():
    email = session['user_email']
    iq = user_sessions[email]
    bal = iq.get_balance()
    return jsonify({"balance": bal})

@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    # Ejemplo estático; adapta si deseas obtener dinámicamente
    syms = ["EURUSD","GBPUSD","USDJPY","AUDUSD","EURUSD-OTC"]
    return jsonify({"symbols": syms})

@app.route('/api/start_bot', methods=['POST'])
@app.route('/start_bot', methods=['POST'])
@require_auth
def start_bot():
    email = session['user_email']
    with bots_lock:
        if active_bots.get(email, False):
            return jsonify({"error": "Bot ya activo"}), 400
        active_bots[email] = True

    config = request.get_json() or {}
    def _run():
        iq = user_sessions[email]
        while active_bots.get(email):
            candles = iq.get_candles(
                config.get('symbol','EURUSD'),
                60, 100, time.time()
            )
            ind = calc_indicators(candles)
            socketio.emit('analysis', ind or {}, room=email)
            time.sleep(5)
        socketio.emit('bot_stopped', {"email": email}, room=email)

    Thread(target=_run, daemon=True).start()
    send_telegram(f"🚀 Bot started: `{email}` – {config.get('symbol','EURUSD')}")
    return jsonify({"started": True})

@app.route('/api/stop_bot', methods=['POST'])
@app.route('/stop_bot', methods=['POST'])
@require_auth
def stop_bot():
    email = session['user_email']
    active_bots[email] = False
    send_telegram(f"🛑 Bot stopped: `{email}`")
    return jsonify({"stopped": True})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "time": datetime.datetime.now().isoformat()
    })

# -----------------------------------------------------------------------------
# SOCKET.IO EVENTS
# -----------------------------------------------------------------------------
@socketio.on('connect')
def on_connect():
    room = request.sid
    join_room(room)
    emit('connected', {"sid": room})

# -----------------------------------------------------------------------------
# ARRANQUE
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    logger.info("🚀 Starting Flask main.py")
    socketio.run(app,
                 host='0.0.0.0',
                 port=int(os.getenv('PORT', 5000)))
