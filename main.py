# backend.py - Backend Optimizado para Trading Bot
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
from iqoptionapi.stable_api import IQ_Option
from flask_session import Session
import redis
import json

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
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hora

# Inicializar extensiones
Session(app)

# CORS configuración mejorada
CORS(app, 
     resources={r"/*": {
         "origins": ["https://iqoptionbot.ct.ws", "http://localhost:3000", "http://localhost:5000"],
         "methods": ["GET", "POST", "OPTIONS"],
         "allow_headers": ["Content-Type", "Authorization"],
         "expose_headers": ["Content-Type"],
         "supports_credentials": True,
         "max_age": 3600
     }})

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# SocketIO con configuración mejorada
socketio = SocketIO(
    app,
    cors_allowed_origins=["https://iqoptionbot.ct.ws", "http://localhost:3000", "http://localhost:5000"],
    async_mode='eventlet',
    logger=True,
    engineio_logger=True,
    cors_credentials=True,
    ping_timeout=60,
    ping_interval=25
)

# --- Configuración de Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Variables Globales con Thread Safety ---
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# --- Configuración de Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# --- Clases y Utilidades ---

class TradingMetrics:
    """Clase para mantener métricas de trading"""
    def __init__(self):
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.draws = 0
        self.total_profit = 0
        self.max_consecutive_losses = 0
        self.current_consecutive_losses = 0
        self.start_balance = 0
        self.current_balance = 0
        
    def to_dict(self):
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "win_rate": round(win_rate, 2),
            "total_profit": round(self.total_profit, 2),
            "max_consecutive_losses": self.max_consecutive_losses,
            "roi": round(((self.current_balance - self.start_balance) / self.start_balance * 100) if self.start_balance > 0 else 0, 2)
        }

# Métricas por usuario
user_metrics = {}

# --- Decoradores ---

def require_auth(f):
    """Decorador para requerir autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
            
            # Verificar conexión IQ Option
            iq = user_sessions[email]
            if not iq.check_connect():
                logger.warning(f"Conexión IQ Option perdida para {email}")
                # Intentar reconectar
                if not iq.connect():
                    del user_sessions[email]
                    session.clear()
                    return jsonify({"error": "Conexión IQ Option perdida", "code": "CONNECTION_LOST"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# --- Funciones de Utilidad ---

def send_telegram_message(message):
    """Envía mensaje a Telegram con formato mejorado"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram no configurado")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Mensaje enviado a Telegram")
    except Exception as e:
        logger.error(f"Error enviando a Telegram: {e}")

def calculate_indicators(candles):
    """Calcula indicadores técnicos mejorados"""
    try:
        if len(candles) < 30:
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        
        # RSI mejorado
        def calculate_rsi(prices, period=14):
            deltas = np.diff(prices)
            seed = deltas[:period+1]
            up = seed[seed >= 0].sum() / period
            down = -seed[seed < 0].sum() / period
            rs = up / down if down != 0 else 100
            rsi = np.zeros_like(prices)
            rsi[:period] = 100. - 100. / (1. + rs)
            
            for i in range(period, len(prices)):
                delta = deltas[i-1]
                if delta > 0:
                    upval = delta
                    downval = 0.
                else:
                    upval = 0.
                    downval = -delta
                
                up = (up * (period - 1) + upval) / period
                down = (down * (period - 1) + downval) / period
                rs = up / down if down != 0 else 100
                rsi[i] = 100. - 100. / (1. + rs)
            
            return rsi[-1]
        
        # EMA calculación
        def calculate_ema(data, period):
            ema = [sum(data[:period]) / period]
            multiplier = 2 / (period + 1)
            for i in range(period, len(data)):
                ema.append((data[i] - ema[-1]) * multiplier + ema[-1])
            return ema
        
        # Calcular indicadores
        rsi = calculate_rsi(closes)
        
        # MACD
        ema12 = calculate_ema(closes, 12)[-1]
        ema26 = calculate_ema(closes, 26)[-1]
        macd = ema12 - ema26
        signal = calculate_ema(closes, 9)[-1]
        
        # Stochastic
        period = 14
        lowest_low = np.min(lows[-period:])
        highest_high = np.max(highs[-period:])
        current_close = closes[-1]
        
        if highest_high != lowest_low:
            stoch_k = 100 * ((current_close - lowest_low) / (highest_high - lowest_low))
        else:
            stoch_k = 50
        
        # Bollinger Bands
        sma20 = np.mean(closes[-20:])
        std20 = np.std(closes[-20:])
        upper_band = sma20 + (2 * std20)
        lower_band = sma20 - (2 * std20)
        
        # ATR (Average True Range)
        tr = []
        for i in range(1, len(candles)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr.append(max(high_low, high_close, low_close))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else 0
        
        return {
            "rsi": round(rsi, 2),
            "macd": round(macd, 4),
            "signal": round(signal, 4),
            "stoch_k": round(stoch_k, 2),
            "price": round(current_close, 5),
            "sma20": round(sma20, 5),
            "upper_band": round(upper_band, 5),
            "lower_band": round(lower_band, 5),
            "atr": round(atr, 5),
            "volatility": round(std20 / sma20 * 100, 2) if sma20 > 0 else 0
        }
        
    except Exception as e:
        logger.error(f"Error calculando indicadores: {e}")
        return None

def get_signal(indicators):
    """Genera señal de trading con estrategia mejorada"""
    if not indicators:
        return None, 0
    
    score = 0
    direction = None
    
    # Pesos para cada indicador
    weights = {
        'rsi': 2,
        'macd': 2,
        'stoch': 1,
        'bollinger': 1,
        'trend': 1
    }
    
    # RSI
    if indicators['rsi'] < 30:
        score += weights['rsi']
    elif indicators['rsi'] > 70:
        score -= weights['rsi']
    
    # MACD
    if indicators['macd'] > indicators['signal'] and indicators['macd'] > 0:
        score += weights['macd']
    elif indicators['macd'] < indicators['signal'] and indicators['macd'] < 0:
        score -= weights['macd']
    
    # Stochastic
    if indicators['stoch_k'] < 20:
        score += weights['stoch']
    elif indicators['stoch_k'] > 80:
        score -= weights['stoch']
    
    # Bollinger Bands
    if indicators['price'] < indicators['lower_band']:
        score += weights['bollinger']
    elif indicators['price'] > indicators['upper_band']:
        score -= weights['bollinger']
    
    # Tendencia (precio vs SMA20)
    if indicators['price'] > indicators['sma20']:
        score += weights['trend'] * 0.5
    else:
        score -= weights['trend'] * 0.5
    
    # Decisión basada en score
    confidence = abs(score) / sum(weights.values()) * 100
    
    if score >= 3:
        direction = 'call'
    elif score <= -3:
        direction = 'put'
    
    return direction, confidence

# --- Endpoints HTTP ---

@app.before_request
def handle_preflight():
    """Maneja peticiones OPTIONS para CORS"""
    if request.method == "OPTIONS":
        response = make_response()
        origin = request.headers.get('Origin')
        if origin in ["https://iqoptionbot.ct.ws", "http://localhost:3000", "http://localhost:5000"]:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            response.headers['Access-Control-Allow-Credentials'] = 'true'
            response.headers['Access-Control-Max-Age'] = '3600'
        return response

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "active_sessions": len(user_sessions),
        "active_bots": len([b for b in active_bots.values() if b])
    }), 200

@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    """Login endpoint mejorado"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "Datos inválidos"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
        
        logger.info(f"Intento de login para: {email}")
        
        # Cerrar sesión anterior si existe
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        # Conectar a IQ Option
        iq = IQ_Option(email, password)
        
        if not iq.connect():
            return jsonify({"success": False, "message": "Error conectando con IQ Option"}), 401
        
        if not iq.check_connect():
            return jsonify({"success": False, "message": "Credenciales incorrectas"}), 401
        
        # Obtener información del usuario
        profile = iq.get_profile()
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        # Guardar sesión
        with sessions_lock:
            user_sessions[email] = iq
        
        session['user_email'] = email
        session.permanent = True
        
        # Inicializar métricas
        if email not in user_metrics:
            user_metrics[email] = TradingMetrics()
            user_metrics[email].start_balance = balance
            user_metrics[email].current_balance = balance
        
        # Notificar a Telegram
        send_telegram_message(f"""🎯 *NUEVO LOGIN*
👤 Usuario: {profile.get('name', email)}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}
⏰ {datetime.datetime.now().strftime('%H:%M:%S')}""")
        
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
        logger.error(f"Error en login: {str(e)}")
        return jsonify({"success": False, "message": "Error interno del servidor"}), 500

@app.route('/api/logout', methods=['POST'])
@require_auth
def logout():
    """Logout endpoint"""
    try:
        email = session['user_email']
        
        # Detener bot si está activo
        with bots_lock:
            if email in active_bots:
                active_bots[email] = False
        
        # Cerrar conexión IQ Option
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        session.clear()
        
        send_telegram_message(f"👋 *LOGOUT*\n📧 {email}\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
        
        return jsonify({"success": True, "message": "Sesión cerrada"}), 200
        
    except Exception as e:
        logger.error(f"Error en logout: {str(e)}")
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

@app.route('/api/balance', methods=['GET'])
@require_auth
def get_balance():
    """Obtener balance actual"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        # Actualizar métricas
        if email in user_metrics:
            user_metrics[email].current_balance = balance
        
        return jsonify({
            "balance": balance,
            "account_type": account_type,
            "metrics": user_metrics[email].to_dict() if email in user_metrics else None
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo balance: {str(e)}")
        return jsonify({"error": "Error obteniendo balance"}), 500

@app.route('/api/symbols', methods=['GET'])
@require_auth
def get_symbols():
    """Obtener símbolos disponibles"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        # Obtener activos disponibles de IQ Option
        # Por simplicidad, usamos una lista predefinida
        # En producción, deberías obtener esto dinámicamente de IQ Option
        symbols = [
            {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
            {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
            {"symbol": "USDJPY", "name": "USD/JPY", "type": "forex"},
            {"symbol": "AUDUSD", "name": "AUD/USD", "type": "forex"},
            {"symbol": "EURUSD-OTC", "name": "EUR/USD OTC", "type": "forex-otc"},
            {"symbol": "GBPUSD-OTC", "name": "GBP/USD OTC", "type": "forex-otc"}
        ]
        
        return jsonify({"symbols": symbols}), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo símbolos: {str(e)}")
        return jsonify({"error": "Error obteniendo símbolos"}), 500

@app.route('/api/start_bot', methods=['POST'])
@require_auth
@limiter.limit("3 per minute")
def start_bot():
    """Iniciar bot de trading"""
    try:
        email = session['user_email']
        
        # Verificar si ya hay un bot activo
        with bots_lock:
            if active_bots.get(email, False):
                return jsonify({"error": "Ya hay un bot activo"}), 400
        
        data = request.get_json()
        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE')
        stop_loss = float(data.get('stop_loss', 0))
        take_profit = float(data.get('take_profit', 0))
        
        # Validaciones
        if amount <= 0 or amount > 10000:
            return jsonify({"error": "Monto debe estar entre $1 y $10,000"}), 400
        
        if martingalas < 0 or martingalas > 5:
            return jsonify({"error": "Martingalas debe estar entre 0 y 5"}), 400
        
        # Cambiar tipo de cuenta
        iq = user_sessions[email]
        iq.change_balance(account_type)
        
        # Verificar balance
        balance = iq.get_balance()
        max_risk = amount * (2**(martingalas + 1) - 1)
        
        if max_risk > balance:
            return jsonify({
                "error": f"Riesgo máximo (${max_risk:.2f}) excede el balance (${balance:.2f})"
            }), 400
        
        # Marcar bot como activo
        with bots_lock:
            active_bots[email] = True
        
        # Configuración del bot
        bot_config = {
            'symbol': symbol,
            'amount': amount,
            'martingalas': martingalas,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'account_type': account_type
        }
        
        # Iniciar bot en thread
        thread = Thread(
            target=run_bot,
            args=(iq, bot_config, email, request.sid)
        )
        thread.daemon = True
        thread.start()
        
        send_telegram_message(f"""🚀 *BOT INICIADO*
👤 {email}
📈 {symbol} - ${amount:.2f}
🎯 Martingalas: {martingalas}
🏦 Cuenta: {account_type}
💰 Balance: ${balance:.2f}
⚠️ Riesgo máx: ${max_risk:.2f}""")
        
        return jsonify({
            "message": "Bot iniciado correctamente",
            "config": bot_config
        }), 200
        
    except Exception as e:
        logger.error(f"Error iniciando bot: {str(e)}")
        return jsonify({"error": "Error iniciando bot"}), 500

@app.route('/api/stop_bot', methods=['POST'])
@require_auth
def stop_bot():
    """Detener bot de trading"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots and active_bots[email]:
                active_bots[email] = False
                send_telegram_message(f"🛑 *BOT DETENIDO*\n👤 {email}")
                return jsonify({"message": "Bot detenido"}), 200
            else:
                return jsonify({"error": "No hay bot activo"}), 400
                
    except Exception as e:
        logger.error(f"Error deteniendo bot: {str(e)}")
        return jsonify({"error": "Error deteniendo bot"}), 500

# --- Funciones del Bot ---

def run_bot(iq_api, config, email, sid):
    """Función principal del bot mejorada"""
    current_amount = config['amount']
    consecutive_losses = 0
    session_profit = 0
    
    try:
        while active_bots.get(email, False):
            # Verificar conexión
            if not iq_api.check_connect():
                logger.warning(f"Reconectando para {email}...")
                if not iq_api.connect():
                    break
            
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
            
            if direction and confidence >= 60:  # Solo operar con confianza >= 60%
                # Verificar stop loss / take profit
                if config['stop_loss'] > 0 and session_profit <= -config['stop_loss']:
                    logger.info(f"Stop loss alcanzado para {email}")
                    break
                
                if config['take_profit'] > 0 and session_profit >= config['take_profit']:
                    logger.info(f"Take profit alcanzado para {email}")
                    break
                
                # Ejecutar operación
                result = execute_trade(iq_api, config['symbol'], current_amount, direction, email, sid)
                
                # Actualizar métricas
                if email in user_metrics:
                    metrics = user_metrics[email]
                    metrics.total_trades += 1
                    
                    if result['result'] == 'WIN':
                        metrics.wins += 1
                        metrics.current_consecutive_losses = 0
                        session_profit += result['profit']
                        current_amount = config['amount']  # Reset
                        consecutive_losses = 0
                    elif result['result'] == 'LOSS':
                        metrics.losses += 1
                        metrics.current_consecutive_losses += 1
                        metrics.max_consecutive_losses = max(
                            metrics.max_consecutive_losses,
                            metrics.current_consecutive_losses
                        )
                        session_profit += result['profit']
                        consecutive_losses += 1
                        
                        if consecutive_losses <= config['martingalas']:
                            current_amount *= 2
                        else:
                            # Martingalas agotadas
                            break
                    else:  # DRAW
                        metrics.draws += 1
                        current_amount = config['amount']
                        consecutive_losses = 0
                    
                    metrics.total_profit = session_profit
                    metrics.current_balance = iq_api.get_balance()
                
                # Pausa entre operaciones
                time.sleep(90)
            else:
                # Sin señal clara
                time.sleep(60)
                
    except Exception as e:
        logger.error(f"Error en bot para {email}: {str(e)}")
    finally:
        active_bots[email] = False
        socketio.emit('bot_stopped', {
            'reason': 'finished',
            'session_profit': session_profit,
            'metrics': user_metrics[email].to_dict() if email in user_metrics else None
        }, room=sid)

def execute_trade(iq_api, symbol, amount, direction, email, sid):
    """Ejecutar operación con manejo mejorado"""
    try:
        # Abrir operación
        status, order_id = iq_api.buy(amount, symbol, direction, 1)
        
        if not status:
            return {"result": "ERROR", "profit": 0, "message": "Error abriendo posición"}
        
        # Notificar apertura
        socketio.emit('trade_opened', {
            'order_id': order_id,
            'symbol': symbol,
            'direction': direction,
            'amount': amount
        }, room=sid)
        
        # Esperar resultado
        time.sleep(65)
        
        # Verificar resultado
        profit = iq_api.check_win(order_id)
        
        if profit is None:
            result = 'UNKNOWN'
        elif profit > 0:
            result = 'WIN'
        elif profit < 0:
            result = 'LOSS'
        else:
            result = 'DRAW'
        
        # Notificar resultado
        socketio.emit('trade_closed', {
            'order_id': order_id,
            'result': result,
            'profit': profit
        }, room=sid)
        
        return {
            'result': result,
            'profit': profit,
            'order_id': order_id,
            'amount': amount
        }
        
    except Exception as e:
        logger.error(f"Error ejecutando trade: {str(e)}")
        return {"result": "ERROR", "profit": 0, "message": str(e)}

# --- WebSocket Events ---

@socketio.on('connect')
def handle_connect():
    """Manejar conexión WebSocket"""
    join_room(request.sid)
    emit('connected', {'sid': request.sid})
    logger.info(f"Cliente conectado: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """Manejar desconexión WebSocket"""
    leave_room(request.sid)
    logger.info(f"Cliente desconectado: {request.sid}")

@socketio.on('ping')
def handle_ping():
    """Manejar ping para mantener conexión activa"""
    emit('pong')

# --- Tareas en background ---

def cleanup_inactive_sessions():
    """Limpiar sesiones inactivas cada hora"""
    while True:
        time.sleep(3600)
        with sessions_lock:
            for email, iq in list(user_sessions.items()):
                if not iq.check_connect():
                    try:
                        iq.close_websocket()
                    except:
                        pass
                    del user_sessions[email]
                    logger.info(f"Sesión inactiva eliminada: {email}")

# Iniciar limpieza en thread
cleanup_thread = Thread(target=cleanup_inactive_sessions)
cleanup_thread.daemon = True
cleanup_thread.start()

# --- Inicio de la aplicación ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Servidor iniciando en puerto {port}")
    send_telegram_message(f"🚀 *SERVIDOR INICIADO*\n⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Determinar entorno
    is_production = os.environ.get('FLASK_ENV') == 'production' or 'RENDER' in os.environ
    
    if is_production:
        # En producción con Gunicorn
        socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
    else:
        # En desarrollo
        socketio.run(app, debug=True, host='0.0.0.0', port=port)
