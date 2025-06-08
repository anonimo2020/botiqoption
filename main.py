# main.py - Backend con IQ Option API Real
import os
import logging
import datetime
import time
import requests
import numpy as np
from functools import wraps
from threading import Thread, Lock
import eventlet
eventlet.monkey_patch()

from flask import Flask, request, jsonify, session, make_response
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
import json

# Manejo de importación de IQ Option
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
except ImportError:
    logging.warning("IQOptionAPI no disponible, algunas funciones estarán limitadas")
    IQ_AVAILABLE = False
    # Clase mock básica para evitar errores
    class IQ_Option:
        def __init__(self, email, password):
            self.email = email
            self.password = password
            raise Exception("IQOptionAPI no está instalada. Por favor instala: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")

# --- Configuración de la aplicación Flask ---
app = Flask(__name__)

# Configuración de seguridad
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-key-change-in-production')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_COOKIE_NAME'] = 'trading_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600

# Inicializar extensiones
Session(app)

# CORS más permisivo
CORS(app, supports_credentials=True, origins="*")

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# SocketIO
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    logger=True,
    engineio_logger=True,
    cors_credentials=True
)

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Variables Globales ---
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# --- Telegram Config ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# --- Funciones de Utilidad ---

def send_telegram_message(message):
    """Envía mensaje a Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error Telegram: {e}")

def calculate_indicators_simple(candles):
    """Calcula indicadores sin talib"""
    try:
        if len(candles) < 30:
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        
        # RSI simple
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-14:]) if len(gains) >= 14 else 0
        avg_loss = np.mean(losses[-14:]) if len(losses) >= 14 else 0
        
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        # MACD simple
        ema12 = closes[-12:].mean()
        ema26 = closes[-26:].mean()
        macd = ema12 - ema26
        signal = closes[-9:].mean()
        
        # Stochastic simple
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        
        lowest = np.min(lows[-14:])
        highest = np.max(highs[-14:])
        
        if highest != lowest:
            stoch_k = 100 * ((closes[-1] - lowest) / (highest - lowest))
        else:
            stoch_k = 50
        
        return {
            "rsi": round(rsi, 2),
            "macd": round(macd, 4),
            "signal": round(signal, 4),
            "stoch_k": round(stoch_k, 2),
            "price": round(closes[-1], 5)
        }
        
    except Exception as e:
        logger.error(f"Error en indicadores: {e}")
        return None

def get_signal(indicators):
    """Genera señal de trading"""
    if not indicators:
        return None, 0
    
    score = 0
    
    # Condiciones de compra
    if indicators['rsi'] < 30:
        score += 2
    if indicators['macd'] > indicators['signal']:
        score += 2
    if indicators['stoch_k'] < 20:
        score += 1
    
    # Condiciones de venta
    if indicators['rsi'] > 70:
        score -= 2
    if indicators['macd'] < indicators['signal']:
        score -= 2
    if indicators['stoch_k'] > 80:
        score -= 1
    
    confidence = abs(score) * 20  # Confianza basada en score
    
    if score >= 3:
        return 'call', confidence
    elif score <= -3:
        return 'put', confidence
    
    return None, 0

# --- Endpoints ---

@app.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "iq_api_available": IQ_AVAILABLE,
        "active_sessions": len(user_sessions)
    }), 200

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    """Login endpoint"""
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
            return jsonify({
                "success": False, 
                "message": "IQ Option API no está disponible en el servidor. Contacta al administrador."
            }), 503
        
        # Cerrar sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        # Conectar a IQ Option
        iq = IQ_Option(email, password)
        
        # Intentar conexión con reintentos
        connected = False
        for i in range(3):
            if iq.connect():
                connected = True
                break
            time.sleep(2)
        
        if not connected:
            return jsonify({"success": False, "message": "No se pudo conectar con IQ Option"}), 503
        
        if not iq.check_connect():
            return jsonify({"success": False, "message": "Credenciales incorrectas"}), 401
        
        # Obtener información
        profile = iq.get_profile()
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        # Guardar sesión
        with sessions_lock:
            user_sessions[email] = iq
        
        session['user_email'] = email
        session.permanent = True
        
        # Notificar
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
    """Logout endpoint"""
    try:
        if 'user_email' in session:
            email = session['user_email']
            
            # Detener bot
            with bots_lock:
                if email in active_bots:
                    active_bots[email] = False
            
            # Cerrar conexión
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
    """Get balance"""
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
    """Get trading symbols"""
    try:
        # Determinar si es fin de semana
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
        
    except Exception as e:
        logger.error(f"Symbols error: {str(e)}")
        return jsonify({"error": "Error obteniendo símbolos"}), 500

@app.route('/api/start_bot', methods=['POST'])
def start_bot():
    """Start bot"""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado"}), 401
        
        email = session['user_email']
        
        # Verificar bot activo
        with bots_lock:
            if active_bots.get(email, False):
                return jsonify({"error": "Ya hay un bot activo"}), 400
        
        data = request.get_json()
        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE')
        
        # Validaciones
        if amount <= 0:
            return jsonify({"error": "Monto inválido"}), 400
        
        with sessions_lock:
            if email not in user_sessions:
                return jsonify({"error": "Sesión expirada"}), 401
            
            iq = user_sessions[email]
            
            # Cambiar tipo de cuenta
            iq.change_balance(account_type)
            
            # Verificar balance
            balance = iq.get_balance()
            if amount > balance:
                return jsonify({"error": f"Fondos insuficientes. Balance: ${balance:.2f}"}), 400
        
        # Marcar bot activo
        with bots_lock:
            active_bots[email] = True
        
        # Iniciar bot
        thread = Thread(
            target=run_bot,
            args=(iq, symbol, amount, martingalas, email, request.sid)
        )
        thread.daemon = True
        thread.start()
        
        send_telegram_message(f"""🚀 *BOT INICIADO*
👤 {email}
📈 {symbol}
💰 ${amount:.2f}
🎯 Martingalas: {martingalas}""")
        
        return jsonify({"message": "Bot iniciado"}), 200
        
    except Exception as e:
        logger.error(f"Start bot error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    """Stop bot"""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado"}), 401
        
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                active_bots[email] = False
                send_telegram_message(f"🛑 *BOT DETENIDO*\n👤 {email}")
                return jsonify({"message": "Bot detenido"}), 200
            else:
                return jsonify({"error": "No hay bot activo"}), 400
                
    except Exception as e:
        logger.error(f"Stop bot error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# --- Bot Logic ---

def run_bot(iq_api, symbol, amount, martingalas, email, sid):
    """Bot principal con martingala"""
    try:
        current_amount = amount
        consecutive_losses = 0
        
        while active_bots.get(email, False):
            try:
                # Verificar conexión
                if not iq_api.check_connect():
                    logger.warning("Reconectando...")
                    iq_api.connect()
                    time.sleep(3)
                    continue
                
                # Obtener velas
                candles = iq_api.get_candles(symbol, 60, 100, time.time())
                
                if not candles or len(candles) < 30:
                    time.sleep(30)
                    continue
                
                # Calcular indicadores
                indicators = calculate_indicators_simple(candles)
                
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
                    status, order_id = iq_api.buy(current_amount, symbol, direction, 1)
                    
                    if status:
                        socketio.emit('trade_opened', {
                            'order_id': order_id,
                            'symbol': symbol,
                            'direction': direction,
                            'amount': current_amount
                        }, room=sid)
                        
                        send_telegram_message(f"""📊 *OPERACIÓN ABIERTA*
📈 {symbol}
🎯 {direction.upper()}
💰 ${current_amount:.2f}
🔢 Martingala: {consecutive_losses}""")
                        
                        # Esperar resultado
                        time.sleep(65)
                        
                        # Verificar resultado
                        profit = iq_api.check_win_v3(order_id)
                        
                        if isinstance(profit, tuple):
                            profit = profit[1] if len(profit) > 1 else 0
                        
                        win = profit > 0
                        
                        socketio.emit('trade_closed', {
                            'order_id': order_id,
                            'result': 'WIN' if win else 'LOSS',
                            'profit': profit
                        }, room=sid)
                        
                        if win:
                            consecutive_losses = 0
                            current_amount = amount
                            send_telegram_message(f"✅ *GANADA* +${profit:.2f}")
                        else:
                            consecutive_losses += 1
                            if consecutive_losses <= martingalas:
                                current_amount *= 2
                                send_telegram_message(f"❌ *PERDIDA* -${abs(profit):.2f}\n🎲 Activando martingala {consecutive_losses}")
                            else:
                                send_telegram_message(f"💀 *MARTINGALAS AGOTADAS*\n💸 Pérdida total sesión")
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
        logger.error(f"Error bot: {e}")
    finally:
        active_bots[email] = False
        socketio.emit('bot_stopped', {'reason': 'finished'}, room=sid)

# --- WebSocket Events ---

@socketio.on('connect')
def handle_connect():
    join_room(request.sid)
    emit('connected', {'sid': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    leave_room(request.sid)

@socketio.on('ping')
def handle_ping():
    emit('pong')

# --- Main ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting server on port {port}")
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
