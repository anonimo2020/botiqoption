# backend.py – API Flask + IQ Option + Telegram
"""
Backend funcional (mínimo pero completo) que acompaña al frontend
proporcionado.  Provee:

- Autenticación contra IQ Option a partir de email / password recibidos
  desde el frontend (/api/login y cookies de sesión).
- Endpoints REST seguros (balance, símbolos, start/stop bot, logout).
- Comunicación tiempo‑real con el frontend mediante Socket.IO.
- Ejemplo de bot sencillo basado en RSI; ejecuta operaciones binarias de
  1 min y publica métricas al frontend y a Telegram.

Requisitos (requirements.txt):
    Flask==3.*
    Flask-SocketIO==5.*
    Flask-Session==0.5.*
    Flask-Cors==4.*
    flask-limiter==3.*
    eventlet==0.36.*
    iqoptionapi==2.*            # biblioteca no-oficial
    python-telegram-bot==20.*

Variables de entorno necesarias:
    FLASK_SECRET_KEY       – clave para firmar cookies
    TELEGRAM_BOT_TOKEN     – token del bot (BotFather)
    TELEGRAM_CHAT_ID       – chat/persona donde enviar alertas

Opcionales (para entornos de staging):
    PORT                   – puerto a escuchar (por defecto 5000)

Ejecutar (local):
    $ python backend.py

En producción (Render):
    Procfile ->  web: gunicorn --worker-class eventlet -w 1 backend:app
"""
from __future__ import annotations

import os
import time
import json
import logging
import datetime
from threading import Thread, Lock
from functools import wraps

import eventlet

#  monkey‑patch para que iqoptionapi + socketio funcionen con eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from iqoptionapi.stable_api import IQ_Option
import numpy as np
import requests

# ---------------------------------------------------------------------------
# Configuración global
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "dev_change_me"),
    SESSION_TYPE="filesystem",
    SESSION_PERMANENT=False,
    SESSION_USE_SIGNER=True,
    SESSION_COOKIE_SAMESITE="None",  #  requerido para cross‑site cookies en HTTPS
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
)
Session(app)

#  CORS: actualiza con los orígenes de tu frontend
ALLOWED_ORIGINS = [
    "https://iqoptionbot.ct.ws",  #  ejemplo en producción
    "http://localhost:3000",      #  desarrollo
]
CORS(
    app,
    supports_credentials=True,
    resources={r"/*": {"origins": ALLOWED_ORIGINS}},
)

#  Rate‑limit genérico
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["200/day", "50/hour"])

#  SocketIO (eventlet)
socketio = SocketIO(
    app,
    async_mode="eventlet",
    cors_allowed_origins=ALLOWED_ORIGINS,
    ping_interval=25,
    ping_timeout=60,
)

#  Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Estructuras de datos thread‑safe
# ---------------------------------------------------------------------------

active_iq_sessions: dict[str, IQ_Option] = {}
active_bots: dict[str, bool] = {}
user_metrics: dict[str, "Metrics"] = {}
_sessions_lock = Lock()
_bots_lock = Lock()

# ---------------------------------------------------------------------------
#  Utilidades varias
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(text: str) -> None:
    """Envia mensaje Markdown a Telegram (silencioso si no hay token)"""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Telegram error: %s", exc)

# ---------------------------------------------------------------------------
#  Métricas de trading (muy básicas)
# ---------------------------------------------------------------------------

class Metrics:
    def __init__(self, start_balance: float):
        self.start_balance = start_balance
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_profit = 0.0

    #  @prop: win rate, ROI, etc.
    def to_dict(self):
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades else 0
        roi = ((self.total_profit) / self.start_balance * 100) if self.start_balance else 0
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(win_rate, 2),
            "total_profit": round(self.total_profit, 2),
            "roi": round(roi, 2),
        }

# ---------------------------------------------------------------------------
#  Decoradores
# ---------------------------------------------------------------------------

def require_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "email" not in session:
            return jsonify({"error": "AUTH_REQUIRED"}), 401
        email = session["email"]
        with _sessions_lock:
            iq = active_iq_sessions.get(email)
        if not iq or not iq.check_connect():
            session.clear()
            return jsonify({"error": "SESSION_EXPIRED"}), 401
        return fn(*args, **kwargs)

    return wrapper

# ---------------------------------------------------------------------------
#  Helpers de indicadores (ejemplo RSI y SMA20)
# ---------------------------------------------------------------------------

def calc_indicators(candles):
    closes = np.array([float(c["close"]) for c in candles])
    sma20 = closes[-20:].mean()
    #  RSI simple
    deltas = np.diff(closes)
    seed = deltas[:14]
    up = seed[seed >= 0].sum() / 14
    down = -seed[seed < 0].sum() / 14
    rs = up / down if down else 0
    rsi = 100 - 100 / (1 + rs)
    return {"price": float(closes[-1]), "sma20": float(sma20), "rsi": round(rsi, 2)}

# ---------------------------------------------------------------------------
#  ENDPOINTS
# ---------------------------------------------------------------------------

@app.route("/api/login", methods=["POST"])
@limiter.limit("5/minute")
def login():
    body = request.json or {}
    email = body.get("email", "").strip()
    password = body.get("password", "")
    if not email or not password:
        return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400

    log.info("Login intento %s", email)

    #  Cerrar sesión previa (si la hubiera)
    with _sessions_lock:
        if email in active_iq_sessions:
            try:
                active_iq_sessions[email].close_websocket()
            except Exception:
                pass
            del active_iq_sessions[email]

    iq = IQ_Option(email, password)
    if not iq.connect():
        return jsonify({"success": False, "message": "Error conectando a IQ Option"}), 401
    if not iq.check_connect():
        return jsonify({"success": False, "message": "Credenciales inválidas"}), 401

    profile = iq.get_profile()
    balance = iq.get_balance()

    with _sessions_lock:
        active_iq_sessions[email] = iq
    session["email"] = email

    if email not in user_metrics:
        user_metrics[email] = Metrics(balance)

    send_telegram(f"📥 *Nuevo login*: {email}\n💰 Balance: ${balance:.2f}")

    return jsonify({
        "success": True,
        "user": {
            "name": profile.get("name", "Usuario"),
            "email": email,
            "balance": balance,
        },
    })


@app.route("/api/logout", methods=["POST"])
@require_login
def logout():
    email = session.pop("email")
    with _sessions_lock:
        iq = active_iq_sessions.pop(email, None)
    if iq:
        try:
            iq.close_websocket()
        except Exception:  # noqa: BLE001
            pass
    with _bots_lock:
        active_bots[email] = False
    send_telegram(f"👋 *Logout*: {email}")
    return jsonify({"success": True})


@app.route("/api/balance", methods=["GET"])
@require_login
def balance():
    email = session["email"]
    with _sessions_lock:
        iq = active_iq_sessions[email]
    bal = iq.get_balance()
    met = user_metrics[email]
    met.total_profit = bal - met.start_balance
    return jsonify({"balance": bal, "metrics": met.to_dict()})


@app.route("/api/symbols", methods=["GET"])
@require_login
def symbols():
    #  En producción usar IQ Option para listar activos; aquí hard‑code comunes.
    symbols = [
        {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
        {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
        {"symbol": "USDJPY", "name": "USD/JPY", "type": "forex"},
    ]
    return jsonify({"symbols": symbols})


@app.route("/api/start_bot", methods=["POST"])
@require_login
def start_bot():
    email = session["email"]
    with _bots_lock:
        if active_bots.get(email):
            return jsonify({"error": "Bot ya activo"}), 400
        active_bots[email] = True

    cfg = request.json or {}
    config = {
        "symbol": cfg.get("symbol", "EURUSD"),
        "amount": float(cfg.get("amount", 1)),
    }

    thread = Thread(target=_bot_loop, args=(email, config))
    thread.daemon = True
    thread.start()

    send_telegram(f"🚀 *Bot iniciado* {email} – {config['symbol']} ${config['amount']}")
    return jsonify({"message": "Bot iniciado"})


@app.route("/api/stop_bot", methods=["POST"])
@require_login
def stop_bot():
    email = session["email"]
    with _bots_lock:
        if not active_bots.get(email):
            return jsonify({"error": "Bot no estaba activo"}), 400
        active_bots[email] = False
    send_telegram(f"🛑 *Bot detenido* {email}")
    return jsonify({"message": "Bot detenido"})

# ---------------------------------------------------------------------------
#  Socket.IO events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def _sio_connect():
    join_room(request.sid)
    emit("connected", {"sid": request.sid})
    log.info("WS conectado %s", request.sid)

@socketio.on("disconnect")
def _sio_disconnect():
    leave_room(request.sid)
    log.info("WS desconectado %s", request.sid)

# ---------------------------------------------------------------------------
#  Lógica del bot – muy simple (RSI)
# ---------------------------------------------------------------------------

def _bot_loop(email: str, config: dict):
    with _sessions_lock:
        iq = active_iq_sessions[email]
    symbol = config["symbol"]
    amount = config["amount"]
    log.info("Bot loop iniciado %s (%s)", email, symbol)
    sid = None  #  se actualizará con cada conexión

    #  referencia a métricas
    metrics = user_metrics[email]

    while active_bots.get(email):
        if not iq.check_connect():
            iq.connect()
        candles = iq.get_candles(symbol, 60, 100, time.time())
        if not candles:
            time.sleep(30)
            continue
        ind = calc_indicators(candles)

        #  enviar al cliente activo
        if sid is None:
            #  elige cualquiera conectado perteneciente a este usuario (simplificado)
            sid = next(iter(socketio.server.manager.get_participants("/", None)), None)
        if sid:
            socketio.emit("analysis", {"indicators": ind}, room=sid)

        rsi = ind["rsi"]
        direction = None
        if rsi <= 30:
            direction = "call"
        elif rsi >= 70:
            direction = "put"

        if direction:
            log.info("%s señal %s RSI %.1f", email, direction, rsi)
            status, order_id = iq.buy(amount, symbol, direction, 1)  #  duración 1 min
            if not status:
                log.warning("Buy failed %s", email)
                time.sleep(60)
                continue
            socketio.emit("trade_opened", {"symbol": symbol, "direction": direction, "amount": amount}, room=sid)
            time.sleep(65)  #  esperar resultado
            profit = iq.check_win(order_id) or 0
            result = "WIN" if profit > 0 else "LOSS" if profit < 0 else "DRAW"
            metrics.total_trades += 1
            if profit > 0:
                metrics.wins += 1
            elif profit < 0:
                metrics.losses += 1
            metrics.total_profit += profit
            socketio.emit("trade_closed", {"result": result, "profit": profit}, room=sid)
        time.sleep(60)

    socketio.emit("bot_stopped", {"reason": "manual"}, room=sid)
    log.info("Bot loop terminado %s", email)

# ---------------------------------------------------------------------------
#  RUN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    log.info("Backend escuchando en %s", port)
    socketio.run(app, host="0.0.0.0", port=port, debug=True)
