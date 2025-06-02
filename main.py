from flask import Flask, request, jsonify
from flask_socketio import SocketIO
import logging
import datetime
import requests

# Inicializar la aplicación Flask y SocketIO
app = Flask(__name__)
socketio = SocketIO(app)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Variables de entorno para las credenciales de Telegram
TELEGRAM_BOT_TOKEN = "tu_token_de_telegram"
TELEGRAM_CHAT_ID = "tu_chat_id"

def send_telegram_message(message):
    """Envía un mensaje a Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message
    }
    requests.post(url, json=payload)

def is_weekend():
    """Verifica si es fin de semana."""
    today = datetime.datetime.now().weekday()
    return today == 5 or today == 6  # 5 = Sábado, 6 = Domingo

@app.route('/')
def index():
    return "API en funcionamiento"

@app.route('/symbols', methods=['GET'])
def get_symbols():
    # Implementa la lógica para obtener símbolos
    if is_weekend():
        symbols = ["OTC_EURUSD", "OTC_GBPUSD", "OTC_USDJPY"]  # Ejemplo de símbolos OTC
    else:
        symbols = ["EURUSD", "GBPUSD", "USDJPY"]  # Ejemplo de símbolos normales
    return jsonify({"symbols": symbols})

@socketio.on('connect')
def handle_connect():
    logger.info("Cliente conectado")
    send_telegram_message("Bot conectado a la cuenta.")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info("Cliente desconectado")

@socketio.on('start_trade')
def start_trade(symbol, amount, direction):
    """Inicia una operación."""
    logger.info(f"Iniciando operación: {symbol}, {amount}, {direction}")
    # Aquí implementa la lógica para abrir una operación
    # Simulación de operación
    socketio.emit('trade_opened', {'symbol': symbol, 'amount': amount, 'direction': direction})
    send_telegram_message(f"Operación abierta: {symbol}, {amount}, {direction}")

@socketio.on('close_trade')
def close_trade(symbol, amount, direction):
    """Cierra una operación."""
    logger.info(f"Cerrando operación: {symbol}, {amount}, {direction}")
    # Aquí implementa la lógica para cerrar una operación
    socketio.emit('trade_closed', {'symbol': symbol, 'amount': amount, 'direction': direction})
    send_telegram_message(f"Operación cerrada: {symbol}, {amount}, {direction}")

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)

