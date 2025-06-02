
from flask import Flask, request, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS
import logging
import datetime
import time
import numpy as np
import requests
import os
import threading
from iqoptionapi.stable_api import IQ_Option

# Inicializar la aplicación Flask y SocketIO
app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración de Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def is_weekend():
    today = datetime.datetime.now().weekday()
    return today == 5 or today == 6

@app.route('/symbols', methods=['GET'])
def get_symbols():
    if is_weekend():
        symbols = ["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC"]
    else:
        symbols = ["EURUSD", "GBPUSD", "USDJPY"]
    return jsonify({"symbols": symbols})

def run_bot(symbol, initial_amount, martingalas):
    email = os.getenv("IQ_EMAIL")
    password = os.getenv("IQ_PASSWORD")
    iq = IQ_Option(email, password)
    iq.connect()

    if not iq.check_connect():
        send_telegram_message("❌ No se pudo conectar a IQ Option.")
        return

    current_amount = initial_amount
    total_invested = 0
    loss_limit = initial_amount * 0.5

    while True:
        candles = iq.get_candles(symbol, 60, 100, time.time())
        close_prices = [candle['close'] for candle in candles]

        rsi = calculate_rsi(close_prices, 14)
        macd, signal_line = calculate_macd(close_prices, 12, 26, 9)
        stochastic_k, stochastic_d = calculate_stochastic(close_prices, 14, 3)

        direction = None
        if rsi < 30 and macd > signal_line and stochastic_k < 20 and stochastic_d < 20:
            direction = 'call'
        elif rsi > 70 and macd < signal_line and stochastic_k > 80 and stochastic_d > 80:
            direction = 'put'

        if direction:
            result = execute_trade(iq, symbol, current_amount, direction)
            logger.info(f"Operación: {direction} en {symbol} con monto {current_amount}. Resultado: {result['result']}")

            total_invested += current_amount
            send_telegram_message(f"Capital actual: ${current_amount:.2f}")

            if result['result'] == 'LOSS':
                current_amount *= 2
                if martingalas > 0:
                    martingalas -= 1
                else:
                    break
            else:
                break

            if current_amount < loss_limit:
                send_telegram_message("🚫 El bot se detuvo por pérdida del 50%.")
                break

        time.sleep(60)

@app.route('/start_bot', methods=['POST'])
def start_bot():
    data = request.json
    symbol = data.get('symbol')
    initial_amount = data.get('amount', 1)
    martingalas = data.get('martingalas', 0)

    if not symbol:
        return jsonify({"error": "Símbolo no válido"}), 400

    threading.Thread(target=run_bot, args=(symbol, initial_amount, martingalas)).start()
    return jsonify({"message": "Bot iniciado correctamente."}), 200

def calculate_rsi(prices, period):
    deltas = np.diff(prices)
    gain = np.where(deltas > 0, deltas, 0)
    loss = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(prices, short_period, long_period, signal_period):
    short_ema = np.mean(prices[-short_period:])
    long_ema = np.mean(prices[-long_period:])
    macd = short_ema - long_ema
    signal_line = np.mean(prices[-signal_period:])
    return macd, signal_line

def calculate_stochastic(prices, k_period, d_period):
    lowest_low = np.min(prices[-k_period:])
    highest_high = np.max(prices[-k_period:])
    k = 100 * (prices[-1] - lowest_low) / (highest_high - lowest_low) if highest_high != lowest_low else 0
    d = np.mean([k] * d_period)
    return k, d

def execute_trade(iq, symbol, amount, direction):
    if direction == 'call':
        result = iq.buy(symbol, amount, 'call', 1)
    else:
        result = iq.buy(symbol, amount, 'put', 1)
    time.sleep(60)
    profit = iq.check_win(result['id'])
    return {
        "symbol": symbol,
        "amount": amount,
        "result": 'WIN' if profit > 0 else 'LOSS',
        "profit": profit
    }

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
