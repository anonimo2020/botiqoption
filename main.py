# 🚨 ¡ESTO DEBE IR PRIMERO!
import eventlet
eventlet.monkey_patch()

import os
import threading
import time
from dotenv import load_dotenv
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room, leave_room
from iqoptionapi.stable_api import IQ_Option

# Cargar .env si es local
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "insecure-default")  # Setea FLASK_SECRET_KEY en Render
CORS(app, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Sesiones de usuario y bots
sessions = {}

# ====================
# Hilo del Bot
# ====================
class BotThread(threading.Thread):
    def __init__(self, user_id, iq, symbol, amount, martingalas, account_type):
        super().__init__()
        self.user_id = user_id
        self.iq = iq
        self.symbol = symbol
        self.amount = amount
        self.martingalas = martingalas
        self.account_type = account_type
        self.running = True

    def run(self):
        socketio.emit("bot_status", {"message": "Bot iniciado", "status": "running"}, room=self.user_id)
        while self.running:
            check, id = self.iq.buy(self.amount, self.symbol, "call", 1)
            if check:
                while self.iq.get_async_order(id) is None:
                    time.sleep(1)
                result = self.iq.check_win_v4(id)
                result_type = "WIN" if result > 0 else "LOSS" if result < 0 else "DRAW"
                socketio.emit("trade_result", {
                    "symbol": self.symbol,
                    "amount": self.amount,
                    "result": result_type,
                    "profit": result
                }, room=self.user_id)
            time.sleep(10)
        socketio.emit("bot_status", {"message": "Bot detenido", "status": "stopped"}, room=self.user_id)

    def stop(self):
        self.running = False

# ====================
# Rutas HTTP
# ====================
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email, password = data.get("email"), data.get("password")
    iq = IQ_Option(email, password)
    iq.connect()
    if iq.check_connect():
        session["user_id"] = email
        iq.change_balance("PRACTICE")
        balance = iq.get_balance()
        sessions[email] = {"iq": iq, "bot": None}
        return jsonify(success=True, user={"email": email, "balance": balance, "account_type": "PRACTICE"})
    return jsonify(success=False, message="Credenciales inválidas o fallo al conectar")

@app.route("/logout", methods=["POST"])
def logout():
    user_id = session.get("user_id")
    if user_id in sessions:
        sessions[user_id]["iq"].close()
        sessions.pop(user_id)
    session.clear()
    return jsonify(success=True)

@app.route("/symbols")
def symbols():
    user_id = session.get("user_id")
    if user_id not in sessions:
        return jsonify(success=False, error="No autenticado"), 401
    iq = sessions[user_id]["iq"]
    activos = iq.get_all_open_time()
    pares = [p for p, v in activos["binary"].items() if v["open"]]
    return jsonify(symbols=pares)

@app.route("/start_bot", methods=["POST"])
def start_bot():
    user_id = session.get("user_id")
    if user_id not in sessions:
        return jsonify(error="No autenticado"), 401
    data = request.get_json()
    symbol = data["symbol"]
    amount = float(data["amount"])
    martingalas = int(data["martingalas"])
    account_type = data["account_type"]

    iq = sessions[user_id]["iq"]
    iq.change_balance(account_type)
    bot = BotThread(user_id, iq, symbol, amount, martingalas, account_type)
    bot.start()
    sessions[user_id]["bot"] = bot
    return jsonify(message="Bot iniciado")

@app.route("/stop_bot", methods=["POST"])
def stop_bot():
    user_id = session.get("user_id")
    if user_id in sessions and sessions[user_id]["bot"]:
        sessions[user_id]["bot"].stop()
        sessions[user_id]["bot"] = None
        return jsonify(message="Bot detenido")
    return jsonify(error="No hay bot activo"), 400

# ====================
# Socket.IO
# ====================
@socketio.on("connect")
def on_connect():
    user_id = session.get("user_id")
    if user_id:
        join_room(user_id)
        emit("bot_status", {"message": "Conectado a Socket.IO", "status": "connected"}, room=user_id)
    else:
        emit("bot_status", {"message": "No autenticado", "status": "error"})

@socketio.on("disconnect")
def on_disconnect():
    user_id = session.get("user_id")
    if user_id:
        leave_room(user_id)

# ====================
# Run local / Render
# ====================
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
