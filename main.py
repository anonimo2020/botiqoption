# backend.py – API REST + WebSocket para Trading Bot Pro con IQ Option y Telegram
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

# parcheo para sockets/eventlet
eventlet.monkey_patch()

from iqoptionapi.stable_api import IQ_Option
import requests
from flask import Flask, request, jsonify, session
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

# CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://iqoptionbot.ct.ws").split(",")
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
enabled_lock = Lock()
user_sessions = {}
active_bots = {}

# Telegram config
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(msg: str):
    if TG_TOKEN and TG_CHAT:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"}
        )

# -----------------------------------------------------------------------------
# UTILIDADES
# -----------------------------------------------------------------------------
def require_auth(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        email = session.get('user_email')
        if not email or email not in user_sessions:
            return jsonify({"error": "AUTH_REQUIRED"}), 401
        return f(*args, **kwargs)
    return wrapped

# Indicadores básicos con NumPy
def calc_indicators(candles):
    closes = np.array([c['close'] for c in candles], dtype=float)
    if len(closes) < 20:
        return None
    sma20 = float(np.mean(closes[-20:]))
    delta = np.diff(closes)
    up = delta[delta>0].sum()/14
    down = -delta[delta<0].sum()/14
    rsi = float(100 - 100/(1 + up/(down+1e-6)))
    return {"price": float(closes[-1]), "sma20": sma20, "rsi": rsi}

# -----------------------------------------------------------------------------
# ENDPOINTS HTTP
# -----------------------------------------------------------------------------
@app.route('/api/login', methods=['POST'])
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = data.get('email', '').strip()
    pwd   = data.get('password', '')
    if not email or not pwd:
        return jsonify({"success": False, "message": "Email y contraseña obligatorios"}), 400

    iq = IQ_Option(email, pwd)
    try:
        with eventlet.Timeout(15, False):
            if not iq.connect():
                return jsonify({"success": False, "message": "Error conectando IQ Option"}), 503
    except Exception:
        return jsonify({"success": False, "message": "Timeout IQ Option"}), 504

    user_sessions[email] = iq
    session['user_email'] = email
    session.permanent = True
    send_telegram(f"🎯 Login: `{email}` @ {datetime.datetime.now().isoformat()}")
    return jsonify({"success": True, "user": {"email": email}})

@app.route('/api/logout', methods=['POST'])
@app.route('/logout', methods=['POST'])
@require_auth
def logout():
    email = session.pop('user_email', None)
    active_bots[email] = False
    user_sessions.pop(email, None)
    send_telegram(f"👋 Logout: `{email}` @ {datetime.datetime.now().isoformat()}")
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
    return jsonify({"symbols": ["EURUSD","GBPUSD","USDJPY","AUDUSD"]})

@app.route('/api/start_bot', methods=['POST'])
@app.route('/start_bot', methods=['POST'])
@require_auth
def start_bot():
    email = session['user_email']
    if active_bots.get(email):
        return jsonify({"error": "Bot already running"}), 400
    active_bots[email] = True
    cfg = request.get_json() or {}

    def run():
        iq = user_sessions[email]
        while active_bots.get(email):
            candles = iq.get_candles(cfg.get('symbol','EURUSD'),60,100,time.time())
            ind = calc_indicators(candles)
            socketio.emit('analysis', ind or {}, room=email)
            time.sleep(5)
        socketio.emit('bot_stopped', {"email": email}, room=email)
    Thread(target=run, daemon=True).start()
    send_telegram(f"🚀 Bot started: `{email}` {cfg.get('symbol','EURUSD')}")
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
    return jsonify({"status": "ok", "time": datetime.datetime.now().isoformat()})

# -----------------------------------------------------------------------------
# SOCKET.IO EVENTS
# -----------------------------------------------------------------------------
@socketio.on('connect')
def on_connect():
    room = session.get('user_email', request.sid)
    join_room(room)
    emit('connected', {"sid": room})

# -----------------------------------------------------------------------------
# ARRANQUE
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    logger.info("🚀 Starting main.py")
    socketio.run(app, host='0.0.0.0', port=int(os.getenv('PORT',5000)))
