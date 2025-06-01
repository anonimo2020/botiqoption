from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import requests
import time
from iqoptionapi.stable_api import IQ_Option

# --- Configuración ---
IQ_EMAIL = "sebaselwspo@gmail.com"
IQ_PASSWORD = "Octubre2001"
TELEGRAM_BOT_TOKEN = "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM"
TELEGRAM_CHAT_ID = "7009100334"

app = Flask(__name__)
CORS(app)

# --- Funciones Telegram ---
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": msg}
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"Error Telegram: {e}")

# --- Bot principal ---
def run_bot(symbol, amount, martingalas):
    try:
        Iq = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
        Iq.connect()
        time.sleep(2)
        Iq.change_balance("PRACTICE")

        balance = Iq.get_balance()
        send_telegram(f"✅ Bot conectado a IQ Option
💼 Balance: ${balance:.2f}")

        for i in range(martingalas + 1):
            status, order_id = Iq.buy(amount, symbol, "call", 1)
            if status:
                send_telegram(f"📈 Operación {i+1}/{martingalas+1} en {symbol} enviada: ${amount:.2f}")
                break
            else:
                send_telegram(f"⚠️ Falló intento {i+1}, duplicando monto")
                amount *= 2

    except Exception as e:
        send_telegram(f"❌ Error en ejecución del bot: {e}")

# --- API HTTP ---
@app.route("/start_bot", methods=["POST"])
def start_bot():
    try:
        data = request.get_json()
        user_symbol = data.get("symbol", "").upper()
        amount = float(data.get("amount", 1))
        martingalas = int(data.get("martingalas", 2))

        # Detectar si es fin de semana
        weekend = datetime.today().weekday() in [5, 6]
        otc_pairs = {
            "EURUSD": "EURUSD-OTC",
            "GBPUSD": "GBPUSD-OTC",
            "USDJPY": "USDJPY-OTC",
            "AUDUSD": "AUDUSD-OTC",
        }

        if weekend and user_symbol in otc_pairs:
            final_symbol = otc_pairs[user_symbol]
            send_telegram(f"🌐 Fin de semana detectado. Cambiando {user_symbol} ➜ {final_symbol} (OTC)")
        else:
            final_symbol = user_symbol

        # Enviar confirmación
        send_telegram(f"🚀 Lanzando bot con parámetros:
🔹Activo: {final_symbol}
💰 Monto: ${amount}
🔁 Martingalas: {martingalas}")

        # Lanzar en hilo aparte
        threading.Thread(target=run_bot, args=(final_symbol, amount, martingalas), daemon=True).start()
        return jsonify({"message": "✅ Bot lanzado correctamente"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
