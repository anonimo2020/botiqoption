# main.py - Backend completo para Bot de Trading IQ Option

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

# Configuración de logging detallado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Agregar path para IQOptionAPI local si existe
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Flask y extensiones
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Importar IQOptionAPI
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando IQOptionAPI: {e}")
    IQ_AVAILABLE = False
    raise Exception("IQOptionAPI no está instalada. Por favor instala: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")

# Configuración Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'trading-bot-secret-key-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_COOKIE_NAME'] = 'trading_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24  # 24 horas

# Crear directorio de sesiones
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# Inicializar extensiones
Session(app)

# CORS configuración completa
CORS(app, 
     resources={r"/*": {
         "origins": "*",
         "methods": ["GET", "POST", "OPTIONS"],
         "allow_headers": ["Content-Type", "Authorization"],
         "expose_headers": ["Content-Type"],
         "supports_credentials": True
     }})

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["200 per day", "50 per hour"]
)

# Variables globales con thread safety
user_sessions = {}  # {email: IQ_Option instance}
active_bots = {}    # {email: Bot instance}
sessions_lock = Lock()
bots_lock = Lock()

# Configuración Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# Métricas de trading por usuario
class TradingMetrics:
    def __init__(self):
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.draws = 0
        self.total_profit = 0.0
        self.max_consecutive_losses = 0
        self.current_consecutive_losses = 0
        self.start_balance = 0.0
        self.current_balance = 0.0
        self.best_profit = 0.0
        self.worst_loss = 0.0
        
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
            "best_profit": round(self.best_profit, 2),
            "worst_loss": round(self.worst_loss, 2),
            "roi": round(((self.current_balance - self.start_balance) / self.start_balance * 100) if self.start_balance > 0 else 0, 2)
        }

user_metrics = {}  # {email: TradingMetrics}

# Funciones auxiliares
def send_telegram_message(message):
    """Envía mensaje a Telegram de forma asíncrona"""
    def send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code != 200:
                logger.error(f"Error Telegram: {response.text}")
        except Exception as e:
            logger.error(f"Error enviando a Telegram: {e}")
    
    Thread(target=send, daemon=True).start()

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
            try:
                if not iq.check_connect():
                    logger.warning(f"Conexión perdida para {email}, reintentando...")
                    if not iq.connect():
                        del user_sessions[email]
                        session.clear()
                        return jsonify({"error": "Conexión perdida con IQ Option", "code": "CONNECTION_LOST"}), 401
            except:
                del user_sessions[email]
                session.clear()
                return jsonify({"error": "Error de conexión", "code": "CONNECTION_ERROR"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# Cálculo de indicadores técnicos
def calculate_indicators(candles):
    """Calcula RSI, MACD, Stochastic y Bollinger Bands"""
    try:
        if len(candles) < 50:
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        
        # RSI (14 períodos)
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
        
        # EMA
        def calculate_ema(data, period):
            ema = np.zeros_like(data)
            ema[0] = data[0]
            multiplier = 2 / (period + 1)
            for i in range(1, len(data)):
                ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
            return ema
        
        # MACD
        ema12 = calculate_ema(closes, 12)
        ema26 = calculate_ema(closes, 26)
        macd_line = ema12 - ema26
        signal_line = calculate_ema(macd_line, 9)
        macd_histogram = macd_line - signal_line
        
        # Stochastic (14, 3, 3)
        period = 14
        lowest_low = np.min(lows[-period:])
        highest_high = np.max(highs[-period:])
        
        if highest_high != lowest_low:
            stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
        else:
            stoch_k = 50
        
        # Stoch D es el promedio móvil de 3 períodos de K
        stoch_d = stoch_k  # Simplificado
        
        # Bollinger Bands
        bb_period = 20
        bb_std = 2
        sma20 = np.mean(closes[-bb_period:])
        std20 = np.std(closes[-bb_period:])
        bb_upper = sma20 + (bb_std * std20)
        bb_lower = sma20 - (bb_std * std20)
        
        # ATR (Average True Range)
        tr = []
        for i in range(1, len(candles)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr.append(max(high_low, high_close, low_close))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else 0
        
        return {
            "rsi": round(calculate_rsi(closes), 2),
            "macd": round(macd_line[-1], 6),
            "macd_signal": round(signal_line[-1], 6),
            "macd_histogram": round(macd_histogram[-1], 6),
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "bb_upper": round(bb_upper, 5),
            "bb_middle": round(sma20, 5),
            "bb_lower": round(bb_lower, 5),
            "atr": round(atr, 5),
            "price": round(closes[-1], 5),
            "sma20": round(sma20, 5),
            "volatility": round((std20 / sma20 * 100) if sma20 > 0 else 0, 2)
        }
        
    except Exception as e:
        logger.error(f"Error calculando indicadores: {e}")
        return None

def get_signal(indicators):
    """Genera señal de trading basada en múltiples indicadores"""
    if not indicators:
        return None, 0
    
    signals = []
    confidence = 0
    
    # RSI
    if indicators['rsi'] < 30:
        signals.append("BUY")
        confidence += 20
    elif indicators['rsi'] > 70:
        signals.append("SELL")
        confidence += 20
    
    # MACD
    if indicators['macd'] > indicators['macd_signal'] and indicators['macd_histogram'] > 0:
        signals.append("BUY")
        confidence += 25
    elif indicators['macd'] < indicators['macd_signal'] and indicators['macd_histogram'] < 0:
        signals.append("SELL")
        confidence += 25
    
    # Stochastic
    if indicators['stoch_k'] < 20 and indicators['stoch_d'] < 20:
        signals.append("BUY")
        confidence += 15
    elif indicators['stoch_k'] > 80 and indicators['stoch_d'] > 80:
        signals.append("SELL")
        confidence += 15
    
    # Bollinger Bands
    if indicators['price'] < indicators['bb_lower']:
        signals.append("BUY")
        confidence += 20
    elif indicators['price'] > indicators['bb_upper']:
        signals.append("SELL")
        confidence += 20
    
    # Determinar señal final
    buy_count = signals.count("BUY")
    sell_count = signals.count("SELL")
    
    if buy_count > sell_count and buy_count >= 3:
        return "call", min(confidence, 100)
    elif sell_count > buy_count and sell_count >= 3:
        return "put", min(confidence, 100)
    
    return None, 0

# Clase Bot de Trading
class TradingBot:
    def __init__(self, iq_api, config, email):
        self.iq_api = iq_api
        self.config = config
        self.email = email
        self.running = False
        self.thread = None
        self.current_amount = config['amount']
        self.consecutive_losses = 0
        self.session_profit = 0
        self.stop_loss_hit = False
        self.take_profit_hit = False
        
    def start(self):
        """Inicia el bot en un thread separado"""
        self.running = True
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
        
    def stop(self):
        """Detiene el bot"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
            
    def _run(self):
        """Loop principal del bot"""
        try:
            logger.info(f"Bot iniciado para {self.email}")
            send_telegram_message(f"""🚀 *BOT INICIADO*
👤 Usuario: {self.email}
📈 Par: {self.config['symbol']}
💰 Monto inicial: ${self.config['amount']:.2f}
🎯 Martingalas: {self.config['martingalas']}
🏦 Cuenta: {self.config['account_type']}
📉 Stop Loss: ${self.config.get('stop_loss', 0):.2f}
📈 Take Profit: ${self.config.get('take_profit', 0):.2f}""")
            
            while self.running:
                try:
                    # Verificar conexión
                    if not self.iq_api.check_connect():
                        logger.warning(f"Reconectando para {self.email}...")
                        if not self.iq_api.connect():
                            logger.error(f"No se pudo reconectar para {self.email}")
                            break
                        time.sleep(3)
                        continue
                    
                    # Verificar stop loss / take profit
                    if self.config.get('stop_loss', 0) > 0 and self.session_profit <= -self.config['stop_loss']:
                        self.stop_loss_hit = True
                        logger.info(f"Stop loss alcanzado para {self.email}")
                        send_telegram_message(f"""🛑 *STOP LOSS ALCANZADO*
👤 Usuario: {self.email}
💸 Pérdida: ${abs(self.session_profit):.2f}
🏁 Bot detenido automáticamente""")
                        break
                    
                    if self.config.get('take_profit', 0) > 0 and self.session_profit >= self.config['take_profit']:
                        self.take_profit_hit = True
                        logger.info(f"Take profit alcanzado para {self.email}")
                        send_telegram_message(f"""🎯 *TAKE PROFIT ALCANZADO*
👤 Usuario: {self.email}
💰 Ganancia: ${self.session_profit:.2f}
🏁 Bot detenido automáticamente""")
                        break
                    
                    # Obtener velas
                    candles = self.iq_api.get_candles(self.config['symbol'], 60, 100, time.time())
                    
                    if not candles or len(candles) < 50:
                        logger.warning(f"Datos insuficientes para {self.config['symbol']}")
                        time.sleep(30)
                        continue
                    
                    # Calcular indicadores
                    indicators = calculate_indicators(candles)
                    if not indicators:
                        time.sleep(30)
                        continue
                    
                    # Generar señal
                    direction, confidence = get_signal(indicators)
                    
                    # Log de análisis
                    analysis_msg = f"""📊 *ANÁLISIS TÉCNICO*
📈 Par: {self.config['symbol']}
💹 Precio: {indicators['price']}
📊 RSI: {indicators['rsi']}
📈 MACD: {indicators['macd']:.4f}
📉 Signal: {indicators['macd_signal']:.4f}
🎯 Stoch K: {indicators['stoch_k']}
📊 Volatilidad: {indicators['volatility']}%"""
                    
                    if direction:
                        analysis_msg += f"\n\n🔔 *SEÑAL: {direction.upper()}*"
                        analysis_msg += f"\n🎯 Confianza: {confidence}%"
                    else:
                        analysis_msg += "\n\n⏳ Sin señal clara"
                    
                    logger.info(f"Análisis: {analysis_msg}")
                    
                    # Ejecutar operación si hay señal fuerte
                    if direction and confidence >= 60:
                        # Verificar balance
                        balance = self.iq_api.get_balance()
                        if self.current_amount > balance:
                            logger.error(f"Fondos insuficientes. Balance: ${balance:.2f}, Requerido: ${self.current_amount:.2f}")
                            send_telegram_message(f"""❌ *FONDOS INSUFICIENTES*
💰 Balance: ${balance:.2f}
💸 Requerido: ${self.current_amount:.2f}
🛑 Bot detenido""")
                            break
                        
                        # Ejecutar trade
                        result = self._execute_trade(direction)
                        
                        # Actualizar métricas
                        if self.email in user_metrics:
                            metrics = user_metrics[self.email]
                            metrics.total_trades += 1
                            
                            if result['result'] == 'WIN':
                                metrics.wins += 1
                                metrics.current_consecutive_losses = 0
                                self.session_profit += result['profit']
                                self.current_amount = self.config['amount']  # Reset
                                self.consecutive_losses = 0
                                
                                if result['profit'] > metrics.best_profit:
                                    metrics.best_profit = result['profit']
                                    
                            elif result['result'] == 'LOSS':
                                metrics.losses += 1
                                metrics.current_consecutive_losses += 1
                                metrics.max_consecutive_losses = max(
                                    metrics.max_consecutive_losses,
                                    metrics.current_consecutive_losses
                                )
                                self.session_profit += result['profit']  # Negativo
                                self.consecutive_losses += 1
                                
                                if result['profit'] < metrics.worst_loss:
                                    metrics.worst_loss = result['profit']
                                
                                # Aplicar Martingala
                                if self.consecutive_losses <= self.config['martingalas']:
                                    self.current_amount *= 2
                                    logger.info(f"Aplicando Martingala {self.consecutive_losses}: ${self.current_amount:.2f}")
                                else:
                                    logger.info("Martingalas agotadas")
                                    send_telegram_message(f"""💀 *MARTINGALAS AGOTADAS*
👤 Usuario: {self.email}
💸 Pérdida acumulada: ${abs(self.session_profit):.2f}
🛑 Bot detenido por seguridad""")
                                    break
                                    
                            else:  # DRAW
                                metrics.draws += 1
                                self.current_amount = self.config['amount']
                                self.consecutive_losses = 0
                            
                            metrics.total_profit = self.session_profit
                            metrics.current_balance = self.iq_api.get_balance()
                        
                        # Pausa entre operaciones
                        time.sleep(90)
                    else:
                        # Sin señal clara, esperar
                        time.sleep(60)
                        
                except Exception as e:
                    logger.error(f"Error en ciclo del bot: {e}")
                    time.sleep(30)
                    
        except Exception as e:
            logger.error(f"Error fatal en bot: {e}")
        finally:
            self.running = False
            with bots_lock:
                if self.email in active_bots:
                    del active_bots[self.email]
            
            # Resumen final
            final_message = f"""🏁 *BOT FINALIZADO*
👤 Usuario: {self.email}
📈 Par: {self.config['symbol']}
💰 Ganancia/Pérdida: ${self.session_profit:.2f}
📊 Trades realizados: {user_metrics.get(self.email, TradingMetrics()).total_trades}
⏰ Finalizado: {datetime.datetime.now().strftime('%H:%M:%S')}"""
            
            if self.stop_loss_hit:
                final_message += "\n🛑 Razón: Stop Loss alcanzado"
            elif self.take_profit_hit:
                final_message += "\n🎯 Razón: Take Profit alcanzado"
            elif self.consecutive_losses > self.config['martingalas']:
                final_message += "\n💀 Razón: Martingalas agotadas"
            
            send_telegram_message(final_message)
            logger.info(f"Bot finalizado para {self.email}")
    
    def _execute_trade(self, direction):
        """Ejecuta una operación y espera el resultado"""
        try:
            logger.info(f"Ejecutando {direction.upper()} en {self.config['symbol']} por ${self.current_amount:.2f}")
            
            # Abrir operación binaria (1 minuto)
            status, order_id = self.iq_api.buy(self.current_amount, self.config['symbol'], direction, 1)
            
            if not status:
                logger.error(f"Error abriendo posición: {order_id}")
                return {"result": "ERROR", "profit": 0, "message": str(order_id)}
            
            # Notificar apertura
            send_telegram_message(f"""🎯 *OPERACIÓN ABIERTA*
📈 Par: {self.config['symbol']}
🎯 Dirección: {direction.upper()}
💰 Monto: ${self.current_amount:.2f}
🆔 ID: {order_id}
⏰ Hora: {datetime.datetime.now().strftime('%H:%M:%S')}
🎲 Martingala: {self.consecutive_losses}""")
            
            # Esperar resultado (operaciones de 1 minuto)
            time.sleep(65)
            
            # Verificar resultado
            result = self.iq_api.check_win_v3(order_id)
            
            # Manejar diferentes formatos de respuesta
            if isinstance(result, tuple) and len(result) >= 2:
                win_amount = result[1]
            elif isinstance(result, (int, float)):
                win_amount = float(result)
            else:
                logger.warning(f"Formato de resultado desconocido: {result}")
                win_amount = None
            
            # Determinar resultado
            if win_amount is None:
                trade_result = "UNKNOWN"
                profit = 0
            elif win_amount > 0:
                trade_result = "WIN"
                profit = win_amount
            elif win_amount < 0:
                trade_result = "LOSS"
                profit = win_amount
            else:
                trade_result = "DRAW"
                profit = 0
            
            # Notificar resultado
            result_emoji = "✅" if trade_result == "WIN" else "❌" if trade_result == "LOSS" else "⚪"
            result_text = "GANADA" if trade_result == "WIN" else "PERDIDA" if trade_result == "LOSS" else "EMPATE"
            
            send_telegram_message(f"""{result_emoji} *OPERACIÓN {result_text}*
📈 Par: {self.config['symbol']}
🎯 Dirección: {direction.upper()}
💰 Monto: ${self.current_amount:.2f}
💵 Resultado: {'+' if profit >= 0 else ''}${profit:.2f}
📊 Balance actual: ${self.iq_api.get_balance():.2f}
⏰ Cierre: {datetime.datetime.now().strftime('%H:%M:%S')}""")
            
            return {
                "result": trade_result,
                "profit": profit,
                "order_id": order_id,
                "amount": self.current_amount
            }
            
        except Exception as e:
            logger.error(f"Error ejecutando trade: {e}")
            return {"result": "ERROR", "profit": 0, "message": str(e)}

# CORS headers
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# Endpoints

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "iq_api_available": IQ_AVAILABLE,
        "active_sessions": len(user_sessions),
        "active_bots": len([b for b in active_bots.values() if b.running])
    }), 200

@app.route('/api/login', methods=['POST', 'OPTIONS'])
@limiter.limit("5 per minute")
def login():
    """Login endpoint"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No se recibieron datos"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña son requeridos"}), 400
        
        logger.info(f"Intento de login para: {email}")
        
        # Limpiar sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        # Crear nueva conexión IQ Option
        iq = IQ_Option(email, password)
        
        # Intentar conectar
        logger.info("Conectando con IQ Option...")
        check, reason = iq.connect()
        
        if not check:
            logger.error(f"Error de conexión: {reason}")
            if reason == "2FA":
                return jsonify({
                    "success": False,
                    "message": "Autenticación de dos factores requerida",
                    "code": "2FA_REQUIRED"
                }), 401
            else:
                return jsonify({
                    "success": False,
                    "message": f"Error de conexión: {reason}"
                }), 503
        
        # Verificar conexión establecida
        if not iq.check_connect():
            return jsonify({
                "success": False,
                "message": "Credenciales incorrectas"
            }), 401
        
        # Obtener información del usuario
        # Como get_profile() puede no funcionar, usamos métodos alternativos
        try:
            # Intentar obtener el email desde la instancia
            user_email = iq.email if hasattr(iq, 'email') else email
            user_name = user_email.split('@')[0].title()
            
            # Obtener balance y tipo de cuenta
            balance = iq.get_balance()
            account_type = iq.get_balance_mode()
            
            # Intentar obtener más información si está disponible
            try:
                # Algunos métodos alternativos según la documentación
                profile_info = {}
                if hasattr(iq, 'get_profile_ansyc'):
                    profile_info = iq.get_profile_ansyc()
                elif hasattr(iq, 'get_user_profile_client'):
                    profile_info = iq.get_user_profile_client(iq.user_id if hasattr(iq, 'user_id') else None)
                
                if profile_info:
                    user_name = profile_info.get('name', user_name)
                    
            except Exception as e:
                logger.warning(f"No se pudo obtener perfil completo: {e}")
            
            # Guardar sesión
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            # Inicializar métricas si es primera vez
            if email not in user_metrics:
                user_metrics[email] = TradingMetrics()
                user_metrics[email].start_balance = balance
                user_metrics[email].current_balance = balance
            
            # Notificar login exitoso
            send_telegram_message(f"""🎯 *LOGIN EXITOSO*
👤 Usuario: {user_name}
📧 Email: {email}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""")
            
            # Respuesta exitosa
            return jsonify({
                "success": True,
                "user": {
                    "name": user_name,
                    "email": email,
                    "balance": float(balance),
                    "account_type": account_type,
                    "currency": "USD"
                },
                "message": "Login exitoso"
            }), 200
            
        except Exception as e:
            logger.error(f"Error obteniendo datos del usuario: {e}")
            # Si hay error pero la conexión está establecida, devolver datos mínimos
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            
            return jsonify({
                "success": True,
                "user": {
                    "name": email.split('@')[0],
                    "email": email,
                    "balance": 0.0,
                    "account_type": "PRACTICE",
                    "currency": "USD"
                },
                "message": "Login exitoso (datos limitados)"
            }), 200
            
    except Exception as e:
        logger.error(f"Error en login: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Error del servidor: {str(e)}"
        }), 500

@app.route('/api/logout', methods=['POST'])
@require_auth
def logout():
    """Logout endpoint"""
    try:
        email = session['user_email']
        
        # Detener bot si está activo
        with bots_lock:
            if email in active_bots:
                active_bots[email].stop()
                del active_bots[email]
        
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
        
        return jsonify({"success": True, "message": "Sesión cerrada correctamente"}), 200
        
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
            "balance": float(balance),
            "account_type": account_type,
            "metrics": user_metrics[email].to_dict() if email in user_metrics else None
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo balance: {str(e)}")
        return jsonify({"error": "Error obteniendo balance"}), 500

@app.route('/api/symbols', methods=['GET'])
@require_auth
def get_symbols():
    """Obtener símbolos disponibles para trading"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        # Determinar si es fin de semana
        weekend = datetime.datetime.today().weekday() >= 5
        
        # Lista de símbolos comunes
        if weekend:
            # En fin de semana solo OTC
            symbols = [
                {"symbol": "EURUSD-OTC", "name": "EUR/USD OTC", "type": "forex-otc"},
                {"symbol": "GBPUSD-OTC", "name": "GBP/USD OTC", "type": "forex-otc"},
                {"symbol": "USDJPY-OTC", "name": "USD/JPY OTC", "type": "forex-otc"},
                {"symbol": "AUDUSD-OTC", "name": "AUD/USD OTC", "type": "forex-otc"},
                {"symbol": "EURJPY-OTC", "name": "EUR/JPY OTC", "type": "forex-otc"},
                {"symbol": "USDCAD-OTC", "name": "USD/CAD OTC", "type": "forex-otc"}
            ]
        else:
            # Días de semana mercados normales
            symbols = [
                {"symbol": "EURUSD", "name": "EUR/USD", "type": "forex"},
                {"symbol": "GBPUSD", "name": "GBP/USD", "type": "forex"},
                {"symbol": "USDJPY", "name": "USD/JPY", "type": "forex"},
                {"symbol": "AUDUSD", "name": "AUD/USD", "type": "forex"},
                {"symbol": "EURJPY", "name": "EUR/JPY", "type": "forex"},
                {"symbol": "USDCAD", "name": "USD/CAD", "type": "forex"}
            ]
        
        # Intentar obtener activos abiertos de IQ Option
        try:
            if hasattr(iq, 'get_all_open_time'):
                all_assets = iq.get_all_open_time()
                # Filtrar solo los que están abiertos
                open_symbols = []
                
                # Verificar forex
                if 'forex' in all_assets:
                    for asset, info in all_assets['forex'].items():
                        if info.get('open', False):
                            open_symbols.append({
                                "symbol": asset,
                                "name": asset,
                                "type": "forex"
                            })
                
                # Verificar turbo (binarias)
                if 'turbo' in all_assets:
                    for asset, info in all_assets['turbo'].items():
                        if info.get('open', False) and asset not in [s['symbol'] for s in open_symbols]:
                            open_symbols.append({
                                "symbol": asset,
                                "name": asset,
                                "type": "turbo"
                            })
                
                if open_symbols:
                    symbols = open_symbols[:10]  # Limitar a 10 símbolos
                    
        except Exception as e:
            logger.warning(f"No se pudieron obtener activos dinámicamente: {e}")
        
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
            if email in active_bots and active_bots[email].running:
                return jsonify({"error": "Ya hay un bot activo para esta sesión"}), 400
        
        data = request.get_json()
        
        # Validar parámetros
        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE')
        stop_loss = float(data.get('stop_loss', 0))
        take_profit = float(data.get('take_profit', 0))
        
        # Validaciones
        if amount <= 0 or amount > 10000:
            return jsonify({"error": "El monto debe estar entre $1 y $10,000"}), 400
        
        if martingalas < 0 or martingalas > 5:
            return jsonify({"error": "Las martingalas deben estar entre 0 y 5"}), 400
        
        if stop_loss < 0:
            return jsonify({"error": "El stop loss no puede ser negativo"}), 400
        
        if take_profit < 0:
            return jsonify({"error": "El take profit no puede ser negativo"}), 400
        
        # Cambiar tipo de cuenta
        iq = user_sessions[email]
        iq.change_balance(account_type)
        
        # Verificar balance
        balance = iq.get_balance()
        max_risk = amount * (2**(martingalas + 1) - 1)  # Riesgo máximo con martingala
        
        if max_risk > balance:
            return jsonify({
                "error": f"Riesgo máximo (${max_risk:.2f}) excede el balance disponible (${balance:.2f})"
            }), 400
        
        # Configuración del bot
        bot_config = {
            'symbol': symbol,
            'amount': amount,
            'martingalas': martingalas,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'account_type': account_type
        }
        
        # Crear e iniciar bot
        bot = TradingBot(iq, bot_config, email)
        
        with bots_lock:
            active_bots[email] = bot
        
        bot.start()
        
        return jsonify({
            "message": "Bot iniciado correctamente",
            "config": bot_config,
            "max_risk": max_risk
        }), 200
        
    except Exception as e:
        logger.error(f"Error iniciando bot: {str(e)}")
        return jsonify({"error": f"Error iniciando bot: {str(e)}"}), 500

@app.route('/api/stop_bot', methods=['POST'])
@require_auth
def stop_bot():
    """Detener bot de trading"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                bot.stop()
                del active_bots[email]
                
                send_telegram_message(f"🛑 *BOT DETENIDO MANUALMENTE*\n👤 {email}")
                
                return jsonify({"message": "Bot detenido correctamente"}), 200
            else:
                return jsonify({"error": "No hay bot activo para detener"}), 400
                
    except Exception as e:
        logger.error(f"Error deteniendo bot: {str(e)}")
        return jsonify({"error": "Error deteniendo bot"}), 500

@app.route('/api/bot_status', methods=['GET'])
@require_auth
def bot_status():
    """Obtener estado del bot"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                status = {
                    "running": bot.running,
                    "current_amount": bot.current_amount,
                    "consecutive_losses": bot.consecutive_losses,
                    "session_profit": bot.session_profit,
                    "config": bot.config
                }
            else:
                status = {
                    "running": False,
                    "message": "No hay bot activo"
                }
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo estado del bot: {str(e)}")
        return jsonify({"error": "Error obteniendo estado"}), 500

@app.route('/api/metrics', methods=['GET'])
@require_auth
def get_metrics():
    """Obtener métricas de trading"""
    try:
        email = session['user_email']
        
        if email in user_metrics:
            metrics = user_metrics[email].to_dict()
        else:
            metrics = TradingMetrics().to_dict()
        
        return jsonify({"metrics": metrics}), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo métricas: {str(e)}")
        return jsonify({"error": "Error obteniendo métricas"}), 500

@app.route('/api/change_account', methods=['POST'])
@require_auth
def change_account():
    """Cambiar entre cuenta real y práctica"""
    try:
        email = session['user_email']
        data = request.get_json()
        
        account_type = data.get('account_type', 'PRACTICE').upper()
        
        if account_type not in ['PRACTICE', 'REAL']:
            return jsonify({"error": "Tipo de cuenta inválido"}), 400
        
        # Verificar si hay bot activo
        with bots_lock:
            if email in active_bots and active_bots[email].running:
                return jsonify({"error": "No se puede cambiar de cuenta con el bot activo"}), 400
        
        iq = user_sessions[email]
        iq.change_balance(account_type)
        
        # Verificar cambio
        new_balance = iq.get_balance()
        new_type = iq.get_balance_mode()
        
        return jsonify({
            "success": True,
            "account_type": new_type,
            "balance": float(new_balance)
        }), 200
        
    except Exception as e:
        logger.error(f"Error cambiando cuenta: {str(e)}")
        return jsonify({"error": "Error cambiando cuenta"}), 500

# Limpieza de sesiones inactivas
def cleanup_inactive_sessions():
    """Limpia sesiones inactivas cada hora"""
    while True:
        time.sleep(3600)  # Cada hora
        try:
            with sessions_lock:
                for email, iq in list(user_sessions.items()):
                    try:
                        if not iq.check_connect():
                            logger.info(f"Limpiando sesión inactiva de {email}")
                            try:
                                iq.close_websocket()
                            except:
                                pass
                            del user_sessions[email]
                    except:
                        # Si hay error verificando, eliminar sesión
                        logger.warning(f"Error verificando sesión de {email}, eliminando")
                        del user_sessions[email]
        except Exception as e:
            logger.error(f"Error en limpieza de sesiones: {e}")

# Iniciar thread de limpieza
cleanup_thread = Thread(target=cleanup_inactive_sessions, daemon=True)
cleanup_thread.start()

# Main
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info(f"🚀 INICIANDO SERVIDOR BOT DE TRADING IQ OPTION")
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🔧 IQ Option API: {'Disponible' if IQ_AVAILABLE else 'No disponible'}")
    logger.info(f"📱 Telegram: {'Configurado' if TELEGRAM_BOT_TOKEN else 'No configurado'}")
    logger.info("=" * 60)
    
    if not IQ_AVAILABLE:
        logger.error("IQOptionAPI no está disponible. El servidor no funcionará correctamente.")
        logger.error("Instala con: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
    
    send_telegram_message(f"""🚀 *SERVIDOR BOT INICIADO*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🔧 API: {'OK' if IQ_AVAILABLE else 'ERROR'}""")
    
    # Usar servidor de desarrollo Flask con threading
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
