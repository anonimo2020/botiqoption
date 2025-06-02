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
import talib

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
    try:
        requests.post(url, json=payload)
    except Exception as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")

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

def calculate_indicators(candles):
    try:
        closes = np.array([float(candle['close']) for candle in candles])
        highs = np.array([float(candle['max']) for candle in candles])
        lows = np.array([float(candle['min']) for candle in candles])

        rsi = talib.RSI(closes, timeperiod=14)[-1]
        macd, macdsignal, _ = talib.MACD(closes, fastperiod=12, slowperiod=26, signalperiod=9)
        stoch_k, stoch_d = talib.STOCH(highs, lows, closes, fastk_period=14, slowk_period=3, slowd_period=3)

        return {
            'rsi': rsi,
            'macd': macd[-1],
            'signal': macdsignal[-1],
            'stoch_k': stoch_k[-1],
            'stoch_d': stoch_d[-1],
            'price': closes[-1] if len(closes) > 0 else 0
        }
    except Exception as e:
        logger.error(f"Error calculando indicadores: {e}")
        return None

def get_signal(ind):
    if not ind:
        return None

    if ind['rsi'] < 30 and ind['macd'] > ind['signal'] and ind['stoch_k'] < 20 and ind['stoch_d'] < 20:
        return 'call'
    elif ind['rsi'] > 70 and ind['macd'] < ind['signal'] and ind['stoch_k'] > 80 and ind['stoch_d'] > 80:
        return 'put'
    return None

def run_bot(symbol, initial_amount, martingalas):
    email = os.getenv("IQ_EMAIL")
    password = os.getenv("IQ_PASSWORD")
    iq = IQ_Option(email, password)
    iq.connect()

    if not iq.check_connect():
        send_telegram_message("❌ No se pudo conectar a IQ Option.")
        return

    send_telegram_message(f"🤖 Bot iniciado para *{symbol}* con ${initial_amount}, martingalas: {martingalas}")

    current_amount = initial_amount
    loss_limit = initial_amount * 0.5

    while True:
        candles = iq.get_candles(symbol, 60, 100, time.time())
        ind = calculate_indicators(candles)
        direction = get_signal(ind)

        send_telegram_message(f"🔎 RSI: {ind['rsi']:.2f} | MACD: {ind['macd']:.2f} | SIGNAL: {ind['signal']:.2f} | STOCH_K: {ind['stoch_k']:.2f} | STOCH_D: {ind['stoch_d']:.2f}")

        if direction:
            result = execute_trade(iq, symbol, current_amount, direction)
            msg = f"📊 Operación: *{direction.upper()}* en *{symbol}* con ${current_amount} → *{result['result']}*\nGanancia: ${result['profit']:.2f}"
            send_telegram_message(msg)

            logger.info(msg)
            if result['result'] == 'LOSS':
                current_amount *= 2
                martingalas -= 1
                if martingalas < 0:
                    send_telegram_message("🔴 Máxima cantidad de martingalas alcanzada. Bot detenido.")
                    break
            else:
                send_telegram_message("✅ Operación ganada. Finalizando ciclo.")
                break

            if current_amount < loss_limit:
                send_telegram_message("🚫 El bot se detuvo por pérdida del 50%.")
                break
        else:
            logger.info("Ninguna señal encontrada. Esperando...")
            send_telegram_message("⏳ Ninguna señal encontrada. Esperando 60s...")

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

def execute_trade(iq, symbol, amount, direction):
    if direction == 'call':
        status, id = iq.buy(amount, symbol, 'call', 1)
    else:
        status, id = iq.buy(amount, symbol, 'put', 1)

    if not status:
        send_telegram_message("❌ Error al enviar operación")
        return {"result": "ERROR", "profit": 0}

    send_telegram_message(f"📥 Enviando operación {direction.upper()} con ${amount} en {symbol}...")

    time.sleep(60)
    profit = iq.check_win(id)
    return {
        "symbol": symbol,
        "amount": amount,
        "result": 'WIN' if profit > 0 else 'LOSS',
        "profit": profit
    }

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
