# backend.py – Backend Flask inspirado en "IQ OPTION BOT" pero expuesto como API REST + SocketIO
# Funciona con el frontend Trading Bot Pro que compartiste.
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
# ta-lib
# python-telegram-bot==13.15  # o simplemente requests para un POST manual
# -----------------------------------------------------------------------------
# VARIABLES DE ENTORNO NECESARIAS
# -----------------------------------------------------------------------------
# FLASK_SECRET_KEY= cambia‑esto
# TELEGRAM_BOT_TOKEN=xxx
# TELEGRAM_CHAT_ID=xxx
# ALLOWED_ORIGINS=https://iqoptionbot.ct.ws,http://localhost:3000
# -----------------------------------------------------------------------------

import os, time, logging, datetime, json
from threading import Thread, Lock
from functools import wraps
from typing import Optional, Dict

import eventlet
eventlet.monkey_patch()  # SocketIO + requests non‑blocking

import numpy as np
import talib
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
        if not iq.check_connect():  # reconectar rápido
            logger.info("Reconectando IQOption…")
            if not iq.connect():
                return jsonify({"error": "CONNECTION_LOST"}), 401
        return fn(*args, **kwargs)
    return _wrap

# -----------------------------------------------------------------------------
# INDICADORES Y SEÑAL
# -----------------------------------------------------------------------------
RSI_PERIOD, BB_PERIOD, BB_STD = 14, 20, 2
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
STO_K, STO_D = 14, 3

MIN_CANDLES = 60


def calc_indicators(candles):
    if len(candles) < MIN_CANDLES:
        return None
    closes = np.array([float(c["close"]) for c in candles])
    highs  = np.array([float(c["max"])   for c in candles])
    lows   = np.array([float(c["min"])   for c in candles])
    rsi = talib.RSI(closes, RSI_PERIOD)[-1]
    macd, macd_signal, _ = talib.MACD(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    macd, macd_signal = macd[-1], macd_signal[-1]
    upper, mid, lower = talib.BBANDS(closes, BB_PERIOD, BB_STD, BB_STD)
    upper, lower = upper[-1], lower[-1]
    stoch_k, stoch_d = talib.STOCH(highs, lows, closes, STO_K, 3, STO_D)
    stoch_k, stoch_d = stoch_k[-1], stoch_d[-1]
    price = closes[-1]
    return {
        "price": price, "rsi": rsi,
        "macd": macd, "macd_signal": macd_signal,
        "upper": upper, "lower": lower,
        "stoch_k": stoch_k, "stoch_d": stoch_d,
    }


def decide(ind):
    if not ind:
        return None
    score = 0
    if ind["rsi"] < 30: score += 2
    if ind["rsi"] > 70: score -= 2
    if ind["macd"] > ind["macd_signal"]: score += 2
    if ind["macd"] < ind["macd_signal"]: score -= 2
    if ind["stoch_k"] < 20 and ind["stoch_d"] < 20: score += 1
    if ind["stoch_k"] > 80 and ind["stoch_d"] > 80: score -= 1
    if ind["price"] < ind["lower"]: score += 1
    if ind["price"] > ind["upper"]: score -= 1
    if score >= 3:
        return "call", abs(score) * 12.5
    if score <= -3:
        return "put", abs(score) * 12.5
    return None

# -----------------------------------------------------------------------------
# ENDPOINTS
# -----------------------------------------------------------------------------

@app.route("/api/login", methods=["POST"])
@limiter.limit("5/minute")
def api_login():
    data = request.get_json() or {}
    email, pwd = data.get("email", "").strip(), data.get("password", "")
    if not (email and pwd):
        return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
    logger.info(f"Login intento {email}")

    # cerrar sesión previa
    with _sessions_lock:
        if email in user_iq:
            try:
                user_iq[email].close_websocket()
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

    user_metrics[email] = {
        "start_balance": balance, "profit": 0,
        "total_trades": 0, "wins": 0, "losses": 0,
    }

    tg_send(f"🔑 Nuevo login: {email} | Balance ${balance:.2f} | {account_type}")
    return jsonify({"success": True, "user": {"name": profile.get("name", "Usuario"), "email": email, "balance": balance}})


@app.route("/api/logout", methods=["POST"])
@require_auth
def api_logout():
    email = session.pop("user_email")
    with _bots_lock:
        active_bots[email] = False
    with _sessions_lock:
        if email in user_iq:
            try: user_iq[email].close_websocket()
            except: pass
            del user_iq[email]
    tg_send(f"👋 Logout {email}")
    return jsonify({"success": True})


@app.route("/api/balance", methods=["GET"])
@require_auth
def api_balance():
    email = session["user_email"]
    iq = user_iq[email]
    bal = iq.get_balance()
    return jsonify({"balance": bal, "metrics": user_metrics.get(email)})


@app.route("/api/symbols", methods=["GET"])
@require_auth
def api_symbols():
    symbols = [  # se puede hacer dinámico llamando iq.get_all_open_time()
        {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
        {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
        {"symbol": "USDJPY", "name": "USD/JPY", "type": "forex"},
        {"symbol": "EURUSD-OTC", "name": "EUR/USD OTC", "type": "otc"},
    ]
    return jsonify({"symbols": symbols})


@app.route("/api/start_bot", methods=["POST"])
@require_auth
@limiter.limit("3/minute")
def api_start_bot():
    email = session["user_email"]
    data = request.get_json() or {}
    cfg = {
        "symbol": data.get("symbol", "EURUSD"),
        "amount": float(data.get("amount", 1)),
        "martingalas": int(data.get("martingalas", 0)),
        "stop_loss": float(data.get("stop_loss", 0)),
        "take_profit": float(data.get("take_profit", 0)),
    }
    with _bots_lock:
        if active_bots.get(email):
            return jsonify({"error": "Bot ya activo"}), 400
        active_bots[email] = True
    sid = request.sid  # SID de websocket (si existe); puede ser None en REST puro
    Thread(target=_bot_worker, args=(email, cfg, sid), daemon=True).start()
    return jsonify({"message": "Bot iniciado", "config": cfg})


@app.route("/api/stop_bot", methods=["POST"])
@require_auth
def api_stop_bot():
    email = session["user_email"]
    with _bots_lock:
        active_bots[email] = False
    return jsonify({"message": "Stop enviado"})

# -----------------------------------------------------------------------------
# WEBSOCKET EVENTS
# -----------------------------------------------------------------------------
@socketio.on("connect")
def ws_connect():
    join_room(request.sid)
    emit("connected", {"sid": request.sid})

@socketio.on("disconnect")
def ws_disc():
    leave_room(request.sid)

# keepalive
@socketio.on("ping")
def ws_ping():
    emit("pong")

# -----------------------------------------------------------------------------
# BOT WORKER
# -----------------------------------------------------------------------------

def _bot_worker(email: str, cfg: dict, sid: Optional[str]):
    iq = user_iq[email]
    logger.info(f"🚀 Bot para {email} {cfg}")
    tg_send(f"🚀 Bot iniciado {email} {cfg['symbol']} ${cfg['amount']}")
    base_amount = cfg["amount"]
    amount = base_amount
    marti_max = cfg["martingalas"]
    consecutive_losses = 0
    profit_session = 0

    try:
        while active_bots.get(email):
            # asegurar conexión
            if not iq.check_connect():
                iq.connect()
                time.sleep(2)
                continue
            candles = iq.get_candles(cfg["symbol"], 60, MIN_CANDLES, time.time())
            ind = calc_indicators(candles)
            decision = decide(ind)
            if sid and ind:
                socketio.emit("analysis", {"indicators": ind, "signal": decision[0] if decision else None}, room=sid)
            if decision and decision[1] >= 60:  # confianza ≥60
                direction = decision[0]
                # abrir operación
                status, order_id = iq.buy(amount, cfg["symbol"], direction, 1)
                if not status:
                    logger.warning("No se pudo abrir operación")
                    time.sleep(10)
                    continue
                if sid:
                    socketio.emit("trade_opened", {"order_id": order_id, "direction": direction, "amount": amount}, room=sid)
                time.sleep(65)
                profit = iq.check_win(order_id)
                result = "WIN" if profit > 0 else "LOSS" if profit < 0 else "DRAW"
                if sid:
                    socketio.emit("trade_closed", {"order_id": order_id, "result": result, "profit": profit}, room=sid)

                # métricas
                m = user_metrics[email]
                m["total_trades"] += 1
                if profit > 0:
                    m["wins"] += 1
                    amount = base_amount
                    consecutive_losses = 0
                elif profit < 0:
                    m["losses"] += 1
                    consecutive_losses += 1
                    if consecutive_losses <= marti_max:
                        amount *= 2
                    else:
                        break
                profit_session += profit
                m["profit"] = profit_session

                # stop loss / take profit
                if cfg["stop_loss"] and profit_session <= -cfg["stop_loss"]:
                    logger.info("Stop loss alcanzado")
                    break
                if cfg["take_profit"] and profit_session >= cfg["take_profit"]:
                    logger.info("Take profit alcanzado")
                    break
                time.sleep(20)
            else:
                time.sleep(30)
    finally:
        with _bots_lock:
            active_bots[email] = False
        if sid:
            socketio.emit("bot_stopped", {"session_profit": profit_session, "metrics": user_metrics.get(email)}, room=sid)
        tg_send(f"🛑 Bot detenido {email} | Profit sesión ${profit_session:.2f}")

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info(f"🎯 Ejecutando en 0.0.0.0:{port}")
    socketio.run(app, host="0.0.0.0", port=port)
