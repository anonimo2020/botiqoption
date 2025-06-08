# backend.py – Backend Flask inspirado en "IQ OPTION BOT".  Versión estable sin TA‑Lib ni errores de sintaxis.
# ----------------------------------------------------------------------------------
# REQUIREMENTS (requirements.txt)
# flask
# flask-session
# flask-cors
# flask-socketio
# eventlet
# flask-limiter
# iqoptionapi
# numpy
# requests  # para Telegram
# ----------------------------------------------------------------------------------
# ENV VARS
# FLASK_SECRET_KEY=change-me
# TELEGRAM_BOT_TOKEN=<token>
# TELEGRAM_CHAT_ID=<chat id>
# ALLOWED_ORIGINS=https://iqoptionbot.ct.ws,http://localhost:3000
# ----------------------------------------------------------------------------------

import os, time, datetime, logging, json, eventlet, numpy as np
from threading import Thread, Lock
from functools import wraps
from typing import Dict

eventlet.monkey_patch()

from iqoptionapi.stable_api import IQ_Option
import requests
from flask import Flask, request, jsonify, session, make_response
from flask_session import Session
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, join_room, leave_room

# ----------------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------------

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "dev-key"),
    SESSION_TYPE="filesystem",
    SESSION_COOKIE_NAME="tbp_session",
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_PERMANENT=False,
)
Session(app)

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
CORS(app, supports_credentials=True, origins=ALLOWED_ORIGINS)

limiter = Limiter(app, key_func=get_remote_address, default_limits=["200/day", "50/hour"])

socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode="eventlet")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("tbp_backend")

# ----------------------------------------------------------------------------------
# IN‑MEMORY STORES
# ----------------------------------------------------------------------------------

user_iq: Dict[str, IQ_Option] = {}
active_bots: Dict[str, bool] = {}
user_metrics: Dict[str, dict] = {}
_sessions_lock, _bots_lock = Lock(), Lock()

# ----------------------------------------------------------------------------------
# TELEGRAM
# ----------------------------------------------------------------------------------

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

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

# ----------------------------------------------------------------------------------
# AUTH DECORATOR
# ----------------------------------------------------------------------------------

def require_auth(fn):
    @wraps(fn)
    def _wrap(*args, **kwargs):
        email = session.get("user_email")
        if not email:
            return jsonify({"error": "AUTH_REQUIRED"}), 401
        with _sessions_lock:
            if email not in user_iq:
                session.clear()
                return jsonify({"error": "SESSION_EXPIRED"}), 401
            iq = user_iq[email]
        if not iq.check_connect():
            if not iq.connect():
                return jsonify({"error": "CONNECTION_LOST"}), 401
        return fn(*args, **kwargs)
    return _wrap

# ----------------------------------------------------------------------------------
# SIMPLE INDICATORS (NumPy‑only)
# ----------------------------------------------------------------------------------

RSI_PERIOD = 14
BB_PERIOD = 20
BB_STD = 2
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
STO_PERIOD = 14


def _ema(arr, period):
    alpha = 2 / (period + 1)
    ema = [np.mean(arr[:period])]
    for price in arr[period:]:
        ema.append(alpha * price + (1 - alpha) * ema[-1])
    return np.array(ema)


def calc_indicators(candles):
    if len(candles) < 30:
        return None
    closes = np.array([float(c["close"]) for c in candles])
    highs = np.array([float(c["max"]) for c in candles])
    lows = np.array([float(c["min"]) for c in candles])
    price = closes[-1]

    # RSI
    deltas = np.diff(closes)
    seed = deltas[:RSI_PERIOD]
    up = seed[seed >= 0].sum() / RSI_PERIOD
    down = -seed[seed < 0].sum() / RSI_PERIOD
    rs = up / down if down else 0
    rsi_series = np.zeros_like(closes)
    rsi_series[:RSI_PERIOD] = 100 - 100 / (1 + rs) if down else 100
    for i in range(RSI_PERIOD, len(closes)):
        delta = deltas[i - 1]
        upval = max(delta, 0)
        downval = -min(delta, 0)
        up = (up * (RSI_PERIOD - 1) + upval) / RSI_PERIOD
        down = (down * (RSI_PERIOD - 1) + downval) / RSI_PERIOD
        rs = up / down if down else 0
        rsi_series[i] = 100 - 100 / (1 + rs) if down else 100
    rsi = float(rsi_series[-1])

    # MACD
    ema_fast = _ema(closes, MACD_FAST)
    ema_slow = _ema(closes, MACD_SLOW)
    macd_line = ema_fast[-len(ema_slow):] - ema_slow
    macd_signal = _ema(macd_line, MACD_SIGNAL)[-1]
    macd = macd_line[-1]

    # Bollinger
    sma20 = closes[-BB_PERIOD:].mean()
    std20 = closes[-BB_PERIOD:].std()
    upper = sma20 + BB_STD * std20
    lower = sma20 - BB_STD * std20

    # Stochastic
    lowest = lows[-STO_PERIOD:].min()
    highest = highs[-STO_PERIOD:].max()
    stoch_k = 100 * (price - lowest) / (highest - lowest) if highest != lowest else 50

    return {"price": price, "rsi": rsi, "macd": macd, "macd_signal": macd_signal, "upper": upper, "lower": lower, "stoch_k": stoch_k}


def decide(ind):
    if not ind:
        return None
    score = 0
    if ind["rsi"] < 30:
        score += 2
    if ind["rsi"] > 70:
        score -= 2
    if ind["macd"] > ind["macd_signal"]:
        score += 2
    if ind["macd"] < ind["macd_signal"]:
        score -= 2
    if ind["stoch_k"] < 20:
        score += 1
    if ind["stoch_k"] > 80:
        score -= 1
    if ind["price"] < ind["lower"]:
        score += 1
    if ind["price"] > ind["upper"]:
        score -= 1
    if score >= 3:
        return "call", min(100, score * 12.5)
    if score <= -3:
        return "put", min(100, abs(score) * 12.5)
    return None

# ----------------------------------------------------------------------------------
# API ENDPOINTS
# ----------------------------------------------------------------------------------

@app.route("/api/login", methods=["POST"])
@limiter.limit("5/minute")
def api_login():
    data = request.get_json() or {}
    email, pwd = data.get("email", "").strip(), data.get("password", "")
    if not (email and pwd):
        return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
    logger.info(f"Login intento {email}")

    with _sessions_lock:
        if email in user_iq:
            try:
                user_iq[email].close_websocket()
            except:
                pass
            del user_iq[email]

    iq = IQ_Option(email, pwd)
    try:
        with eventlet.Timeout(15, False):
            if not iq.connect():
                return jsonify({"success": False, "message": "No se pudo conectar a IQ Option"}), 503
        if not iq.check_connect():
            return jsonify({"success": False, "message": "Credenciales inválidas"}), 401
    except eventlet.timeout.Timeout:
        return jsonify({"success": False, "message": "IQ Option tardó demasiado"}), 504

    balance = iq.get_balance()
    with _sessions_lock:
        user_iq[email] = iq
    session["user_email"] = email
    user_metrics[email] = {"start_balance": balance, "profit": 0}
    tg_send(f"🔑 Nuevo login: {email} | Balance ${balance:.2f}")
    return jsonify({"success": True, "user": {"email": email, "balance": balance}})


@app.route("/api/logout", methods=["POST"])
@require_auth
def api_logout():
    email = session.get("user_email")
    with _bots_lock:
        active_bots[email] = False
    with _sessions_lock:
        try:
            user_iq[email].close_websocket()
        except:
            pass
        user_iq.pop(email, None)
    session.clear()
    tg_send(f"👋 Logout: {email}")
    return jsonify({"success": True})


@app.route("/api/balance", methods=["GET"])
@require_auth
def api_balance():
    email = session["user_email"]
    iq = user_iq[email]
    bal = iq.get_balance()
    return jsonify({"balance": bal})


@app.route("/api/symbols", methods=["GET"])
@require_auth
def api_symbols():
    # lista fija simplificada
    return jsonify({"symbols": [
        {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
        {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
        {"symbol": "USDJPY"}]
