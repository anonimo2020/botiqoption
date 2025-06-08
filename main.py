# backend.py – Backend Flask inspirado en "IQ OPTION BOT" pero sin dependencia nativa de TA‑Lib
# Funciona con el frontend Trading Bot Pro que compartiste y corre en Render
# -----------------------------------------------------------------------------
# REQUISITOS (requirements.txt)
# -----------------------------------------------------------------------------
# flask
# flask-session
# flask-cors
# flask-socketio
# eventlet
# flask-limiter
# iqoptionapi
# numpy
# (opcional) ta-lib‑binary; si no está disponible usamos cálculo manual
# python-telegram-bot==13.15  # o requests
# -----------------------------------------------------------------------------
# VARIABLES DE ENTORNO NECESARIAS
# -----------------------------------------------------------------------------
# FLASK_SECRET_KEY= cambia‑esto
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
# ALLOWED_ORIGINS=https://iqoptionbot.ct.ws,http://localhost:3000
# -----------------------------------------------------------------------------

import os, time, logging, datetime, json
from threading import Thread, Lock
from functools import wraps
from typing import Optional, Dict

import eventlet
eventlet.monkey_patch()  # SocketIO + requests non‑blocking

import numpy as np
try:
    import talib                # intentamos usar TA‑Lib si existe
    USE_TALIB = True
except ModuleNotFoundError:      # Render free tier no tiene la librería nativa
    talib = None
    USE_TALIB = False

import requests
from iqoptionapi.stable_api import IQ_Option

from flask import Flask, request, jsonify, session, make_response
from flask_session import Session
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, join_room, leave_room

# -----------------------------------------------------------------------------
# CONFIG FLASK
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "dev‑key"),
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

socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode="eventlet", logger=False)

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("tbp_backend")

# -----------------------------------------------------------------------------
# ALMACENES EN MEMORIA
# -----------------------------------------------------------------------------
user_iq: Dict[str, IQ_Option] = {}      # email ➜ iq instance
active_bots: Dict[str, bool] = {}       # email ➜ running?
user_metrics: Dict[str, dict] = {}      # email ➜ métricas acumuladas

_sessions_lock, _bots_lock = Lock(), Lock()

# -----------------------------------------------------------------------------
# TELEGRAM
# -----------------------------------------------------------------------------
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID")

def tg_send(msg: str):
    if not (TG_TOKEN and TG_CHAT):
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TG_CHAT, "text": msg}, timeout=10)
    except Exception as e:
        logger.warning(f"Telegram error: {e}")

# -----------------------------------------------------------------------------
# DECORADOR AUTH
# -----------------------------------------------------------------------------

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
            logger.info("Reconectando IQOption…")
            if not iq.connect():
                return jsonify({"error": "CONNECTION_LOST"}), 401
        return fn(*args, **kwargs)
    return _wrap

# -----------------------------------------------------------------------------
# INDICADORES (fallback manual si no hay TA‑Lib)
# -----------------------------------------------------------------------------
RSI_PERIOD, BB_PERIOD, BB_STD = 14, 20, 2
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
STO_PERIOD = 14

MIN_CANDLES = 60


def _ema(arr, period):
    alpha = 2 / (period + 1)
    ema = [np.mean(arr[:period])]
    for price in arr[period:]:
        ema.append(alpha * price + (1 - alpha) * ema[-1])
    return np.array(ema)


def calc_indicators(candles):
    if len(candles) < MIN_CANDLES:
        return None
    closes = np.array([float(c["close"]) for c in candles])
    highs  = np.array([float(c["max"])   for c in candles])
    lows   = np.array([float(c["min"])   for c in candles])
    price = closes[-1]

    if USE_TALIB:
        rsi = talib.RSI(closes, RSI_PERIOD)[-1]
        macd, macd_signal, _ = talib.MACD(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        macd, macd_signal = macd[-1], macd_signal[-1]
        upper, mid, lower = talib.BBANDS(closes, BB_PERIOD, BB_STD, BB_STD)
        upper, lower = upper[-1], lower[-1]
        stoch_k, stoch_d = talib.STOCH(highs, lows, closes, STO_PERIOD, 3, 3)
        stoch_k, stoch_d = stoch_k[-1], stoch_d[-1]
    else:
        # --- RSI manual ---
        deltas = np.diff(closes)
        seed = deltas[:RSI_PERIOD]
        up = seed[seed >= 0].sum() / RSI_PERIOD
        down = -seed[seed < 0].sum() / RSI_PERIOD
        rs = up / down if down != 0 else 0
        rsi_series = np.zeros_like(closes)
        rsi_series[:RSI_PERIOD] = 100. - 100. / (1. + rs) if down != 0 else 100
        for i in range(RSI_PERIOD, len(closes)):
            delta = deltas[i-1]
            upval = max(delta, 0)
            downval = -min(delta, 0)
            up = (up * (RSI_PERIOD - 1) + upval) / RSI_PERIOD
            down = (down * (RSI_PERIOD - 1) + downval) / RSI_PERIOD
            rs = up / down if down != 0 else 0
            rsi_series[i] = 100. - 100. / (1. + rs) if down != 0 else 100
        rsi = rsi_series[-1]

        # --- MACD manual ---
        ema_fast = _ema(closes, MACD_FAST)
        ema_slow = _ema(closes, MACD_SLOW)
        macd_line = ema_fast[-len(ema_slow):] - ema_slow
        macd_signal = _ema(macd_line, MACD_SIGNAL)[-1]
        macd = macd_line[-1]

        # --- Bollinger ---
        sma = np.convolve(closes, np.ones(BB_PERIOD)/BB_PERIOD, mode="valid")
        sma20 = sma[-1]
        std20 = closes[-BB_PERIOD:].std()
        upper, lower = sma20 + BB_STD*std20, sma20 - BB_STD*std20

        # --- Stochastic %K/%D ---
        lowest_low = lows[-STO_PERIOD:].min()
        highest_high = highs[-STO_PERIOD:].max()
        stoch_k = 100 * (price - lowest_low) / (highest_high - lowest_low) if highest_high != lowest_low else 50
        stoch_d = stoch_k  # simplificado (3‑period SMA podría añadirse)

    return {
        "price": price, "rsi": rsi,
        "macd": macd, "macd_signal": macd_signal,
        "upper": upper, "lower": lower,
        "stoch_k": stoch_k,
    }

# -----------------------------------------------------------------------------
# ESTRATEGIA
# -----------------------------------------------------------------------------

def decide(ind):
    if not ind:
        return None
    score = 0
    if ind["rsi"] < 30: score += 2
    if ind["rsi"] > 70: score -= 2
    if ind["macd"] > ind["macd_signal"]: score += 2
    if ind["macd"] < ind["macd_signal"]: score -= 2
    if ind["stoch_k"] < 20: score += 1
    if ind["stoch_k"] > 80: score -= 1
    if ind["price"] < ind["lower"]: score += 1
    if ind["price"] > ind["upper"]: score -= 1
    if score >= 3:
        return "call", score*12.5
    if score <= -3:
        return "put", abs(score)*12.5
    return None

# -----------------------------------------------------------------------------
# ENDPOINTS  (idénticos a la versión previa)
# -----------------------------------------------------------------------------

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
            try: user_iq[email].close_websocket()
            except: pass
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

    profile = iq.get_profile() or {}
    balance = iq.get_balance()
    account_type = iq.get_balance_mode()

    with _sessions_lock:
        user_iq[email] = iq
    session["user_email"] = email

    user_metrics[email] = {"start_balance": balance, "profit": 0, "total_trades": 0, "wins": 0, "losses": 0}

    tg_send(f"🔑 Nuevo login: {email} | Balance ${balance:.2f} | {account_type}")
    return jsonify({"success": True, "user": {"name": profile.get("name", "Usuario"), "email": email, "balance": balance}})


@app.route("/api/logout", methods=["
