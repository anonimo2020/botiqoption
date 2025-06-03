from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO
from flask_cors import CORS
import logging, datetime, time, threading, os, requests, numpy as np
from iqoptionapi.stable_api import IQ_Option
from flask_session import Session

import eventlet
eventlet.monkey_patch()

app = Flask(__name__)
app.secret_key = 'super_secret_key'

# Configuración de sesión segura y compatible con Flask >=2.3
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_FILE_DIR'] = '/tmp/session_data'
app.config['SESSION_COOKIE_NAME'] = 'session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
Session(app)

CORS(app, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions = {}

TELEGRAM_TOKEN = "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM"
TELEGRAM_CHAT_ID = "7009100334"

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload)
        logger.info(f"Telegram response: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Error enviando mensaje a Telegram: {e}")

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')

    iq = IQ_Option(email, password)
    iq.connect()
    if iq.check_connect():
        user_sessions[email] = iq
        session['user_email'] = email

        profile = iq.get_profile_ansyc()
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        send_telegram_message(f"""✅ Inicio de sesión:
👤 Usuario: {profile.get('name', 'Desconocido')}
📧 Email: {email}
💰 Balance: ${balance:.2f} ({account_type})""")

        return jsonify({"success": True, "message": "Conectado a IQ Option"}), 200
    else:
        return jsonify({"success": False, "message": "Credenciales incorrectas"}), 401

@app.route('/symbols', methods=['GET'])
def get_symbols():
    return jsonify({"symbols": ["EURUSD", "GBPUSD", "USDJPY", "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC"]})

def calculate_indicators(candles):
    try:
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])

        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        rsi = 100 - (100 / (1 + rs))
        macd = np.mean(closes[-12:]) - np.mean(closes[-26:])
        signal = np.mean(closes[-9:])
        stoch_k = 100 * ((closes[-1] - np.min(lows[-14:])) / (np.max(highs[-14:]) - np.min(lows[-14:]))) if np.max(highs[-14:]) != np.min(lows[-14:]) else 0
        stoch_d = np.mean([stoch_k]*3)

        return {"rsi": rsi, "macd": macd, "signal": signal, "stoch_k": stoch_k, "stoch_d": stoch_d, "price": closes[-1]}
    except Exception as e:
        logger.error(f"Error calculando indicadores: {e}")
        return None

def get_signal(ind):
    if not ind: return None
    if ind['rsi'] < 35 or (ind['macd'] > ind['signal'] and ind['stoch_k'] < 25): return 'call'
    if ind['rsi'] > 65 or (ind['macd'] < ind['signal'] and ind['stoch_k'] > 75): return 'put'
    return None

@app.route('/start_bot', methods=['POST'])
def start_bot():
    if 'user_email' not in session:
        return jsonify({"error": "Usuario no autenticado"}), 403

    email = session['user_email']
    iq = user_sessions.get(email)

    if not iq or not iq.check_connect():
        return jsonify({"error": "Sesión expirada o inválida"}), 403

    data = request.json
    symbol = data.get('symbol')
    amount = float(data.get('amount', 1))
    martingalas = int(data.get('martingalas', 0))
    account_type = data.get('account_type', 'PRACTICE')

    if amount <= 0:
        return jsonify({"error": "El monto debe ser mayor que 0"}), 400

    balance = iq.get_balance()
    if amount > balance:
        return jsonify({"error": f"Fondos insuficientes. Balance: ${balance:.2f}"}), 400

    iq.change_balance(account_type.upper())
    socketio.start_background_task(run_bot, iq, symbol, amount, martingalas, email)

    return jsonify({"message": "Bot iniciado correctamente."}), 200

def run_bot(iq, symbol, initial_amount, martingalas, email):
    try:
        current_amount = initial_amount
        loss_limit = initial_amount * 0.5

        candles = iq.get_candles(symbol, 60, 100, time.time())
        ind = calculate_indicators(candles)
        direction = get_signal(ind)

        if ind:
            send_telegram_message(f"🔎 RSI: {ind['rsi']:.2f} | MACD: {ind['macd']:.2f} | STOCH_K: {ind['stoch_k']:.2f}")
        else:
            send_telegram_message("⚠️ No se pudieron calcular los indicadores.")

        if direction:
            balance = iq.get_balance()
            if current_amount > balance:
                send_telegram_message(f"🚫 Fondos insuficientes para operar ${current_amount:.2f}. Balance actual: ${balance:.2f}. Bot detenido.")
                return

            result = execute_trade(iq, symbol, current_amount, direction)
            send_telegram_message(f"📊 Operación: {direction.upper()} en {symbol} → *{result['result']}* | Monto: ${current_amount:.2f} | Ganancia: ${result['profit']:.2f}")

            if result['result'] == 'LOSS':
                current_amount *= 2
                martingalas -= 1
                if martingalas < 0:
                    send_telegram_message("🔴 Martingalas agotadas. Bot detenido.")
                    return
            else:
                return

            if current_amount < loss_limit:
                send_telegram_message("🚫 Pérdida del 50%. Bot detenido.")
                return
        else:
            send_telegram_message("⏳ Sin señal. Finalizando ejecución de prueba.")

    except Exception as e:
        logger.error(f"Error en run_bot: {e}")
        send_telegram_message(f"❌ Error en run_bot: {e}")

def execute_trade(iq, symbol, amount, direction):
    try:
        status, id = iq.buy(amount, symbol, direction, 1)
        if not status:
            send_telegram_message("❌ Error al enviar la operación a IQ Option.")
            return {"result": "ERROR", "profit": 0}

        time.sleep(60)
        profit = iq.check_win(id)
        return {"symbol": symbol, "amount": amount, "result": 'WIN' if profit > 0 else 'LOSS', "profit": profit}
    except Exception as e:
        logger.error(f"Error en execute_trade: {e}")
        send_telegram_message(f"❌ Error en execute_trade: {e}")
        return {"result": "ERROR", "profit": 0}

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
