# 🚨 ¡ESTO DEBE IR SIEMPRE PRIMERO!
import eventlet
eventlet.monkey_patch()

# Después de monkey_patch(), ya puedes importar el resto
import os
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from iqoptionapi.stable_api import IQ_Option
from dotenv import load_dotenv
import threading
import time

eventlet.monkey_patch()

app = Flask(__name__)
app.secret_key = "supersecretkey"  # Cámbialo en producción
CORS(app, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

sessions = {}

# ====================
# Helper IQ Option Bot
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
# Rutas API REST
# ====================
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email, password = data["email"], data["password"]
    iq = IQ_Option(email, password)
    iq.connect()
    if iq.check_connect():
        session["user_id"] = email
        iq.change_balance("PRACTICE")  # Default
        balance = iq.get_balance()
        sessions[email] = {"iq": iq, "bot": None}
        return jsonify(success=True, user={"email": email, "balance": balance, "account_type": "PRACTICE"})
    return jsonify(success=False, message="Credenciales inválidas o fallo al conectar")

@app.route("/logout", methods=["POST"])
def logout():
    user_id = session.get("user_id")
    if user_id and user_id in sessions:
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
    assets = iq.get_all_open_time()
    pairs = [k for k, v in assets["binary"].items() if v["open"]]
    return jsonify(symbols=pairs)

@app.route("/start_bot", methods=["POST"])
def start_bot():
    user_id = session.get("user_id")
    if user_id not in sessions:
        return jsonify(error="No autenticado"), 401

    data = request.json
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
def handle_connect():
    user_id = session.get("user_id")
    if user_id:
        emit("bot_status", {"message": "Conexión establecida", "status": "connected"}, room=request.sid)
        socketio.enter_room(request.sid, user_id)
    else:
        emit("bot_status", {"message": "No autenticado", "status": "error"})

@socketio.on("disconnect")
def handle_disconnect():
    socketio.leave_room(request.sid, session.get("user_id", ""))

# ====================
# Main
# ====================
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
