from flask import Flask, request, jsonify
from flask_socketio import SocketIO
from flask_cors import CORS
import logging
import datetime
import time
import numpy as np
import requests
import os
from iqoptionapi.stable_api import IQ_Option


# Inicializar la aplicación Flask y SocketIO
app = Flask(__name__)
CORS(app)  # Permitir CORS para todas las rutas
socketio = SocketIO(app, cors_allowed_origins="*")

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Conexión a IQ Option usando variables de entorno
email = os.getenv("IQ_EMAIL")
password = os.getenv("IQ_PASSWORD")
iq = IQ_Option(email, password)
iq.connect()
if not iq.check_connect():
    return jsonify({"error": "No se pudo conectar a IQ Option"}), 500


# Configuración de Telegram usando variables de entorno
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message):
    """Envía un mensaje a Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def is_weekend():
    """Verifica si es fin de semana."""
    today = datetime.datetime.now().weekday()
    return today == 5 or today == 6  # 5 = Sábado, 6 = Domingo

@app.route('/symbols', methods=['GET'])
def get_symbols():
    """Devuelve los símbolos de trading según el día de la semana."""
    if is_weekend():
        symbols = ["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC"]  # Ejemplo de símbolos OTC
    else:
        symbols = ["EURUSD", "GBPUSD", "USDJPY"]  # Ejemplo de símbolos normales
    return jsonify({"symbols": symbols})

@app.route('/start_bot', methods=['POST'])
def start_bot():
    """Inicia el bot de trading."""
    data = request.json
    symbol = data.get('symbol')
    initial_amount = data.get('amount', 1)
    martingalas = data.get('martingalas', 0)

    if not symbol:
        return jsonify({"error": "Símbolo no válido"}), 400

    current_amount = initial_amount
    total_invested = 0
    loss_limit = initial_amount * 0.5  # 50% de la inversión inicial

    # Lógica de trading automatizado
    while True:
        # Obtener datos de precios
        # Obtener 100 velas de 1 minuto
        candles = iq.get_candles(symbol, 60, 100, time.time())
        close_prices = [candle['close'] for candle in candles]

        # Calcular indicadores
        rsi = calculate_rsi(close_prices, 14)
        macd, signal_line = calculate_macd(close_prices, 12, 26, 9)
        stochastic_k, stochastic_d = calculate_stochastic(close_prices, 14, 3)

        # Determinar la dirección de la operación
        direction = None
        if rsi < 30 and macd > signal_line and stochastic_k < 20 and stochastic_d < 20:
            direction = 'call'  # Señal de compra
        elif rsi > 70 and macd < signal_line and stochastic_k > 80 and stochastic_d > 80:
            direction = 'put'  # Señal de venta

        if direction:
            # Ejecutar la operación
            result = execute_trade(symbol, current_amount, direction)
            logger.info(f"Operación: {direction} en {symbol} con monto {current_amount}. Resultado: {result['result']}")

            # Actualizar el total invertido
            total_invested += current_amount

            # Enviar capital actual a Telegram
            send_telegram_message(f"Capital actual: ${current_amount:.2f}")

            # Manejo de martingalas
            if result['result'] == 'LOSS':
                current_amount *= 2  # Duplicar el monto para la martingala
                if martingalas > 0:
                    martingalas -= 1
                else:
                    break  # Salir si se alcanzó el límite de martingalas
            else:
                break  # Salir si se ganó

            # Verificar si se ha perdido el 50% de la inversión inicial
            if current_amount < loss_limit:
                send_telegram_message("El bot ha detenido las operaciones debido a una pérdida del 50% de la inversión inicial.")
                break  # Detener el bot

        time.sleep(60)  # Esperar un minuto antes de la siguiente operación

    return jsonify({"message": "Operaciones completadas."}), 200

def calculate_rsi(prices, period):
    """Calcula el RSI."""
    deltas = np.diff(prices)
    gain = np.where(deltas > 0, deltas, 0)
    loss = np.where(deltas < 0, -deltas, 0)

    avg_gain = np.mean(gain[-period:])
    avg_loss = np.mean(loss[-period:])

    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(prices, short_period, long_period, signal_period):
    """Calcula el MACD."""
    short_ema = np.mean(prices[-short_period:])
    long_ema = np.mean(prices[-long_period:])
    macd = short_ema - long_ema

    # Calcular la línea de señal
    signal_line = np.mean(prices[-signal_period:])  # Esto es una simplificación
    return macd, signal_line

def calculate_stochastic(prices, k_period, d_period):
    """Calcula el Stochastic Oscillator."""
    lowest_low = np.min(prices[-k_period:])
    highest_high = np.max(prices[-k_period:])
    k = 100 * (prices[-1] - lowest_low) / (highest_high - lowest_low) if highest_high != lowest_low else 0

    # Calcular D como un promedio simple de K
    d = np.mean([k] * d_period)  # Esto es una simplificación
    return k, d

def execute_trade(symbol, amount, direction):
    """Ejecuta una operación de trading."""
    if direction == 'call':
        result = iq.buy(symbol, amount, 'call', 1)  # 1 = tiempo de expiración en minutos
    else:
        result = iq.buy(symbol, amount, 'put', 1)

    # Esperar el resultado de la operación
    time.sleep(60)  # Esperar 1 minuto para el resultado
    profit = iq.check_win(result['id'])  # Verificar el resultado de la operación
    return {
        "symbol": symbol,
        "amount": amount,
        "result": 'WIN' if profit > 0 else 'LOSS',
        "profit": profit
    }

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
