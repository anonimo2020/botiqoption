from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import threading
import time
import requests
from datetime import datetime
from iqoptionapi.stable_api import IQ_Option

# --- Configuración ---
IQ_EMAIL = "sebaselwspo@gmail.com"
IQ_PASSWORD = "Octubre2001"
TELEGRAM_BOT_TOKEN = "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM"
TELEGRAM_CHAT_ID = "7009100334"

iq = None
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

def run_bot(symbol, amount, martingalas, account_type):
    global iq
    try:
        iq = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
        iq.connect()
        time.sleep(2)

        if account_type == "REAL":
            iq.change_balance("REAL")
        else:
            iq.change_balance("PRACTICE")

        balance = iq.get_balance()
        send_telegram(f"✅ Conectado a IQ Option | Balance: ${balance:.2f}")
        socketio.emit("balance", {"balance": balance})

        for i in range(martingalas + 1):
            status, order_id = iq.buy(amount, symbol, "call", 1)
            if status:
                msg = f"🟢 Operación {i+1} enviada: {symbol} | Monto: ${amount:.2f}"
                send_telegram(msg)
                socketio.emit("operation", {"symbol": symbol, "amount": amount, "status": "pending"})

                result = iq.check_win_v3(order_id)
                win = float(result) > 0
                resultado = "GANADA" if win else "PERDIDA"
                profit = float(result)

                msg2 = f"📊 Resultado: {resultado} | Beneficio: ${profit:.2f}"
                send_telegram(msg2)
                socketio.emit("result", {"result": resultado, "profit": profit})
                break
            else:
                amount *= 2
                send_telegram(f"⚠️ Fallo operación {i+1}, siguiente monto: ${amount:.2f}")
                socketio.emit("error", {"msg": f"Error en intento {i+1}"})

    except Exception as e:
        send_telegram(f"❌ Error en bot: {e}")
        socketio.emit("error", {"msg": str(e)})

@app.route("/start_bot", methods=["POST"])
def start():
    try:
        data = request.get_json()
        symbol = data.get("symbol", "EURUSD").upper()
        amount = float(data.get("amount", 1))
        martingalas = int(data.get("martingalas", 2))
        account = data.get("account", "DEMO").upper()

        # Detectar fin de semana y activar OTC
        weekend = datetime.today().weekday() in [5, 6]
        otc_map = {
            "EURUSD": "EURUSD-OTC",
            "GBPUSD": "GBPUSD-OTC",
            "USDJPY": "USDJPY-OTC",
            "AUDUSD": "AUDUSD-OTC",
        }

        final_symbol = otc_map[symbol] if weekend and symbol in otc_map else symbol

        send_telegram(f"🚀 Bot lanzado con {final_symbol}, ${amount}, Martingalas: {martingalas}, Cuenta: {account}")
        socketio.emit("launch", {"symbol": final_symbol, "amount": amount, "martingalas": martingalas})

        threading.Thread(target=run_bot, args=(final_symbol, amount, martingalas, account), daemon=True).start()
        return jsonify({"msg": "Bot lanzado"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=10000)
