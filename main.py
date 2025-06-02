from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import threading
import requests
import time
from iqoptionapi.stable_api import IQ_Option
from datetime import datetime
import json

# --- Configuración ---
IQ_EMAIL = "sebaselwspo@gmail.com"
IQ_PASSWORD = "Octubre2001"
TELEGRAM_BOT_TOKEN = "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM"
TELEGRAM_CHAT_ID = "7009100334"

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Función para enviar mensajes a Telegram ---
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

# --- Bot principal ---
def run_bot(symbol, amount, martingalas, account):
    try:
        Iq = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
        Iq.connect()
        time.sleep(2)
        Iq.change_balance(account)

        balance = Iq.get_balance()
        socketio.emit("balance", {"balance": balance})
        send_telegram(f"✅ Bot conectado a IQ Option\nBalance: ${balance:.2f}")

        for i in range(martingalas + 1):
            status, order_id = Iq.buy(amount, symbol, "call", 1)
            if status:
                socketio.emit("operation", {"symbol": symbol, "amount": amount})
                send_telegram(f"📈 Operación {i+1}/{martingalas+1} en {symbol} enviada: ${amount:.2f}")

                # Esperar resultado real
                while True:
                    check, result = Iq.check_win_v4(order_id)
                    if check:
                        socketio.emit("result", {"result": "Ganada" if result > 0 else "Perdida", "profit": result})
                        break
                    time.sleep(1)
                break
            else:
                send_telegram(f"⚠️ Falló intento {i+1}, duplicando monto")
                amount *= 2

    except Exception as e:
        socketio.emit("error", {"msg": str(e)})
        send_telegram(f"❌ Error en ejecución del bot: {e}")

# --- API para lanzar el bot ---
@app.route("/start_bot", methods=["POST"])
def start_bot():
    try:
        data = request.get_json()
        user_symbol = data.get("symbol", "EURUSD").upper()
        amount = float(data.get("amount", 1))
        martingalas = int(data.get("martingalas", 2))
        account = data.get("account", "PRACTICE")

        # Verificar si es fin de semana y cambiar a OTC si aplica
        weekend = datetime.today().weekday() in [5, 6]
        otc_pairs = {
            "EURUSD": "EURUSD-OTC",
            "GBPUSD": "GBPUSD-OTC",
            "USDJPY": "USDJPY-OTC",
            "AUDUSD": "AUDUSD-OTC",
            "EURJPY": "EURJPY-OTC"
        }
        if weekend and user_symbol in otc_pairs:
            final_symbol = otc_pairs[user_symbol]
            send_telegram(f"🌐 Fin de semana detectado. Usando mercado OTC: {final_symbol}")
        else:
            final_symbol = user_symbol

        send_telegram(f"🚀 Lanzando bot: {final_symbol} | Monto: ${amount} | Martingalas: {martingalas} | Cuenta: {account}")

        threading.Thread(target=run_bot, args=(final_symbol, amount, martingalas, account), daemon=True).start()
        return jsonify({"message": "✅ Bot lanzado correctamente"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- API para obtener símbolos disponibles ---
@app.route("/symbols", methods=["GET"])
def get_symbols():
    weekend = datetime.today().weekday() in [5, 6]
    if weekend:
        symbols = ["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC", "EURJPY-OTC"]
    else:
        symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY"]
    response = make_response(json.dumps({"symbols": symbols}))
    response.headers["Content-Type"] = "application/json"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

# --- Inicio del servidor ---
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000)
