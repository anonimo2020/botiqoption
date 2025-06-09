# ------------------------------
# main.py - Bot de Opciones Binarias a 5 Minutos
# ------------------------------
import os
import sys
import logging
import datetime
import time
import requests
import numpy as np
from functools import wraps
from threading import Thread, Lock, Event
import json
from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Insertar path local de IQOptionAPI
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iqoptionapi.stable_api import IQ_Option

# ------------------------------
# Configuración de Logger
# ------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ------------------------------
# Flask App & Config
# ------------------------------
app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)
CORS(app)
# Inicializar Limiter sin pasar app como positional para evitar conflicto
limiter = Limiter(key_func=get_remote_address)
limiter.init_app(app)

# ------------------------------
# Global State
# ------------------------------
user_sessions = {}       # email -> IQ_Option
sessions_lock = Lock()
active_bots = {}         # email -> Thread
bots_lock = Lock()

# ------------------------------
# Estrategias 5min categorizadas por riesgo
# ------------------------------
STRATEGY_RISK = {
    'low': {
        'name': 'Trend Following',
        'description': 'EMA crossover + MACD',
        'threshold': 0.8
    },
    'medium': {
        'name': 'Bollinger Reversal',
        'description': 'Bollinger Bands + RSI',
        'threshold': 0.6
    },
    'high': {
        'name': 'Stochastic Scalping',
        'description': 'Stochastic O/S',
        'threshold': 0.5
    }
}

# ------------------------------
# Utilitarios
# ------------------------------
def get_indicators(iq, symbol):
    data = iq.get_candles(symbol, 300, 100, time.time())
    closes = np.array([candle['close'] for candle in data])
    return {
        'closes': closes,
        'ema_fast': np.mean(closes[-5:]),
        'ema_slow': np.mean(closes[-20:]),
        'macd': closes[-1] - np.mean(closes[-26:]),
        'rsi': 50,
        'bb_upper': np.max(closes[-20:]),
        'bb_lower': np.min(closes[-20:]),
        'stoch': 20,
    }


def get_signal_by_risk(indicators, risk_level):
    strat = STRATEGY_RISK[risk_level]
    # Trend Following (low)
    if risk_level == 'low':
        if indicators['ema_fast'] > indicators['ema_slow'] and indicators['macd'] > 0:
            return 'call', 0.9
        else:
            return 'put', 0.9
    # Bollinger Reversal (medium)
    if risk_level == 'medium':
        if indicators['closes'][-1] > indicators['bb_upper'] and indicators['rsi'] > 70:
            return 'put', 0.7
        elif indicators['closes'][-1] < indicators['bb_lower'] and indicators['rsi'] < 30:
            return 'call', 0.7
        else:
            return None, 0
    # Stochastic Scalping (high)
    if risk_level == 'high':
        if indicators['stoch'] < 20:
            return 'call', 0.5
        elif indicators['stoch'] > 80:
            return 'put', 0.5
        else:
            return None, 0

# ------------------------------
# Endpoints
# ------------------------------
@app.route('/api/login', methods=['POST'])
@limiter.limit('10 per minute')
def api_login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email y password requeridos'}), 400

    with sessions_lock:
        if email in user_sessions:
            try:
                user_sessions[email].close_websocket()
            except:
                pass
            del user_sessions[email]

        iq = IQ_Option(email, password)
        check, reason = iq.connect()
        if not check:
            code = reason.get('code') if isinstance(reason, dict) else None
            if code == 'invalid_credentials':
                return jsonify({'success': False, 'message': 'Correo o contraseña incorrecta'}), 401
            return jsonify({'success': False, 'message': 'Error de conexión'}), 503
        user_sessions[email] = iq
    return jsonify({'success': True}), 200

@app.route('/api/symbols', methods=['GET'])
def api_symbols():
    with sessions_lock:
        if not user_sessions:
            return jsonify([]), 200
        iq = next(iter(user_sessions.values()))
        all_syms = iq.get_all_init_data()[0]['binary']
        return jsonify(all_syms), 200

@app.route('/api/start_bot', methods=['POST'])
def api_start_bot():
    data = request.get_json()
    email = data.get('email')
    symbol = data.get('symbol')
    amount = data.get('amount')
    risk = data.get('risk_level')
    if risk not in STRATEGY_RISK:
        return jsonify({'success': False, 'message': 'Riesgo inválido'}), 400

    with sessions_lock:
        iq = user_sessions.get(email)
    if not iq:
        return jsonify({'success': False, 'message': 'No logueado'}), 401

    def trading_loop():
        while True:
            try:
                inds = get_indicators(iq, symbol)
                signal, conf = get_signal_by_risk(inds, risk)
                if signal:
                    iq.buy(amount, symbol, signal, 5)
                    logger.info(f"Trade: {signal} {symbol} 🕔5m conf={conf}")
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error en bot: {e}")
                break

    with bots_lock:
        if email in active_bots:
            return jsonify({'success': False, 'message': 'Bot ya activo'}), 409
        th = Thread(target=trading_loop, daemon=True)
        active_bots[email] = th
        th.start()

    return jsonify({'success': True}), 200

@app.route('/api/stop_bot', methods=['POST'])
def api_stop_bot():
    data = request.get_json()
    email = data.get('email')
    with bots_lock:
        th = active_bots.pop(email, None)
    if not th:
        return jsonify({'success': False, 'message': 'Bot no estaba activo'}), 404
    return jsonify({'success': True}), 200

@app.route('/api/balance', methods=['GET'])
def api_balance():
    email = request.args.get('email')
    with sessions_lock:
        iq = user_sessions.get(email)
    if not iq:
        return jsonify({'success': False, 'message': 'No logueado'}), 401
    bal = iq.get_balance()
    return jsonify({'success': True, 'balance': bal}), 200

@app.route('/health', methods=['GET'])
def health_check():
    try:
        health_data = {
            'status': 'healthy',
            'timestamp': datetime.datetime.now().isoformat()
        }
        return jsonify(health_data), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
