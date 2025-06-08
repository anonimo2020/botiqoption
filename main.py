# main.py - Backend con IQOptionAPI local
import os
import sys
import logging

# Configurar logging primero
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# IMPORTANTE: Agregar el directorio actual al path ANTES de importar
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logger.info(f"Python path: {sys.path[0]}")

# Verificar si existe la carpeta iqoptionapi
iqoption_path = os.path.join(os.path.dirname(__file__), 'iqoptionapi')
if os.path.exists(iqoption_path):
    logger.info(f"✅ Found iqoptionapi folder at: {iqoption_path}")
else:
    logger.error(f"❌ iqoptionapi folder not found at: {iqoption_path}")

# Intentar importar IQOptionAPI
IQ_AVAILABLE = False
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI imported successfully!")
except ImportError as e:
    logger.error(f"❌ Failed to import IQOptionAPI: {e}")
    # Crear una clase mock simple
    class IQ_Option:
        def __init__(self, email, password):
            raise NotImplementedError("IQOptionAPI no está disponible. Por favor, incluye la carpeta iqoptionapi en tu proyecto.")

# Imports de Flask y otras librerías
import datetime
import time
import requests
import numpy as np
from functools import wraps
from threading import Thread, Lock
import json

import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify, session, make_response
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session

# --- Configuración Flask ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/sessions'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True

Session(app)
CORS(app, supports_credentials=True, origins="*")

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://"
)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    cors_credentials=True
)

# Variables globales
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"Telegram error: {e}")

# --- Endpoints ---

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "iq_api_available": IQ_AVAILABLE,
        "active_sessions": len(user_sessions)
    }), 200

@app.route('/test', methods=['GET', 'POST'])
def test():
    """Endpoint de prueba para verificar funcionamiento"""
    return jsonify({
        "message": "Server is running",
        "method": request.method,
        "iq_option_available": IQ_AVAILABLE,
        "timestamp": datetime.datetime.now().isoformat()
    }), 200

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No data received"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
        
        logger.info(f"Login attempt for: {email}")
        
        if not IQ_AVAILABLE:
            # Modo demo sin IQOption real
            logger.warning("IQOptionAPI not available, using demo mode")
            
            # Simular login exitoso en demo
            session['user_email'] = email
            session['demo_mode'] = True
            
            user_data = {
                "name": email.split('@')[0].title(),
                "email": email,
                "balance": 10000.00,
                "account_type": "PRACTICE",
                "currency": "USD"
            }
            
            # Crear objeto mock para la sesión
            class MockIQ:
                def __init__(self):
                    self.balance = 10000.0
                    self.connected = True
                def get_balance(self):
                    return self.balance
                def get_balance_mode(self):
                    return "PRACTICE"
                def check_connect(self):
                    return True
                def close_websocket(self):
                    pass
                def change_balance(self, mode):
                    return True
                def get_candles(self, *args):
                    # Generar velas demo
                    return [{"close": 1.0850 + i*0.0001, "open": 1.0850, "min": 1.0840, "max": 1.0860} for i in range(100)]
                def buy(self, *args):
                    return True, f"demo_{int(time.time())}"
                def check_win_v3(self, *args):
                    return (True, np.random.choice([-1, 0.85]))
            
            with sessions_lock:
                user_sessions[email] = MockIQ()
            
            send_telegram_message(f"🎯 *LOGIN DEMO*\n👤 {email}\n💰 $10,000.00")
            
            return jsonify({
                "success": True,
                "user": user_data,
                "demo_mode": True,
                "message": "Conectado en modo DEMO (IQOption no disponible)"
            }), 200
        
        # Modo real con IQOption
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        iq = IQ_Option(email, password)
        
        # Intentar conectar
        connected = False
        for attempt in range(3):
            if iq.connect():
                connected = True
                break
            time.sleep(2)
        
        if not connected:
            return jsonify({"success": False, "message": "No se pudo conectar con IQ Option"}), 503
        
        if not iq.check_connect():
            return jsonify({"success": False, "message": "Credenciales incorrectas"}), 401
        
        # Login exitoso
        profile = iq.get_profile()
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        with sessions_lock:
            user_sessions[email] = iq
        
        session['user_email'] = email
        session['demo_mode'] = False
        
        send_telegram_message(f"""🎯 *LOGIN EXITOSO*
👤 Usuario: {profile.get('name', email)}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}""")
        
        return jsonify({
            "success": True,
            "user": {
                "name": profile.get('name', 'Usuario'),
                "email": email,
                "balance": balance,
                "account_type": account_type,
                "currency": profile.get('currency', 'USD')
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    try:
        if 'user_email' in session:
            email = session['user_email']
            
            with bots_lock:
                if email in active_bots:
                    active_bots[email] = False
            
            with sessions_lock:
                if email in user_sessions:
                    try:
                        user_sessions[email].close_websocket()
                    except:
                        pass
                    del user_sessions[email]
            
            session.clear()
            send_telegram_message(f"👋 *LOGOUT*\n📧 {email}")
        
        return jsonify({"success": True}), 200
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return jsonify({"success": False}), 500

@app.route('/api/balance', methods=['GET'])
def get_balance():
    try:
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado"}), 401
        
        email = session['user_email']
        
        with sessions_lock:
            if email not in user_sessions:
                return jsonify({"error": "Sesión expirada"}), 401
            
            iq = user_sessions[email]
            balance = iq.get_balance()
            account_type = iq.get_balance_mode()
        
        return jsonify({
            "balance": balance,
            "account_type": account_type
        }), 200
        
    except Exception as e:
        logger.error(f"Balance error: {str(e)}")
        return jsonify({"error": "Error obteniendo balance"}), 500

@app.route('/api/symbols', methods=['GET'])
def get_symbols():
    weekend = datetime.datetime.today().weekday() >= 5
    
    if weekend:
        symbols = [
            {"symbol": "EURUSD-OTC", "name": "EUR/USD OTC", "type": "otc"},
            {"symbol": "GBPUSD-OTC", "name": "GBP/USD OTC", "type": "otc"},
            {"symbol": "USDJPY-OTC", "name": "USD/JPY OTC", "type": "otc"},
            {"symbol": "AUDUSD-OTC", "name": "AUD/USD OTC", "type": "otc"}
        ]
    else:
        symbols = [
            {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
            {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
            {"symbol": "USDJPY", "name": "USD/JPY", "type": "forex"},
            {"symbol": "AUDUSD", "name": "AUD/USD", "type": "forex"}
        ]
    
    return jsonify({"symbols": symbols}), 200

@app.route('/api/start_bot', methods=['POST'])
def start_bot():
    try:
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado"}), 401
        
        email = session['user_email']
        
        with bots_lock:
            if active_bots.get(email, False):
                return jsonify({"error": "Ya hay un bot activo"}), 400
        
        data = request.get_json()
        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE')
        
        if amount <= 0:
            return jsonify({"error": "Monto debe ser mayor a 0"}), 400
        
        with sessions_lock:
            if email not in user_sessions:
                return jsonify({"error": "Sesión expirada"}), 401
            
            iq = user_sessions[email]
            iq.change_balance(account_type)
            balance = iq.get_balance()
            
            if amount > balance:
                return jsonify({"error": f"Fondos insuficientes. Balance: ${balance:.2f}"}), 400
        
        with bots_lock:
            active_bots[email] = True
        
        # Configuración del bot
        bot_config = {
            'symbol': symbol,
            'amount': amount,
            'martingalas': martingalas,
            'account_type': account_type
        }
        
        # Iniciar bot en thread
        thread = Thread(
            target=run_bot,
            args=(iq, bot_config, email, request.sid)
        )
        thread.daemon = True
        thread.start()
        
        mode = "DEMO" if session.get('demo_mode', False) else "REAL"
        send_telegram_message(f"""🚀 *BOT INICIADO ({mode})*
👤 {email}
📈 {symbol}
💰 ${amount:.2f}
🎯 Martingalas: {martingalas}
🏦 Cuenta: {account_type}""")
        
        return jsonify({"message": "Bot iniciado correctamente"}), 200
        
    except Exception as e:
        logger.error(f"Start bot error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    try:
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado"}), 401
        
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots and active_bots[email]:
                active_bots[email] = False
                send_telegram_message(f"🛑 *BOT DETENIDO*\n👤 {email}")
                return jsonify({"message": "Bot detenido"}), 200
            else:
                return jsonify({"error": "No hay bot activo"}), 400
                
    except Exception as e:
        logger.error(f"Stop bot error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# --- Bot Logic ---

def calculate_indicators(candles):
    """Calcula indicadores técnicos simples"""
    if len(candles) < 30:
        return None
    
    closes = np.array([float(c['close']) for c in candles])
    
    # RSI simple
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    avg_gain = np.mean(gains[-14:])
    avg_loss = np.mean(losses[-14:])
    
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs))
    
    # MACD simple
    ema12 = np.mean(closes[-12:])
    ema26 = np.mean(closes[-26:])
    macd = ema12 - ema26
    signal = np.mean(closes[-9:])
    
    # Stochastic
    highs = np.array([float(c.get('max', c['close'])) for c in candles])
    lows = np.array([float(c.get('min', c['close'])) for c in candles])
    
    lowest = np.min(lows[-14:])
    highest = np.max(highs[-14:])
    
    if highest != lowest:
        stoch_k = 100 * ((closes[-1] - lowest) / (highest - lowest))
    else:
        stoch_k = 50
    
    return {
        "rsi": round(rsi, 2),
        "macd": round(macd, 6),
        "signal": round(signal, 6),
        "stoch_k": round(stoch_k, 2),
        "price": round(closes[-1], 5)
    }

def get_signal(indicators):
    """Genera señal de trading"""
    if not indicators:
        return None, 0
    
    score = 0
    
    # RSI
    if indicators['rsi'] < 30:
        score += 2
    elif indicators['rsi'] > 70:
        score -= 2
    
    # MACD
    if indicators['macd'] > indicators['signal']:
        score += 1
    elif indicators['macd'] < indicators['signal']:
        score -= 1
    
    # Stochastic
    if indicators['stoch_k'] < 20:
        score += 1
    elif indicators['stoch_k'] > 80:
        score -= 1
    
    # Determinar señal
    if score >= 3:
        return 'call', abs(score) * 20
    elif score <= -3:
        return 'put', abs(score) * 20
    
    return None, 0

def run_bot(iq_api, config, email, sid):
    """Función principal del bot"""
    current_amount = config['amount']
    consecutive_losses = 0
    total_trades = 0
    total_profit = 0
    
    try:
        logger.info(f"Bot iniciado para {email}")
        
        while active_bots.get(email, False):
            try:
                # Verificar conexión
                if not iq_api.check_connect():
                    logger.warning(f"Reconectando para {email}...")
                    time.sleep(5)
                    continue
                
                # Obtener velas
                candles = iq_api.get_candles(config['symbol'], 60, 100, time.time())
                
                if not candles or len(candles) < 30:
                    time.sleep(30)
                    continue
                
                # Calcular indicadores
                indicators = calculate_indicators(candles)
                
                if not indicators:
                    time.sleep(30)
                    continue
                
                # Generar señal
                direction, confidence = get_signal(indicators)
                
                # Emitir análisis
                socketio.emit('analysis', {
                    'indicators': indicators,
                    'signal': direction,
                    'confidence': confidence
                }, room=sid)
                
                if direction and confidence >= 60:
                    # Verificar balance
                    balance = iq_api.get_balance()
                    if current_amount > balance:
                        socketio.emit('bot_error', {
                            'message': f'Fondos insuficientes. Balance: ${balance:.2f}'
                        }, room=sid)
                        break
                    
                    # Ejecutar operación
                    logger.info(f"Ejecutando {direction} por ${current_amount:.2f}")
                    status, order_id = iq_api.buy(current_amount, config['symbol'], direction, 1)
                    
                    if status:
                        total_trades += 1
                        
                        socketio.emit('trade_opened', {
                            'order_id': order_id,
                            'symbol': config['symbol'],
                            'direction': direction,
                            'amount': current_amount,
                            'confidence': confidence
                        }, room=sid)
                        
                        # Esperar resultado
                        time.sleep(65)
                        
                        # Verificar resultado
                        result = iq_api.check_win_v3(order_id)
                        
                        if isinstance(result, tuple):
                            profit = result[1]
                        else:
                            profit = float(result) if result else 0
                        
                        win = profit > 0
                        total_profit += profit
                        
                        socketio.emit('trade_closed', {
                            'order_id': order_id,
                            'result': 'WIN' if win else 'LOSS',
                            'profit': profit,
                            'total_trades': total_trades,
                            'total_profit': total_profit
                        }, room=sid)
                        
                        if win:
                            consecutive_losses = 0
                            current_amount = config['amount']
                            logger.info(f"✅ GANADA: +${profit:.2f}")
                        else:
                            consecutive_losses += 1
                            logger.info(f"❌ PERDIDA: -${abs(profit):.2f}")
                            
                            if consecutive_losses <= config['martingalas']:
                                current_amount *= 2
                                logger.info(f"Aplicando martingala {consecutive_losses}: ${current_amount:.2f}")
                            else:
                                logger.info("Martingalas agotadas. Deteniendo bot.")
                                break
                    
                    # Pausa entre operaciones
                    time.sleep(90)
                else:
                    # Sin señal clara
                    time.sleep(60)
                    
            except Exception as e:
                logger.error(f"Error en ciclo bot: {e}")
                time.sleep(30)
                
    except Exception as e:
        logger.error(f"Error fatal en bot: {e}")
    finally:
        active_bots[email] = False
        socketio.emit('bot_stopped', {
            'reason': 'finished',
            'total_trades': total_trades,
            'total_profit': total_profit
        }, room=sid)
        logger.info(f"Bot detenido para {email}. Total trades: {total_trades}, Profit: ${total_profit:.2f}")

# --- WebSocket Events ---

@socketio.on('connect')
def handle_connect():
    join_room(request.sid)
    emit('connected', {'sid': request.sid})
    logger.info(f"Cliente conectado: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    leave_room(request.sid)
    logger.info(f"Cliente desconectado: {request.sid}")

@socketio.on('ping')
def handle_ping():
    emit('pong')

# --- Main ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting server on port {port}")
    logger.info(f"📊 IQ Option API available: {IQ_AVAILABLE}")
    
    # Si IQOption no está disponible, mostrar instrucciones
    if not IQ_AVAILABLE:
        logger.warning("=" * 60)
        logger.warning("IQOptionAPI NO ESTÁ DISPONIBLE")
        logger.warning("El servidor funcionará en modo DEMO")
        logger.warning("Para habilitar el modo real:")
        logger.warning("1. Incluye la carpeta 'iqoptionapi' en tu proyecto")
        logger.warning("2. O instala: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
        logger.warning("=" * 60)
    
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
