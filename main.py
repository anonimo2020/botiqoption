def require_auth(f):
    """Decorador para requerir autenticación con reconexión automática"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
            
            # Verificar conexión IQ Option con reintentos
            iq = user_sessions[email]
            
            # Función para verificar y reconectar si es necesario
            def ensure_connection(max_retries=2):
                for attempt in range(max_retries):
                    try:
                        # Verificar conexión
                        if iq.check_connect():
                            return True
                        
                        logger.warning(f"Conexión perdida para {email}, reintentando... (intento {attempt + 1})")
                        
                        # Intentar reconectar
                        time.sleep(1)  # Pequeña pausa
                        
                        # Crear thread para reconexión con timeout
                        reconnect_result = {'success': False}
                        reconnect_event = Event()
                        
                        def reconnect_thread():
                            try:
                                success = iq.connect()
                                if isinstance(success, tuple):
                                    reconnect_result['success'] = success[0]
                                else:
                                    reconnect_result['success'] = success
                                reconnect_event.set()
                            except Exception as e:
                                logger.error(f"Error en reconexión: {e}")
                                reconnect_result['success'] = False
                                reconnect_event.set()
                        
                        # Ejecutar reconexión con timeout
                        reconnect_worker = Thread(target=reconnect_thread, daemon=True)
                        reconnect_worker.start()
                        
                        if reconnect_event.wait(timeout=15):
                            if reconnect_result['success']:
                                logger.info(f"Reconexión exitosa para {email}")
                                return True
                        else:
                            logger.warning(f"Timeout en reconexión para {email}")
                        
                    except Exception as e:
                        logger.error(f"Error verificando conexión para {email}: {e}")
                
                return False
            
            # Verificar/reconectar con reintentos
            if not ensure_connection():
                # Si no se pudo reconectar, limpiar sesión
                logger.error(f"No se pudo restablecer conexión para {email}")
                try:
                    del user_sessions[email]
                except:
                    pass
                session.clear()
                return jsonify({"error": "Conexión perdida con IQ Option", "code": "CONNECTION_LOST"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# Función para mantener conexiones activas
def connection_keepalive():
    """Mantiene las conexiones WebSocket activas"""
    while True:
        try:
            time.sleep(30)  # Verificar cada 30 segundos
            
            with sessions_lock:
                emails_to_remove = []
                for email, iq in list(user_sessions.items()):
                    try:
                        # Ping básico para mantener conexión
                        if not iq.check_connect():
                            logger.warning(f"Conexión perdida detectada para {email}")
                            emails_to_remove.append(email)
                        else:
                            # Enviar ping silencioso si es posible
                            try:
                                # Obtener timestamp del servidor como ping
                                iq.get_server_timestamp()
                            except:
                                pass
                    except Exception as e:
                        logger.debug(f"Error en keepalive para {email}: {e}")
                        emails_to_remove.append(email)
                
                # Limpiar conexiones muertas
                for email in emails_to_remove:
                    try:
                        logger.info(f"Limpiando conexión muerta: {email}")
                        del user_sessions[email]
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"Error en connection keepalive: {e}")

# Iniciar thread de keepalive
keepalive_thread = Thread(target=connection_keepalive, daemon=True)
keepalive_thread.start()

# Función mejorada para limpiar sesiones inactivas
def cleanup_inactive_sessions():
    """Limpia sesiones inactivas cada hora con mejor detección"""
    while True:
        time.sleep(3600)  # Cada hora
        try:
            logger.info("🧹 Iniciando limpieza de sesiones...")
            cleaned_count = 0
            
            with sessions_lock:
                emails_to_clean = []
                
                for email, iq in list(user_sessions.items()):
                    try:
                        # Verificar múltiples condiciones de sesión muerta
                        is_dead = False
                        
                        # 1. Verificar conexión básica
                        if not iq.check_connect():
                            is_dead = True
                            logger.debug(f"Sesión {email}: conexión cerrada")
                        
                        # 2. Verificar si WebSocket está activo
                        if hasattr(iq, 'websocket_client') and iq.websocket_client:
                            try:
                                ws = iq.websocket_client
                                if hasattr(ws, 'wss') and ws.wss:
                                    if not hasattr(ws.wss, 'sock') or not ws.wss.sock:
                                        is_dead = True
                                        logger.debug(f"Sesión {email}: WebSocket sin socket")
                            except:
                                is_dead = True
                                logger.debug(f"Sesión {email}: Error verificando WebSocket")
                        
                        # 3. Test de comunicación
                        if not is_dead:
                            try:
                                # Intentar operación simple para verificar comunicación
                                balance = iq.get_balance()
                                if balance is None:
                                    is_dead = True
                                    logger.debug(f"Sesión {email}: no responde a get_balance")
                            except Exception as e:
                                is_dead = True
                                logger.debug(f"Sesión {email}: error en test de comunicación: {e}")
                        
                        if is_dead:
                            emails_to_clean.append(email)
                    
                    except Exception as e:
                        logger.warning(f"Error verificando sesión {email}: {e}")
                        emails_to_clean.append(email)
                
                # Limpiar sesiones muertas
                for email in emails_to_clean:
                    try:
                        iq = user_sessions[email]
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        del user_sessions[email]
                        cleaned_count += 1
                        logger.info(f"🗑️ Sesión limpiada: {email}")
                    except:
                        pass
            
            if cleaned_count > 0:
                logger.info(f"✅ Limpieza completada: {cleaned_count} sesiones eliminadas")
            else:
                logger.debug("✅ Limpieza completada: no se encontraron sesiones muertas")
                
        except Exception as e:
            logger.error(f"Error en limpieza de sesiones: {e}")

# Reemplazar el thread de limpieza anterior
cleanup_thread = Thread(target=cleanup_inactive_sessions, daemon=True)
cleanup_thread.start()

# Función para manejar desconexiones gracefully
def graceful_shutdown():
    """Cierra todas las conexiones de forma ordenada"""
    logger.info("🛑 Iniciando cierre ordenado del sistema...")
    
    # Detener todos los bots activos
    with bots_lock:
        for email, bot in list(active_bots.items()):
            try:
                logger.info(f"Deteniendo bot para {email}")
                bot.stop()
            except Exception as e:
                logger.error(f"Error deteniendo bot {email}: {e}")
        active_bots.clear()
    
    # Cerrar todas las sesiones de IQ Option
    with sessions_lock:
        for email, iq in list(user_sessions.items()):
            try:
                logger.info(f"Cerrando sesión para {email}")
                iq.close_websocket()
            except Exception as e:
                logger.error(f"Error cerrando sesión {email}: {e}")
        user_sessions.clear()
    
    logger.info("✅ Cierre ordenado completado")

# Registrar handler para cierre ordenado
import signal
import atexit

def signal_handler(signum, frame):
    logger.info(f"Señal {signum} recibida, iniciando cierre ordenado...")
    graceful_shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
atexit.register(graceful_shutdown)# main.py - Backend Mejorado para Bot de Trading Opciones Binarias Pro

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
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

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

# ============================================================================
# PARCHE PARA WEBSOCKET - SOLUCIONA ERROR DE ARGUMENTOS
# ============================================================================

def apply_websocket_patch():
    """
    Aplica parche para solucionar el error:
    'WebsocketClient.on_close() takes 1 positional argument but 3 were given'
    """
    try:
        logger.info("🔧 Aplicando parche de WebSocket...")
        
        # Crear wrapper para WebSocketApp que maneja argumentos variables
        import websocket
        from websocket import WebSocketApp
        
        class CompatibleWebSocketApp(WebSocketApp):
            """WebSocketApp compatible con diferentes versiones de websocket-client"""
            
            def __init__(self, url, **kwargs):
                def wrap_callback(callback):
                    if callback is None:
                        return None
                    
                    def wrapper(*args, **kwargs_inner):
                        try:
                            # Intentar con el número original de argumentos
                            return callback(*args, **kwargs_inner)
                        except TypeError as e:
                            if "positional argument" in str(e):
                                # Error de argumentos, usar solo el primer argumento (self/ws)
                                try:
                                    return callback(args[0])
                                except:
                                    logger.debug(f"Callback wrapper handled: {e}")
                                    pass
                            else:
                                raise
                    return wrapper
                
                # Wrappear todos los callbacks
                for callback_name in ['on_open', 'on_close', 'on_error', 'on_message']:
                    if callback_name in kwargs:
                        kwargs[callback_name] = wrap_callback(kwargs[callback_name])
                
                super().__init__(url, **kwargs)
        
        # Reemplazar WebSocketApp original
        websocket.WebSocketApp = CompatibleWebSocketApp
        
        logger.info("✅ Parche de WebSocket aplicado correctamente")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error aplicando parche de WebSocket: {e}")
        return False

def patch_iqoption_callbacks():
    """
    Aplica parche específico a los callbacks de IQOptionAPI
    """
    try:
        # Intentar parchear después de importar
        from iqoptionapi.ws.client import WebsocketClient
        
        # Guardar método original
        original_on_close = WebsocketClient.on_close
        
        def patched_on_close(self, *args, **kwargs):
            """Método on_close que acepta argumentos variables"""
            try:
                # Solo ejecutar la lógica básica sin argumentos adicionales
                pass  # El método original de IQOptionAPI no hace nada especial
            except Exception as e:
                logger.debug(f"on_close handled: {e}")
        
        # Aplicar parche
        WebsocketClient.on_close = patched_on_close
        
        logger.info("✅ Callbacks de IQOptionAPI parcheados")
        return True
        
    except ImportError:
        logger.debug("IQOptionAPI no disponible para parchear")
        return False
    except Exception as e:
        logger.error(f"Error parcheando IQOptionAPI: {e}")
        return False

# Aplicar parches antes de importar IQOptionAPI
apply_websocket_patch()

# Flask y extensiones
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Importar IQOptionAPI con parche aplicado
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada correctamente")
    
    # Aplicar parche específico después de importar
    patch_iqoption_callbacks()
    
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

# Enums para estrategias y niveles de riesgo
class RiskLevel(Enum):
    VERY_LOW = "very_low"
    LOW = "low" 
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"

class Strategy(Enum):
    BOLLINGER_RSI = "bollinger_rsi"
    MACD_SIGNAL = "macd_signal"
    TRIPLE_EMA = "triple_ema"
    STOCH_MOMENTUM = "stoch_momentum"
    CCI_DYNAMIC = "cci_dynamic"

# Configuración de estrategias
STRATEGY_CONFIG = {
    Strategy.BOLLINGER_RSI: {
        "name": "Bandas de Bollinger + RSI",
        "description": "Estrategia conservadora basada en sobreventa/sobrecompra",
        "risk_level": RiskLevel.LOW,
        "min_confidence": 70,
        "timeframe": 300,  # 5 minutos
        "expiry": 300,     # 5 minutos
        "indicators": ["bb", "rsi"]
    },
    Strategy.MACD_SIGNAL: {
        "name": "MACD + Señal",
        "description": "Seguimiento de tendencia con cruzamiento de señales",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 65,
        "timeframe": 300,  # 5 minutos
        "expiry": 300,     # 5 minutos
        "indicators": ["macd", "ema"]
    },
    Strategy.TRIPLE_EMA: {
        "name": "Triple EMA + Estocástico",
        "description": "Scalping rápido con múltiples confirmaciones",
        "risk_level": RiskLevel.HIGH,
        "min_confidence": 60,
        "timeframe": 60,   # 1 minuto
        "expiry": 300,     # 5 minutos
        "indicators": ["ema", "stoch"]
    },
    Strategy.STOCH_MOMENTUM: {
        "name": "Estocástico + Momentum",
        "description": "Reversión de momentum en zonas extremas",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 65,
        "timeframe": 300,  # 5 minutos
        "expiry": 300,     # 5 minutos
        "indicators": ["stoch", "rsi", "bb"]
    },
    Strategy.CCI_DYNAMIC: {
        "name": "CCI Dinámico + Bollinger",
        "description": "Volatilidad dinámica para breakouts",
        "risk_level": RiskLevel.VERY_HIGH,
        "min_confidence": 55,
        "timeframe": 300,  # 5 minutos
        "expiry": 300,     # 5 minutos
        "indicators": ["cci", "bb", "ema"]
    }
}

# Métricas de trading por usuario
@dataclass
class TradingMetrics:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_profit: float = 0.0
    max_consecutive_losses: int = 0
    current_consecutive_losses: int = 0
    start_balance: float = 0.0
    current_balance: float = 0.0
    best_profit: float = 0.0
    worst_loss: float = 0.0
    strategy_performance: Dict[str, Dict] = None
    
    def __post_init__(self):
        if self.strategy_performance is None:
            self.strategy_performance = {}
    
    def to_dict(self):
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0
        roi = ((self.current_balance - self.start_balance) / self.start_balance * 100) if self.start_balance > 0 else 0
        
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
            "roi": round(roi, 2),
            "strategy_performance": self.strategy_performance
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

# Cálculo de indicadores técnicos mejorados
def calculate_indicators(candles, strategy: Strategy = None):
    """Calcula indicadores técnicos optimizados para opciones binarias"""
    try:
        if len(candles) < 50:
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        volumes = np.array([float(c.get('volume', 1)) for c in candles])
        
        indicators = {}
        
        # RSI optimizado (14 períodos)
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
        
        # EMA mejorada
        def calculate_ema(data, period):
            ema = np.zeros_like(data)
            ema[0] = data[0]
            multiplier = 2 / (period + 1)
            for i in range(1, len(data)):
                ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
            return ema
        
        # MACD optimizado
        ema12 = calculate_ema(closes, 12)
        ema26 = calculate_ema(closes, 26)
        macd_line = ema12 - ema26
        signal_line = calculate_ema(macd_line, 9)
        macd_histogram = macd_line - signal_line
        
        # Estocástico K y D
        period = 14
        lowest_lows = []
        highest_highs = []
        
        for i in range(period-1, len(closes)):
            lowest_lows.append(np.min(lows[i-period+1:i+1]))
            highest_highs.append(np.max(highs[i-period+1:i+1]))
        
        if len(lowest_lows) > 0:
            lowest_low = lowest_lows[-1]
            highest_high = highest_highs[-1]
            
            if highest_high != lowest_low:
                stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
            else:
                stoch_k = 50
            
            # Calcular %D (promedio móvil de 3 períodos de %K)
            if len(closes) >= period + 2:
                recent_k = []
                for i in range(max(0, len(closes)-3), len(closes)):
                    if i >= period-1:
                        ll = np.min(lows[i-period+1:i+1])
                        hh = np.max(highs[i-period+1:i+1])
                        if hh != ll:
                            k_val = 100 * ((closes[i] - ll) / (hh - ll))
                        else:
                            k_val = 50
                        recent_k.append(k_val)
                stoch_d = np.mean(recent_k) if recent_k else stoch_k
            else:
                stoch_d = stoch_k
        else:
            stoch_k = 50
            stoch_d = 50
        
        # Bollinger Bands
        bb_period = 20
        bb_std = 2
        sma20 = np.mean(closes[-bb_period:])
        std20 = np.std(closes[-bb_period:])
        bb_upper = sma20 + (bb_std * std20)
        bb_lower = sma20 - (bb_std * std20)
        bb_squeeze = (bb_upper - bb_lower) / sma20 * 100  # Medir compresión
        
        # CCI (Commodity Channel Index)
        cci_period = 20
        typical_prices = (highs + lows + closes) / 3
        sma_tp = np.mean(typical_prices[-cci_period:])
        mean_deviation = np.mean(np.abs(typical_prices[-cci_period:] - sma_tp))
        cci = (typical_prices[-1] - sma_tp) / (0.015 * mean_deviation) if mean_deviation != 0 else 0
        
        # Triple EMA para scalping
        ema5 = calculate_ema(closes, 5)
        ema13 = calculate_ema(closes, 13)
        ema21 = calculate_ema(closes, 21)
        
        # ATR para volatilidad
        tr = []
        for i in range(1, len(candles)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr.append(max(high_low, high_close, low_close))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else 0
        
        # Volume Profile (simplificado)
        volume_ratio = volumes[-1] / np.mean(volumes[-20:]) if len(volumes) >= 20 else 1
        
        # Compilar indicadores
        indicators = {
            "price": round(closes[-1], 5),
            "rsi": round(calculate_rsi(closes), 2),
            "macd": round(macd_line[-1], 6),
            "macd_signal": round(signal_line[-1], 6),
            "macd_histogram": round(macd_histogram[-1], 6),
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "bb_upper": round(bb_upper, 5),
            "bb_middle": round(sma20, 5),
            "bb_lower": round(bb_lower, 5),
            "bb_squeeze": round(bb_squeeze, 2),
            "cci": round(cci, 2),
            "ema5": round(ema5[-1], 5),
            "ema13": round(ema13[-1], 5),
            "ema21": round(ema21[-1], 5),
            "atr": round(atr, 5),
            "volatility": round((std20 / sma20 * 100) if sma20 > 0 else 0, 2),
            "volume_ratio": round(volume_ratio, 2),
            "trend_strength": round(abs(macd_histogram[-1]) * 1000, 2)
        }
        
        return indicators
        
    except Exception as e:
        logger.error(f"Error calculando indicadores: {e}")
        return None

# Estrategias de Trading especializadas para opciones binarias
class TradingStrategies:
    
    @staticmethod
    def bollinger_rsi_strategy(indicators):
        """Estrategia Bollinger + RSI - Conservadora"""
        signals = []
        confidence = 0
        
        price = indicators['price']
        rsi = indicators['rsi']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        bb_middle = indicators['bb_middle']
        
        # Señal CALL: Precio cerca banda inferior + RSI sobreventa
        if price <= bb_lower * 1.001 and rsi <= 30:
            signals.append("call")
            confidence += 35
            
        # Señal PUT: Precio cerca banda superior + RSI sobrecompra
        if price >= bb_upper * 0.999 and rsi >= 70:
            signals.append("put")
            confidence += 35
        
        # Confirmación adicional con rebote de bandas
        if price < bb_lower and rsi < 25:
            confidence += 20
        elif price > bb_upper and rsi > 75:
            confidence += 20
            
        # Filtro de volatilidad
        if indicators['bb_squeeze'] < 2:  # Bandas muy comprimidas
            confidence *= 0.7  # Reducir confianza
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def macd_signal_strategy(indicators):
        """Estrategia MACD + Señal - Seguimiento de tendencia"""
        signals = []
        confidence = 0
        
        macd = indicators['macd']
        macd_signal = indicators['macd_signal']
        macd_histogram = indicators['macd_histogram']
        ema21 = indicators['ema21']
        price = indicators['price']
        
        # Cruzamiento MACD alcista
        if macd > macd_signal and macd_histogram > 0:
            signals.append("call")
            confidence += 30
            
        # Cruzamiento MACD bajista
        if macd < macd_signal and macd_histogram < 0:
            signals.append("put")
            confidence += 30
        
        # Confirmación con EMA
        if price > ema21 and macd > macd_signal:
            confidence += 20
        elif price < ema21 and macd < macd_signal:
            confidence += 20
            
        # Fuerza del histograma
        hist_strength = abs(macd_histogram)
        if hist_strength > 0.0001:
            confidence += 15
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def triple_ema_strategy(indicators):
        """Estrategia Triple EMA + Estocástico - Scalping rápido"""
        signals = []
        confidence = 0
        
        price = indicators['price']
        ema5 = indicators['ema5']
        ema13 = indicators['ema13']
        ema21 = indicators['ema21']
        stoch_k = indicators['stoch_k']
        stoch_d = indicators['stoch_d']
        
        # Alineación EMAs alcista
        if ema5 > ema13 > ema21 and price > ema5:
            signals.append("call")
            confidence += 25
            
        # Alineación EMAs bajista
        if ema5 < ema13 < ema21 and price < ema5:
            signals.append("put")
            confidence += 25
        
        # Confirmación estocástica
        if stoch_k < 20 and stoch_d < 20 and stoch_k > stoch_d:
            if "call" in signals:
                confidence += 25
        elif stoch_k > 80 and stoch_d > 80 and stoch_k < stoch_d:
            if "put" in signals:
                confidence += 25
                
        # Momentum de las EMAs
        ema_momentum = (ema5 - ema21) / ema21 * 100
        if abs(ema_momentum) > 0.05:
            confidence += 10
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def stoch_momentum_strategy(indicators):
        """Estrategia Estocástico + Momentum - Reversión"""
        signals = []
        confidence = 0
        
        stoch_k = indicators['stoch_k']
        stoch_d = indicators['stoch_d']
        rsi = indicators['rsi']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        price = indicators['price']
        
        # Divergencia estocástica en sobreventa
        if stoch_k < 20 and stoch_d < 20 and rsi < 35:
            signals.append("call")
            confidence += 30
            
        # Divergencia estocástica en sobrecompra
        if stoch_k > 80 and stoch_d > 80 and rsi > 65:
            signals.append("put")
            confidence += 30
        
        # Confirmación con Bollinger
        if price < bb_lower and stoch_k < 25:
            confidence += 25
        elif price > bb_upper and stoch_k > 75:
            confidence += 25
            
        # Cruzamiento estocástico
        if stoch_k > stoch_d and stoch_k < 30:
            confidence += 15
        elif stoch_k < stoch_d and stoch_k > 70:
            confidence += 15
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def cci_dynamic_strategy(indicators):
        """Estrategia CCI + Bollinger - Volatilidad dinámica"""
        signals = []
        confidence = 0
        
        cci = indicators['cci']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        price = indicators['price']
        bb_squeeze = indicators['bb_squeeze']
        volume_ratio = indicators['volume_ratio']
        
        # CCI extremo con breakout
        if cci < -200 and price < bb_lower:
            signals.append("call")
            confidence += 30
            
        if cci > 200 and price > bb_upper:
            signals.append("put")
            confidence += 30
        
        # Expansión de volatilidad
        if bb_squeeze > 3:  # Alta volatilidad
            confidence += 20
            
        # Confirmación con volumen
        if volume_ratio > 1.5:  # Alto volumen
            confidence += 15
        elif volume_ratio < 0.5:  # Bajo volumen
            confidence *= 0.8
            
        # CCI divergencia
        if abs(cci) > 100:
            confidence += 10
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def _consolidate_signals(signals, confidence):
        """Consolida señales múltiples"""
        if not signals:
            return None, 0
            
        # Contar señales
        call_count = signals.count("call")
        put_count = signals.count("put")
        
        # Determinar señal final
        if call_count > put_count:
            return "call", min(confidence, 100)
        elif put_count > call_count:
            return "put", min(confidence, 100)
        else:
            return None, 0

def get_signal_by_strategy(indicators, strategy: Strategy):
    """Obtiene señal según la estrategia seleccionada"""
    if not indicators:
        return None, 0
    
    strategy_functions = {
        Strategy.BOLLINGER_RSI: TradingStrategies.bollinger_rsi_strategy,
        Strategy.MACD_SIGNAL: TradingStrategies.macd_signal_strategy,
        Strategy.TRIPLE_EMA: TradingStrategies.triple_ema_strategy,
        Strategy.STOCH_MOMENTUM: TradingStrategies.stoch_momentum_strategy,
        Strategy.CCI_DYNAMIC: TradingStrategies.cci_dynamic_strategy
    }
    
    if strategy in strategy_functions:
        return strategy_functions[strategy](indicators)
    else:
        return None, 0

# Gestión de capital avanzada
class MoneyManagement:
    
    @staticmethod
    def kelly_criterion(win_rate, avg_win, avg_loss):
        """Calcula el porcentaje óptimo según Kelly Criterion"""
        if avg_loss == 0 or win_rate <= 0:
            return 0
        
        win_prob = win_rate / 100
        loss_prob = 1 - win_prob
        
        # Kelly = (bp - q) / b
        # b = avg_win / avg_loss (payoff ratio)
        # p = probabilidad de ganar
        # q = probabilidad de perder
        
        payoff_ratio = avg_win / abs(avg_loss)
        kelly_percent = (payoff_ratio * win_prob - loss_prob) / payoff_ratio
        
        # Aplicar Kelly fraccionario (50% del Kelly completo para reducir riesgo)
        return max(0, min(kelly_percent * 0.5, 0.25))  # Max 25% del capital
    
    @staticmethod
    def calculate_position_size(balance, strategy_config, user_metrics, base_amount):
        """Calcula el tamaño de posición óptimo"""
        # Limitar al 50% del capital disponible como máximo
        max_capital = balance * 0.5
        
        # Si el usuario tiene métricas, usar Kelly
        if user_metrics and user_metrics.total_trades >= 10:
            win_rate = (user_metrics.wins / user_metrics.total_trades) * 100
            
            # Calcular promedios de ganancias y pérdidas
            if user_metrics.wins > 0 and user_metrics.losses > 0:
                avg_win = user_metrics.best_profit / user_metrics.wins if user_metrics.wins > 0 else 0
                avg_loss = abs(user_metrics.worst_loss / user_metrics.losses) if user_metrics.losses > 0 else 0
                
                kelly_fraction = MoneyManagement.kelly_criterion(win_rate, avg_win, avg_loss)
                optimal_amount = balance * kelly_fraction
            else:
                optimal_amount = base_amount
        else:
            # Para usuarios nuevos, usar cantidad base conservadora
            optimal_amount = base_amount
        
        # Aplicar límites según nivel de riesgo de la estrategia
        risk_multipliers = {
            RiskLevel.VERY_LOW: 0.5,
            RiskLevel.LOW: 0.7,
            RiskLevel.MEDIUM: 1.0,
            RiskLevel.HIGH: 1.3,
            RiskLevel.VERY_HIGH: 1.5
        }
        
        risk_level = strategy_config.get('risk_level', RiskLevel.MEDIUM)
        risk_multiplier = risk_multipliers.get(risk_level, 1.0)
        
        # Ajustar por rachas perdedoras
        if user_metrics and user_metrics.current_consecutive_losses > 0:
            loss_penalty = 0.8 ** user_metrics.current_consecutive_losses
            optimal_amount *= loss_penalty
        
        # Aplicar multiplicador de riesgo
        final_amount = optimal_amount * risk_multiplier
        
        # Respetar límites
        final_amount = max(1.0, min(final_amount, max_capital))
        
        return round(final_amount, 2)

# Clase Bot de Trading mejorada
class TradingBot:
    def __init__(self, iq_api, config, email):
        self.iq_api = iq_api
        self.config = config
        self.email = email
        self.running = False
        self.thread = None
        self.strategy = Strategy(config['strategy'])
        self.current_amount = config['amount']
        self.consecutive_losses = 0
        self.session_profit = 0
        self.operations_count = 0
        self.max_operations = config.get('max_operations', 0)  # 0 = sin límite
        self.max_loss_operations = config.get('max_loss_operations', 5)  # Límite de pérdidas consecutivas
        self.candles_data = []
        self.last_signal_time = 0
        
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
        """Loop principal del bot mejorado"""
        try:
            strategy_config = STRATEGY_CONFIG[self.strategy]
            logger.info(f"Bot iniciado para {self.email} con estrategia {strategy_config['name']}")
            
            send_telegram_message(f"""🚀 *BOT INICIADO - OPCIONES BINARIAS PRO*
👤 Usuario: {self.email}
📈 Estrategia: {strategy_config['name']}
🎯 Nivel de Riesgo: {strategy_config['risk_level'].value.upper()}
💰 Monto inicial: ${self.config['amount']:.2f}
📊 Timeframe: {strategy_config['timeframe']}s
⏱️ Expiración: {strategy_config['expiry']}s
🏦 Cuenta: {self.config['account_type']}
🛑 Max Pérdidas: {self.max_loss_operations}
📉 Stop después de: {self.max_operations if self.max_operations > 0 else 'Sin límite'} operaciones""")
            
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
                    
                    # Verificar límites de operaciones
                    if self.max_operations > 0 and self.operations_count >= self.max_operations:
                        logger.info(f"Límite de operaciones alcanzado para {self.email}")
                        send_telegram_message(f"""📊 *LÍMITE DE OPERACIONES ALCANZADO*
👤 Usuario: {self.email}
🔢 Operaciones realizadas: {self.operations_count}
💰 Ganancia/Pérdida: ${self.session_profit:.2f}
🏁 Bot detenido automáticamente""")
                        break
                    
                    # Verificar límite de pérdidas consecutivas
                    if self.consecutive_losses >= self.max_loss_operations:
                        logger.info(f"Límite de pérdidas consecutivas alcanzado para {self.email}")
                        send_telegram_message(f"""💀 *LÍMITE DE PÉRDIDAS ALCANZADO*
👤 Usuario: {self.email}
💸 Pérdidas consecutivas: {self.consecutive_losses}
💰 Pérdida acumulada: ${abs(self.session_profit):.2f}
🛑 Bot detenido por seguridad""")
                        break
                    
                    # Obtener velas según el timeframe de la estrategia
                    timeframe = strategy_config['timeframe']
                    candles = self.iq_api.get_candles(self.config['symbol'], timeframe, 100, time.time())
                    
                    if not candles or len(candles) < 50:
                        logger.warning(f"Datos insuficientes para {self.config['symbol']}")
                        time.sleep(30)
                        continue
                    
                    # Almacenar datos para análisis
                    self.candles_data = candles[-50:]  # Últimas 50 velas
                    
                    # Calcular indicadores
                    indicators = calculate_indicators(candles, self.strategy)
                    if not indicators:
                        time.sleep(30)
                        continue
                    
                    # Generar señal según estrategia
                    direction, confidence = get_signal_by_strategy(indicators, self.strategy)
                    
                    # Log de análisis
                    analysis_msg = f"""📊 *ANÁLISIS TÉCNICO - {strategy_config['name'].upper()}*
📈 Par: {self.config['symbol']}
💹 Precio: {indicators['price']}
📊 RSI: {indicators['rsi']}
📈 MACD: {indicators['macd']:.4f}
📉 Signal: {indicators['macd_signal']:.4f}
🎯 Stoch K: {indicators['stoch_k']:.1f}
📊 Volatilidad: {indicators['volatility']:.1f}%
🔥 CCI: {indicators['cci']:.1f}"""
                    
                    if direction:
                        analysis_msg += f"\n\n🔔 *SEÑAL: {direction.upper()}*"
                        analysis_msg += f"\n🎯 Confianza: {confidence:.0f}%"
                        analysis_msg += f"\n📊 Min. requerida: {strategy_config['min_confidence']}%"
                    else:
                        analysis_msg += "\n\n⏳ Sin señal clara"
                    
                    logger.info(f"Análisis: {direction} - Confianza: {confidence}%")
                    
                    # Ejecutar operación si hay señal fuerte y ha pasado tiempo suficiente
                    min_confidence = strategy_config['min_confidence']
                    current_time = time.time()
                    min_interval = 60  # Mínimo 1 minuto entre señales
                    
                    if (direction and confidence >= min_confidence and 
                        current_time - self.last_signal_time >= min_interval):
                        
                        # Verificar balance y calcular tamaño de posición
                        balance = self.iq_api.get_balance()
                        user_metrics_obj = user_metrics.get(self.email)
                        
                        optimal_amount = MoneyManagement.calculate_position_size(
                            balance, strategy_config, user_metrics_obj, self.config['amount']
                        )
                        
                        if optimal_amount > balance:
                            logger.error(f"Fondos insuficientes. Balance: ${balance:.2f}, Requerido: ${optimal_amount:.2f}")
                            send_telegram_message(f"""❌ *FONDOS INSUFICIENTES*
💰 Balance: ${balance:.2f}
💸 Requerido: ${optimal_amount:.2f}
🛑 Bot detenido""")
                            break
                        
                        # Ejecutar trade
                        result = self._execute_trade(direction, optimal_amount, strategy_config)
                        self.last_signal_time = current_time
                        self.operations_count += 1
                        
                        # Actualizar métricas
                        self._update_metrics(result, strategy_config)
                        
                        # Pausa entre operaciones según timeframe
                        pause_time = max(strategy_config['expiry'], 90)
                        time.sleep(pause_time)
                    else:
                        # Sin señal clara o muy pronto, esperar
                        wait_time = 30 if timeframe >= 300 else 15
                        time.sleep(wait_time)
                        
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
📈 Estrategia: {STRATEGY_CONFIG[self.strategy]['name']}
💰 Ganancia/Pérdida: ${self.session_profit:.2f}
📊 Operaciones: {self.operations_count}
⏰ Finalizado: {datetime.datetime.now().strftime('%H:%M:%S')}"""
            
            if self.operations_count >= self.max_operations and self.max_operations > 0:
                final_message += "\n🎯 Razón: Límite de operaciones alcanzado"
            elif self.consecutive_losses >= self.max_loss_operations:
                final_message += "\n💀 Razón: Límite de pérdidas alcanzado"
            
            send_telegram_message(final_message)
            logger.info(f"Bot finalizado para {self.email}")
    
    def _execute_trade(self, direction, amount, strategy_config):
        """Ejecuta una operación y espera el resultado"""
        try:
            expiry_time = strategy_config['expiry']
            logger.info(f"Ejecutando {direction.upper()} en {self.config['symbol']} por ${amount:.2f} - Expiración: {expiry_time}s")
            
            # Abrir operación binaria
            status, order_id = self.iq_api.buy(amount, self.config['symbol'], direction, expiry_time // 60)
            
            if not status:
                logger.error(f"Error abriendo posición: {order_id}")
                return {"result": "ERROR", "profit": 0, "message": str(order_id), "amount": amount}
            
            # Notificar apertura
            send_telegram_message(f"""🎯 *OPERACIÓN ABIERTA*
📈 Par: {self.config['symbol']}
🎯 Dirección: {direction.upper()}
💰 Monto: ${amount:.2f}
⏱️ Expiración: {expiry_time}s
🆔 ID: {order_id}
⏰ Hora: {datetime.datetime.now().strftime('%H:%M:%S')}
📊 Operación #{self.operations_count + 1}
🔥 Estrategia: {STRATEGY_CONFIG[self.strategy]['name']}""")
            
            # Esperar resultado
            wait_time = expiry_time + 10  # Agregar buffer
            time.sleep(wait_time)
            
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
💰 Monto: ${amount:.2f}
💵 Resultado: {'+' if profit >= 0 else ''}${profit:.2f}
📊 Balance actual: ${self.iq_api.get_balance():.2f}
⏰ Cierre: {datetime.datetime.now().strftime('%H:%M:%S')}
🔥 Estrategia: {STRATEGY_CONFIG[self.strategy]['name']}""")
            
            return {
                "result": trade_result,
                "profit": profit,
                "order_id": order_id,
                "amount": amount,
                "strategy": self.strategy.value
            }
            
        except Exception as e:
            logger.error(f"Error ejecutando trade: {e}")
            return {"result": "ERROR", "profit": 0, "message": str(e), "amount": amount}
    
    def _update_metrics(self, trade_result, strategy_config):
        """Actualiza métricas del usuario"""
        if self.email not in user_metrics:
            return
            
        metrics = user_metrics[self.email]
        strategy_name = self.strategy.value
        
        # Inicializar performance de estrategia si no existe
        if strategy_name not in metrics.strategy_performance:
            metrics.strategy_performance[strategy_name] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "profit": 0.0
            }
        
        strategy_perf = metrics.strategy_performance[strategy_name]
        
        # Actualizar métricas generales
        metrics.total_trades += 1
        strategy_perf["trades"] += 1
        
        if trade_result['result'] == 'WIN':
            metrics.wins += 1
            strategy_perf["wins"] += 1
            self.consecutive_losses = 0
            metrics.current_consecutive_losses = 0
            self.session_profit += trade_result['profit']
            
            if trade_result['profit'] > metrics.best_profit:
                metrics.best_profit = trade_result['profit']
                
        elif trade_result['result'] == 'LOSS':
            metrics.losses += 1
            strategy_perf["losses"] += 1
            self.consecutive_losses += 1
            metrics.current_consecutive_losses += 1
            metrics.max_consecutive_losses = max(
                metrics.max_consecutive_losses,
                metrics.current_consecutive_losses
            )
            self.session_profit += trade_result['profit']  # Negativo
            
            if trade_result['profit'] < metrics.worst_loss:
                metrics.worst_loss = trade_result['profit']
                
        else:  # DRAW
            metrics.draws += 1
            self.consecutive_losses = 0
            metrics.current_consecutive_losses = 0
        
        # Actualizar profit de estrategia
        strategy_perf["profit"] += trade_result['profit']
        metrics.total_profit = self.session_profit
        metrics.current_balance = self.iq_api.get_balance()

    def get_live_data(self):
        """Obtiene datos en vivo para el frontend"""
        if not self.candles_data:
            return None
            
        try:
            # Últimas 20 velas para el gráfico
            recent_candles = self.candles_data[-20:]
            
            # Calcular indicadores actuales
            indicators = calculate_indicators(self.candles_data, self.strategy)
            if not indicators:
                return None
            
            # Obtener señal actual
            direction, confidence = get_signal_by_strategy(indicators, self.strategy)
            
            return {
                "candles": [
                    {
                        "time": c.get('time', time.time()),
                        "open": float(c['open']),
                        "high": float(c['max']),
                        "low": float(c['min']),
                        "close": float(c['close']),
                        "volume": float(c.get('volume', 1))
                    } for c in recent_candles
                ],
                "indicators": indicators,
                "signal": {
                    "direction": direction,
                    "confidence": confidence,
                    "strategy": STRATEGY_CONFIG[self.strategy]['name']
                },
                "bot_status": {
                    "running": self.running,
                    "operations_count": self.operations_count,
                    "consecutive_losses": self.consecutive_losses,
                    "session_profit": self.session_profit,
                    "current_amount": self.current_amount
                }
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo datos en vivo: {e}")
            return None

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

@app.route('/', methods=['GET'])
def serve_frontend():
    """Servir el frontend HTML"""
    frontend_html = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Pro - Opciones Binarias</title>
    <style>
        body {
            font-family: 'Arial', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 600px;
            width: 100%;
        }
        .logo {
            font-size: 48px;
            margin-bottom: 20px;
        }
        h1 {
            color: #333;
            margin-bottom: 20px;
        }
        .status {
            background: #d4edda;
            color: #155724;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            border: 1px solid #c3e6cb;
        }
        .info {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            text-align: left;
        }
        .btn {
            background: #007bff;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            margin: 10px;
        }
        .btn:hover {
            background: #0056b3;
        }
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }
        .feature {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }
        .feature h3 {
            margin: 0 0 10px 0;
            color: #007bff;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🚀</div>
        <h1>Trading Bot Pro - Opciones Binarias</h1>
        
        <div class="status">
            ✅ Servidor activo y funcionando correctamente
        </div>
        
        <div class="info">
            <h3>🎯 Sistema Especializado en Opciones Binarias</h3>
            <p>Bot de trading automatizado con:</p>
            <ul>
                <li>✅ 5 estrategias especializadas</li>
                <li>✅ Gestión de capital avanzada (Kelly Criterion)</li>
                <li>✅ Límite de capital al 50% del balance</li>
                <li>✅ Stop loss por operaciones perdidas</li>
                <li>✅ Take profit configurable</li>
                <li>✅ Análisis técnico en tiempo real</li>
                <li>✅ Notificaciones Telegram</li>
            </ul>
        </div>

        <div class="features">
            <div class="feature">
                <h3>📊 Estrategias</h3>
                <p>5 estrategias probadas para diferentes niveles de riesgo</p>
            </div>
            <div class="feature">
                <h3>💰 Gestión Capital</h3>
                <p>Kelly Criterion + Anti-Martingala para máxima seguridad</p>
            </div>
            <div class="feature">
                <h3>📱 Tiempo Real</h3>
                <p>Interfaz moderna con gráficos en vivo</p>
            </div>
            <div class="feature">
                <h3>🛡️ Seguridad</h3>
                <p>Múltiples límites de riesgo y controles</p>
            </div>
        </div>

        <div style="margin-top: 30px;">
            <h3>🔗 Enlaces:</h3>
            <a href="/health" class="btn">📊 Health Check</a>
            <a href="https://github.com" class="btn" target="_blank">📱 Frontend Web</a>
        </div>

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #dee2e6; font-size: 14px; color: #666;">
            <p>🔧 API Endpoints disponibles:</p>
            <ul style="text-align: left; display: inline-block;">
                <li><code>POST /api/login</code> - Autenticación</li>
                <li><code>GET /api/strategies</code> - Estrategias disponibles</li>
                <li><code>POST /api/start_bot</code> - Iniciar bot</li>
                <li><code>GET /api/live_data</code> - Datos en tiempo real</li>
                <li><code>GET /health</code> - Estado del sistema</li>
            </ul>
        </div>
    </div>
</body>
</html>'''
    return frontend_html, 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint mejorado"""
    try:
        # Verificar estado de IQOptionAPI
        iq_status = "available" if IQ_AVAILABLE else "unavailable"
        
        # Contar sesiones activas
        active_sessions = 0
        with sessions_lock:
            for email, iq in user_sessions.items():
                try:
                    if iq.check_connect():
                        active_sessions += 1
                except:
                    pass
        
        # Contar bots activos
        active_bots_count = 0
        with bots_lock:
            for email, bot in active_bots.items():
                if bot.running:
                    active_bots_count += 1
        
        # Verificar conexión a Telegram
        telegram_status = "configured" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "not_configured"
        
        # Estadísticas del sistema
        import psutil
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        
        health_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "iqoption_api": {
                "status": iq_status,
                "version": "available" if IQ_AVAILABLE else "not_installed"
            },
            "sessions": {
                "active": active_sessions,
                "total_registered": len(user_sessions)
            },
            "bots": {
                "active": active_bots_count,
                "total": len(active_bots)
            },
            "telegram": {
                "status": telegram_status,
                "notifications": "enabled" if telegram_status == "configured" else "disabled"
            },
            "strategies": {
                "available": len(STRATEGY_CONFIG),
                "types": [strategy.value for strategy in STRATEGY_CONFIG.keys()]
            },
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "memory_available_gb": round(memory.available / (1024**3), 2)
            },
            "websocket": {
                "patch_applied": True,
                "compatible_version": True
            }
        }
        
        return jsonify(health_data), 200
        
    except Exception as e:
        logger.error(f"Error en health check: {e}")
        return jsonify({
            "status": "error",
            "timestamp": datetime.datetime.now().isoformat(),
            "error": str(e),
            "iqoption_api": "unknown",
            "basic_info": {
                "active_sessions": len(user_sessions),
                "active_bots": len(active_bots)
            }
        }), 500

@app.route('/api/login', methods=['POST', 'OPTIONS'])
@limiter.limit("5 per minute")
def login():
    """Login endpoint con manejo mejorado de conexiones"""
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
        
        # Limpiar cualquier sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    old_iq = user_sessions[email]
                    if hasattr(old_iq, 'websocket_client') and old_iq.websocket_client:
                        try:
                            old_iq.websocket_client.close()
                        except:
                            pass
                    if hasattr(old_iq, 'close_websocket'):
                        try:
                            old_iq.close_websocket()
                        except:
                            pass
                except Exception as e:
                    logger.debug(f"Error limpiando sesión anterior: {e}")
                finally:
                    del user_sessions[email]
        
        # Esperar un momento para asegurar limpieza completa
        time.sleep(0.5)
        
        # Función para intentar conexión con reintentos
        def attempt_connection(max_retries=3):
            for attempt in range(max_retries):
                try:
                    logger.info(f"Intento de conexión {attempt + 1}/{max_retries}")
                    
                    # Crear nueva instancia IQ Option
                    iq = IQ_Option(email, password)
                    
                    # Configurar timeouts más largos
                    if hasattr(iq, 'api') and hasattr(iq.api, 'websocket_client'):
                        try:
                            iq.api.websocket_client.timeout = 30
                        except:
                            pass
                    
                    # Intentar conectar con timeout
                    logger.info("Conectando con IQ Option...")
                    
                    # Usar threading para timeout de conexión
                    connection_result = {'check': False, 'reason': 'Timeout'}
                    connection_event = Event()
                    
                    def connect_thread():
                        try:
                            check, reason = iq.connect()
                            connection_result['check'] = check
                            connection_result['reason'] = reason
                            connection_event.set()
                        except Exception as e:
                            connection_result['check'] = False
                            connection_result['reason'] = str(e)
                            connection_event.set()
                    
                    # Ejecutar conexión en thread separado
                    connect_worker = Thread(target=connect_thread, daemon=True)
                    connect_worker.start()
                    
                    # Esperar con timeout
                    if connection_event.wait(timeout=30):
                        check = connection_result['check']
                        reason = connection_result['reason']
                    else:
                        # Timeout
                        logger.warning(f"Timeout en conexión (intento {attempt + 1})")
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        if attempt < max_retries - 1:
                            time.sleep(2)  # Esperar antes del siguiente intento
                            continue
                        else:
                            return False, "Timeout de conexión. Servidor sobrecargado, intenta más tarde."
                    
                    if not check:
                        logger.error(f"Error de conexión (intento {attempt + 1}): {reason}")
                        
                        # Limpiar conexión fallida
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        
                        # Analizar el tipo de error
                        if isinstance(reason, dict):
                            code = reason.get("code", "")
                            raw_msg = reason.get("message", "")
                        else:
                            try:
                                parsed = json.loads(str(reason))
                                code = parsed.get("code", "")
                                raw_msg = parsed.get("message", "")
                            except:
                                code = str(reason)
                                raw_msg = str(reason)
                        
                        # Errores que no requieren reintentos
                        if code == "2FA":
                            return False, {
                                "message": "Autenticación de dos factores requerida",
                                "code": "2FA_REQUIRED"
                            }
                        elif code == "invalid_credentials" or "wrong credentials" in raw_msg.lower():
                            return False, {
                                "message": "Correo o contraseña incorrecta",
                                "code": "INVALID_CREDENTIALS"
                            }
                        
                        # Errores de conexión que pueden reintentarse
                        if "connection" in raw_msg.lower() or "closed" in raw_msg.lower():
                            if attempt < max_retries - 1:
                                logger.info(f"Error de conexión, reintentando en 2 segundos...")
                                time.sleep(2)
                                continue
                        
                        # Si es el último intento, devolver error
                        if attempt == max_retries - 1:
                            return False, f"Error de conexión después de {max_retries} intentos: {raw_msg}"
                    
                    # Verificar que la conexión esté realmente establecida
                    time.sleep(1)  # Dar tiempo para que se establezca
                    
                    if not iq.check_connect():
                        logger.warning(f"Conexión no verificada (intento {attempt + 1})")
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return False, "No se pudo establecer conexión estable"
                    
                    # Conexión exitosa
                    logger.info("Conexión establecida correctamente")
                    return True, iq
                    
                except Exception as e:
                    logger.error(f"Excepción en intento {attempt + 1}: {str(e)}")
                    if "Connection is already closed" in str(e):
                        if attempt < max_retries - 1:
                            logger.info("Conexión cerrada, reintentando...")
                            time.sleep(2)
                            continue
                    
                    if attempt == max_retries - 1:
                        return False, f"Error de conexión: {str(e)}"
            
            return False, "No se pudo establecer conexión después de múltiples intentos"
        
        # Intentar conexión con reintentos
        success, result = attempt_connection()
        
        if not success:
            if isinstance(result, dict):
                return jsonify({"success": False, **result}), 401
            else:
                return jsonify({"success": False, "message": result}), 503
        
        # result contiene la instancia IQ_Option conectada
        iq = result
        
        # Obtener información del usuario
        try:
            user_email = email
            user_name = user_email.split('@')[0].title()
            
            # Obtener balance y tipo de cuenta con reintentos
            balance = None
            account_type = None
            
            for balance_attempt in range(3):
                try:
                    balance = iq.get_balance()
                    account_type = iq.get_balance_mode()
                    if balance is not None:
                        break
                except Exception as e:
                    logger.warning(f"Error obteniendo balance (intento {balance_attempt + 1}): {e}")
                    if balance_attempt < 2:
                        time.sleep(1)
                    else:
                        # Usar valores por defecto si no se puede obtener
                        balance = 0.0
                        account_type = "PRACTICE"
            
            # Guardar sesión exitosa
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
            send_telegram_message(f"""🎯 *LOGIN EXITOSO - OPCIONES BINARIAS PRO*
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
                "message": "Conexión exitosa con IQ Option"
            }), 200
            
        except Exception as e:
            logger.error(f"Error obteniendo datos del usuario: {e}")
            
            # Si hay error pero la conexión está establecida, devolver datos mínimos
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            return jsonify({
                "success": True,
                "user": {
                    "name": email.split('@')[0],
                    "email": email,
                    "balance": 0.0,
                    "account_type": "PRACTICE",
                    "currency": "USD"
                },
                "message": "Conexión exitosa (datos limitados)"
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
    """Obtener símbolos disponibles para opciones binarias"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        # Lista de símbolos comunes para opciones binarias (NO FOREX)
        binary_symbols = [
            {"symbol": "EURUSD", "name": "EUR/USD", "type": "turbo"},
            {"symbol": "GBPUSD", "name": "GBP/USD", "type": "turbo"}, 
            {"symbol": "USDJPY", "name": "USD/JPY", "type": "turbo"},
            {"symbol": "AUDUSD", "name": "AUD/USD", "type": "turbo"},
            {"symbol": "USDCAD", "name": "USD/CAD", "type": "turbo"},
            {"symbol": "EURJPY", "name": "EUR/JPY", "type": "turbo"},
            {"symbol": "GBPJPY", "name": "GBP/JPY", "type": "turbo"},
            {"symbol": "GOLD", "name": "Gold", "type": "digital"},
            {"symbol": "SILVER", "name": "Silver", "type": "digital"},
            {"symbol": "OIL", "name": "Oil", "type": "digital"}
        ]
        
        # Intentar obtener activos abiertos de IQ Option para binarias
        try:
            if hasattr(iq, 'get_all_open_time'):
                all_assets = iq.get_all_open_time()
                open_symbols = []
                
                # Verificar turbo (opciones binarias)
                if 'turbo' in all_assets:
                    for asset, info in all_assets['turbo'].items():
                        if info.get('open', False):
                            open_symbols.append({
                                "symbol": asset,
                                "name": asset,
                                "type": "turbo"
                            })
                
                # Verificar digital (opciones digitales)
                if 'digital' in all_assets:
                    for asset, info in all_assets['digital'].items():
                        if info.get('open', False):
                            open_symbols.append({
                                "symbol": asset,
                                "name": asset,
                                "type": "digital"
                            })
                
                if open_symbols:
                    binary_symbols = open_symbols[:15]  # Limitar a 15 símbolos
                    
        except Exception as e:
            logger.warning(f"No se pudieron obtener activos dinámicamente: {e}")
        
        return jsonify({"symbols": binary_symbols}), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo símbolos: {str(e)}")
        return jsonify({"error": "Error obteniendo símbolos"}), 500

@app.route('/api/strategies', methods=['GET'])
@require_auth
def get_strategies():
    """Obtener estrategias disponibles"""
    try:
        strategies = []
        for strategy, config in STRATEGY_CONFIG.items():
            strategies.append({
                "id": strategy.value,
                "name": config["name"],
                "description": config["description"],
                "risk_level": config["risk_level"].value,
                "min_confidence": config["min_confidence"],
                "timeframe": config["timeframe"],
                "expiry": config["expiry"],
                "indicators": config["indicators"]
            })
        
        return jsonify({"strategies": strategies}), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo estrategias: {str(e)}")
        return jsonify({"error": "Error obteniendo estrategias"}), 500

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
        strategy = data.get('strategy', Strategy.BOLLINGER_RSI.value)
        account_type = data.get('account_type', 'PRACTICE')
        max_operations = int(data.get('max_operations', 0))
        max_loss_operations = int(data.get('max_loss_operations', 5))
        
        # Validaciones
        if amount <= 0 or amount > 10000:
            return jsonify({"error": "El monto debe estar entre $1 y $10,000"}), 400
        
        try:
            strategy_enum = Strategy(strategy)
        except ValueError:
            return jsonify({"error": "Estrategia no válida"}), 400
        
        if max_loss_operations < 1 or max_loss_operations > 10:
            return jsonify({"error": "El límite de pérdidas debe estar entre 1 y 10"}), 400
        
        # Cambiar tipo de cuenta
        iq = user_sessions[email]
        iq.change_balance(account_type)
        
        # Verificar balance
        balance = iq.get_balance()
        max_risk = balance * 0.5  # Máximo 50% del capital
        
        if amount > max_risk:
            return jsonify({
                "error": f"El monto inicial (${amount:.2f}) excede el 50% del balance disponible (${max_risk:.2f})"
            }), 400
        
        # Configuración del bot
        bot_config = {
            'symbol': symbol,
            'amount': amount,
            'strategy': strategy,
            'account_type': account_type,
            'max_operations': max_operations,
            'max_loss_operations': max_loss_operations
        }
        
        # Crear e iniciar bot
        bot = TradingBot(iq, bot_config, email)
        
        with bots_lock:
            active_bots[email] = bot
        
        bot.start()
        
        strategy_config = STRATEGY_CONFIG[strategy_enum]
        
        return jsonify({
            "message": "Bot iniciado correctamente",
            "config": bot_config,
            "strategy_info": {
                "name": strategy_config["name"],
                "risk_level": strategy_config["risk_level"].value,
                "description": strategy_config["description"]
            },
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
                strategy_config = STRATEGY_CONFIG[bot.strategy]
                
                status = {
                    "running": bot.running,
                    "operations_count": bot.operations_count,
                    "consecutive_losses": bot.consecutive_losses,
                    "session_profit": bot.session_profit,
                    "strategy": {
                        "id": bot.strategy.value,
                        "name": strategy_config["name"],
                        "risk_level": strategy_config["risk_level"].value
                    },
                    "config": bot.config,
                    "limits": {
                        "max_operations": bot.max_operations,
                        "max_loss_operations": bot.max_loss_operations
                    }
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

@app.route('/api/live_data', methods=['GET'])
@require_auth
def get_live_data():
    """Obtener datos en vivo del bot"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                live_data = bot.get_live_data()
                
                if live_data:
                    return jsonify(live_data), 200
                else:
                    return jsonify({"error": "No hay datos disponibles"}), 404
            else:
                return jsonify({"error": "No hay bot activo"}), 404
                
    except Exception as e:
        logger.error(f"Error obteniendo datos en vivo: {str(e)}")
        return jsonify({"error": "Error obteniendo datos en vivo"}), 500

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

@app.route('/api/optimal_amount', methods=['POST'])
@require_auth
def get_optimal_amount():
    """Calcular monto óptimo para trading"""
    try:
        email = session['user_email']
        data = request.get_json()
        
        strategy_id = data.get('strategy', Strategy.BOLLINGER_RSI.value)
        base_amount = float(data.get('base_amount', 1))
        
        try:
            strategy_enum = Strategy(strategy_id)
            strategy_config = STRATEGY_CONFIG[strategy_enum]
        except ValueError:
            return jsonify({"error": "Estrategia no válida"}), 400
        
        iq = user_sessions[email]
        balance = iq.get_balance()
        user_metrics_obj = user_metrics.get(email)
        
        optimal_amount = MoneyManagement.calculate_position_size(
            balance, strategy_config, user_metrics_obj, base_amount
        )
        
        # Información adicional
        max_capital = balance * 0.5
        risk_level = strategy_config['risk_level'].value
        
        recommendation = {
            "optimal_amount": optimal_amount,
            "max_capital": max_capital,
            "current_balance": balance,
            "risk_level": risk_level,
            "strategy_name": strategy_config['name'],
            "recommendation": "conservador" if optimal_amount <= balance * 0.1 else "moderado" if optimal_amount <= balance * 0.25 else "agresivo"
        }
        
        # Si hay métricas, agregar información de Kelly
        if user_metrics_obj and user_metrics_obj.total_trades >= 10:
            win_rate = (user_metrics_obj.wins / user_metrics_obj.total_trades) * 100
            recommendation["win_rate"] = round(win_rate, 2)
            recommendation["total_trades"] = user_metrics_obj.total_trades
            recommendation["using_kelly"] = True
        else:
            recommendation["using_kelly"] = False
            recommendation["note"] = "Usando monto base. Kelly se activará después de 10 operaciones."
        
        return jsonify(recommendation), 200
        
    except Exception as e:
        logger.error(f"Error calculando monto óptimo: {str(e)}")
        return jsonify({"error": "Error calculando monto óptimo"}), 500

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
    
    logger.info("=" * 70)
    logger.info(f"🚀 INICIANDO BOT DE TRADING OPCIONES BINARIAS PRO")
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🔧 IQ Option API: {'Disponible' if IQ_AVAILABLE else 'No disponible'}")
    logger.info(f"📱 Telegram: {'Configurado' if TELEGRAM_BOT_TOKEN else 'No configurado'}")
    logger.info(f"📊 Estrategias disponibles: {len(STRATEGY_CONFIG)}")
    logger.info("🎯 Características:")
    logger.info("   • Gestión de capital avanzada (Kelly Criterion)")
    logger.info("   • 5 estrategias especializadas para opciones binarias")
    logger.info("   • Límite de capital al 50% del balance")
    logger.info("   • Stop loss por número de operaciones perdidas")
    logger.info("   • Take profit por número de operaciones")
    logger.info("   • Análisis técnico en tiempo real")
    logger.info("   • Notificaciones Telegram")
    logger.info("=" * 70)
    
    if not IQ_AVAILABLE:
        logger.error("IQOptionAPI no está disponible. El servidor no funcionará correctamente.")
        logger.error("Instala con: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
    
    send_telegram_message(f"""🚀 *BOT OPCIONES BINARIAS PRO INICIADO*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🔧 API: {'OK' if IQ_AVAILABLE else 'ERROR'}
📊 Estrategias: {len(STRATEGY_CONFIG)}
💰 Gestión: Kelly Criterion + Anti-Martingala
🎯 Límite Capital: 50% del balance""")
    
    # Usar servidor de desarrollo Flask con threading
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
