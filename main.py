# backend.py – Versión mínima funcional (sin errores de sintaxis)
# Compatible con el frontend Trading Bot Pro
# -----------------------------------------------------------------------------
# requirements.txt (añade lo que ya tuvieras menos TA‑Lib):
# flask flask-session flask-cors flask-socketio eventlet flask-limiter iqoptionapi numpy requests
# -----------------------------------------------------------------------------

import os, time, logging, datetime, json, eventlet, numpy as np
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

limiter = Limiter(app, key_func=get_remote_address, default_limits=["200/day", "50/hour"])

socketio = SocketIO(app, async_mode="eventlet", cors_allowed_origins=ALLOWED_ORIGINS)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tbp")

# -----------------------------------------------------------------------------
# VARIABLES GLOBALES EN MEMORIA
# -----------------------------------------------------------------------------

user_iq = {}          # email -> IQ_Option
active_bots = {}      # email -> bool
_sessions_lock = Lock()
_bots_lock = Lock()

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

# -----------------------------------------------------------------------------
# UTILIDADES
# -----------------------------------------------------------------------------

def tg_send(msg: str):
    if not (TG_TOKEN and TG_CHAT):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg}, timeout=10,
        )
    except Exception as e:
        logger.warning(f"Telegram error: {e}")


def require_auth(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        email = session.get("user_email")
        if not email:
            return jsonify({"error": "AUTH_REQUIRED"}), 401
        with _sessions_lock:
            iq = user_iq.get(email)
        if iq is None:
            session.clear()
            return jsonify({"error": "SESSION_EXPIRED"}), 401
        if not iq.check_connect():
            if not iq.connect():
                return jsonify({"error": "CONNECTION_LOST"}), 401
        return fn(*args, **kwargs)
    return _wrap

# -----------------------------------------------------------------------------
# INDICADORES SIMPLES (NumPy puro)
# -----------------------------------------------------------------------------

def indicators(candles):
    if len(candles) < 30:
        return None
    closes = np.array([float(c["close"]) for c in candles])
    price = closes[-1]
    sma20 = closes[-20:].mean()
    rsi = 50  # fake placeholder
    return {"price": price, "sma20": sma20, "rsi": rsi}

# -----------------------------------------------------------------------------
# ENDPOINTS API
# -----------------------------------------------------------------------------

@app.route("/api/login", methods=["POST"])
@limiter.limit("5/minute")
def login():
    data = request.get_json() or {}
    email, password = data.get("email", "").strip(), data.get("password", "")
    if not (email and password):
        return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400

    logger.info(f"Login intento {email}")

    iq = IQ_Option(email, password)
    try:
        with eventlet.Timeout(15, False):
            if not iq.connect():
                return jsonify({"success": False, "message": "No se pudo conectar"}), 503
    except eventlet.timeout.Timeout:
        return jsonify({"success": False, "message": "IQ Option tardó demasiado"}), 504

    if not iq.check_connect():
        return jsonify({"success": False, "message": "Credenciales inválidas"}), 401

    balance = iq.get_balance()
    with _sessions_lock:
        user_iq[email] = iq
    session["user_email"] = email

    tg_send(f"🔑 Login {email} | ${balance:.2f}")
    return jsonify({"success": True, "user": {"email": email, "balance": balance}})


@app.route("/api/logout", methods=["POST"])
@require_auth
def logout():
    email = session["user_email"]
    with _bots_lock:
        active_bots[email] = False
    with _sessions_lock:
        iq = user_iq.pop(email, None)
    if iq:
        try:
            iq.close_websocket()
        except:
            pass
    session.clear()
    tg_send(f"👋 Logout {email}")
    return jsonify({"success": True})


@app.route("/api/balance", methods=["GET"])
@require_auth
def balance():
    email = session["user_email"]
    iq = user_iq[email]
    bal = iq.get_balance()
    return jsonify({"balance": bal})


@app.route("/api/symbols", methods=["GET"])
@require_auth
def symbols():
    symbols_list = [
        {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
        {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
        {"symbol": "USDJPY", "name": "USD/JPY", "type": "forex"},
    ]
    return jsonify({"symbols": symbols_list})


@app.route("/api/start_bot", methods=["POST"])
@require_auth
def start_bot():
    # stub simplificado – solo marca activo y emite evento
    email = session["user_email"]
    with _bots_lock:
        if active_bots.get(email):
            return jsonify({"error": "Bot ya activo"}), 400
        active_bots[email] = True
    socketio.emit("analysis", {"message": "Bot iniciado"}, room=request.sid)
    return jsonify({"message": "Bot iniciado"})


@app.route("/api/stop_bot", methods=["POST"])
@require_auth
def stop_bot():
    email = session["user_email"]
    with _bots_lock:
        active_bots[email] = False
    socketio.emit("bot_stopped", {"reason": "manual"}, room=request.sid)
    return jsonify({"message": "Bot detenido"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "alive", "time": datetime.datetime.utcnow().isoformat()})

# -----------------------------------------------------------------------------
# SOCKET.IO EVENTS
# -----------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    join_room(request.sid)
    emit("connected", {"sid": request.sid})


@socketio.on("disconnect")
def on_disconnect():
    leave_room(request.sid)

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info(f"🔧 Backend listening on {port}")
    socketio.run(app, host="0.0.0.0", port=port)
