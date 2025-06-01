from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import time
import numpy as np
import logging
from iqoptionapi.stable_api import IQ_Option

IQ_EMAIL = "sebaselwspo@gmail.com"
IQ_PASSWORD = "Octubre2001"

app = Flask(__name__)
CORS(app)  # Habilita solicitudes desde cualquier origen

def rsi(closes, period=14):
    deltas = np.diff(closes)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(closes)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(closes)):
        delta = deltas[i - 1]
        upval = max(delta, 0)
        downval = -min(delta, 0)
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)
    return rsi

def bot_logic():
    logging.basicConfig(level=logging.INFO)
    Iq = IQ_Option(IQ_EMAIL, IQ_PASSWORD)
    check, reason = Iq.connect()
    if not check:
        print(f"Error de conexión: {reason}")
        return

    Iq.change_balance("PRACTICE")
    candles = Iq.get_candles("EURUSD", 60, 100, time.time())
    closes = np.array([c['close'] for c in candles], dtype=np.float32)
    calculated_rsi = rsi(closes)[-1]
    print(f"RSI actual: {calculated_rsi:.2f}")

    Iq.buy(1, "EURUSD", "call", 1)
    print("Operación enviada.")

@app.route('/start_bot', methods=['POST'])
def start_bot():
    try:
        threading.Thread(target=bot_logic, daemon=True).start()
        return jsonify({"message": "🤖 Bot con CORS iniciado correctamente"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
