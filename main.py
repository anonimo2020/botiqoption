import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import traceback
import sys
import time

# Configuración de logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

logger.info("🔧 Aplicando parches de compatibilidad...")

import websocket  # noqa: F401

_original_on_message = None
_original_on_error = None
_original_on_close = None
_original_on_open = None


def patch_websocket_callbacks():
    """Parche para manejar diferentes versiones de websocket-client"""
    try:
        from iqoptionapi.ws.client import WebsocketClient

        global _original_on_message, _original_on_error, _original_on_close, _original_on_open

        if hasattr(WebsocketClient, 'on_message'):
            _original_on_message = WebsocketClient.on_message
        if hasattr(WebsocketClient, 'on_error'):
            _original_on_error = WebsocketClient.on_error
        if hasattr(WebsocketClient, 'on_close'):
            _original_on_close = WebsocketClient.on_close
        if hasattr(WebsocketClient, 'on_open'):
            _original_on_open = WebsocketClient.on_open

        def patched_on_message(self, ws, message=None):
            try:
                actual_message = message if message is not None else ws
                if _original_on_message:
                    try:
                        _original_on_message(self, actual_message)
                    except TypeError:
                        _original_on_message(actual_message)
            except Exception as e:
                logger.debug(f"Error en on_message (ignorado): {e}")

        def patched_on_error(self, ws, error=None):
            try:
                actual_error = error if error is not None else ws
                if _original_on_error:
                    try:
                        _original_on_error(self, actual_error)
                    except TypeError:
                        _original_on_error(actual_error)
            except Exception as e:
                logger.debug(f"Error en on_error (ignorado): {e}")

        def patched_on_close(self, ws=None, close_status_code=None, close_msg=None):
            try:
                if _original_on_close:
                    try:
                        _original_on_close(self)
                    except TypeError:
                        try:
                            _original_on_close(self, ws)
                        except TypeError:
                            _original_on_close()
            except Exception as e:
                logger.debug(f"Error en on_close (ignorado): {e}")

        def patched_on_open(self, ws=None):
            try:
                if _original_on_open:
                    try:
                        _original_on_open(self)
                    except TypeError:
                        _original_on_open(self, ws)
            except Exception as e:
                logger.debug(f"Error en on_open (ignorado): {e}")

        WebsocketClient.on_message = patched_on_message
        WebsocketClient.on_error = patched_on_error
        WebsocketClient.on_close = patched_on_close
        WebsocketClient.on_open = patched_on_open

        logger.info("✅ Parches de WebSocket aplicados correctamente")
        return True

    except Exception as e:
        logger.warning(f"⚠️ No se pudieron aplicar parches: {e}")
        return False


patch_websocket_callbacks()

from flask import Flask, request, jsonify, session
from flask_cors import CORS
from flask_session import Session
import redis
import requests

try:
    from iqoptionapi.stable_api import IQ_Option
    logger.info("✅ IQOptionAPI importada correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando IQOptionAPI: {e}")
    logger.error("Instalando IQOptionAPI...")
    os.system("pip install -U git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
    from iqoptionapi.stable_api import IQ_Option

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, CCIIndicator, EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange

try:
    from session_manager import init_session_manager
    from async_handler import get_async_handler
    from database import init_database, get_database
    from monitoring import init_monitoring, get_monitor
    from security import (
        require_auth, rate_limit, validate_request_data,
        add_security_headers, validate_trading_params
    )
except ImportError as e:
    logger.warning(f"⚠️ Módulos locales no disponibles: {e}")

    def init_session_manager(*args, **kwargs): pass
    def init_database(*args, **kwargs): pass
    def get_database(): return None
    def init_monitoring(*args, **kwargs): pass
    def get_monitor(): return None
    def get_async_handler(): return None

    def require_auth(f): return f
    def rate_limit(*args, **kwargs): return lambda f: f
    def validate_request_data(*args): return lambda f: f
    def add_security_headers(response): return response
    def validate_trading_params(data): return True, None


app = Flask(__name__)

is_production = os.environ.get('FLASK_ENV', '').lower() == 'production'

secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or 'your-secret-key-here'


def sync_session_cookie_name():
    cookie_name = app.config.get("SESSION_COOKIE_NAME", "session")
    setattr(app, "session_cookie_name", cookie_name)

# Configuración CORS mejorada
frontend_url = os.environ.get('FRONTEND_URL', 'https://botiqoption.ct.ws').strip()
allowed_origins = []

# Agregar URL del frontend de producción
if frontend_url:
    allowed_origins.append(frontend_url)
    allowed_origins.append(frontend_url.replace('https://', 'http://'))

# Agregar URLs de desarrollo
allowed_origins.extend([
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173"
])

# Si estás en producción, agregar el dominio de Render
render_url = os.environ.get('https://botiqoption-4.onrender.com', '')
if render_url:
    allowed_origins.append(render_url)

print(f"🌐 CORS Origins permitidos: {allowed_origins}")

# Configuración de cookies más permisiva para desarrollo
if is_production:
    cookie_samesite = 'None'
    cookie_secure = True
else:
    cookie_samesite = 'Lax'
    cookie_secure = False

print(f"🍪 Cookies: SameSite={cookie_samesite}, Secure={cookie_secure}")

app.config.update(
    SECRET_KEY=secret_key,
    SESSION_TYPE='redis',
    SESSION_REDIS=redis.from_url(
        os.environ.get('REDIS_URL', 'redis://localhost:6379'),
        decode_responses=True
    ),
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
    SESSION_COOKIE_SECURE=cookie_secure,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=cookie_samesite,
    SESSION_COOKIE_NAME='iqbot_session',
    SESSION_COOKIE_PATH='/',
    SESSION_USE_SIGNER=True,  # Firmar cookies para mayor seguridad
    SESSION_KEY_PREFIX='iqbot:'  # Prefijo para keys en Redis
)

print(f"✅ Flask configurado correctamente")

# Configuración de sesiones mejorada
redis_url = os.environ.get('REDIS_URL')

if redis_url and 'localhost' not in redis_url:
    # Producción con Redis
    print(f"🔴 Usando Redis: {redis_url[:30]}...")
    try:
        app.config.update(
            SECRET_KEY=secret_key,
            SESSION_TYPE='redis',
            SESSION_REDIS=redis.from_url(redis_url, decode_responses=True),
            SESSION_PERMANENT=True,
            PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
            SESSION_COOKIE_SECURE=cookie_secure,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE=cookie_samesite,
            SESSION_COOKIE_NAME='iqbot_session',
            SESSION_COOKIE_PATH='/',
            SESSION_USE_SIGNER=True,
            SESSION_KEY_PREFIX='iqbot:'
        )
        print("✅ Redis configurado correctamente")
    except Exception as e:
        print(f"❌ Error configurando Redis: {e}")
        # Fallback a null session
        app.config.update(
            SECRET_KEY=secret_key,
            SESSION_TYPE='null',
            SESSION_PERMANENT=False
        )
else:
    # Sin Redis - Usar sesiones básicas de Flask
    print("⚠️ Usando sesiones básicas de Flask (en memoria)")
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_TYPE='null',  # Sesiones solo en cookies firmadas
        SESSION_COOKIE_SECURE=cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=cookie_samesite,
        SESSION_COOKIE_NAME='iqbot_session',
        SESSION_COOKIE_PATH='/'
    )

print(f"✅ Flask configurado correctamente")
sync_session_cookie_name()

Session(app)

CORS(
    app,
    resources={r"/api/*": {"origins": allowed_origins}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    expose_headers=["Content-Type", "X-Total-Count"],
    max_age=3600  # Cache preflight por 1 hora
)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    try:
        init_monitoring(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    except Exception:
        pass

active_bots: Dict[str, dict] = {}

STRATEGIES = {
    "conservative_rsi": {
        "name": "RSI Conservador",
        "risk_level": "very_low",
        "description": "Utiliza RSI con confirmación de tendencia",
        "min_confidence": 75,
        "timeframe": 60,
        "indicators": ["rsi", "ema"],
        "max_loss_multiplier": 1.5
    },
    "macd_cross": {
        "name": "Cruce MACD",
        "risk_level": "low",
        "description": "Señales basadas en cruces de MACD",
        "min_confidence": 70,
        "timeframe": 60,
        "indicators": ["macd", "ema"],
        "max_loss_multiplier": 2.0
    },
    "bollinger_bounce": {
        "name": "Rebote Bollinger",
        "risk_level": "medium",
        "description": "Opera rebotes en bandas de Bollinger",
        "min_confidence": 65,
        "timeframe": 60,
        "indicators": ["bollinger", "rsi"],
        "max_loss_multiplier": 2.5
    },
    "multi_indicator": {
        "name": "Multi-Indicador",
        "risk_level": "medium",
        "description": "Combina RSI, MACD y Stochastic",
        "min_confidence": 60,
        "timeframe": 60,
        "indicators": ["rsi", "macd", "stochastic"],
        "max_loss_multiplier": 3.0
    },
    "momentum_scalper": {
        "name": "Scalping Momentum",
        "risk_level": "high",
        "description": "Operaciones rápidas basadas en momentum",
        "min_confidence": 55,
        "timeframe": 60,
        "indicators": ["cci", "atr", "ema"],
        "max_loss_multiplier": 4.0
    }
}

@app.before_request
def handle_preflight():
    """Maneja requests OPTIONS de preflight"""
    if request.method == "OPTIONS":
        response = jsonify({"status": "ok"})
        origin = request.headers.get('Origin')
        if origin in allowed_origins:
            response.headers.add('Access-Control-Allow-Origin', origin)
            response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
            response.headers.add('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
            response.headers.add('Access-Control-Allow-Credentials', 'true')
            response.headers.add('Access-Control-Max-Age', '3600')
        return response, 200

@app.after_request
def after_request(response):
    response.headers.setdefault('Vary', 'Origin')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.route('/', methods=['GET'])
def index():
    return jsonify({'status': 'online', 'service': 'IQ Option Bot API', 'version': '2.0.0'})

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})

@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    """Endpoint de login con mejor manejo de errores"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        logger.info("🔐 Intento de login recibido")
        logger.info(f"📨 Headers: {dict(request.headers)}")
        logger.info(f"🌐 Origin: {request.headers.get('Origin')}")
        
        data = request.get_json(silent=True) or {}
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            logger.warning("❌ Email o contraseña faltantes")
            return jsonify({
                'success': False, 
                'message': 'Email y contraseña requeridos'
            }), 400

        logger.info(f"📧 Intentando login para: {email}")

        try:
            # Aplicar parches de compatibilidad
            patch_websocket_callbacks()
            
            # Crear instancia de API
            api = IQ_Option(email, password)
            logger.info("✅ Instancia IQ_Option creada")

            # Intentar conectar
            logger.info("🔌 Conectando con IQ Option...")
            check, reason = api.connect()
            logger.info(f"📊 Resultado conexión: check={check}")

            if not check:
                error_msg = "Error de conexión con IQ Option"
                
                if reason:
                    reason_str = str(reason)
                    logger.error(f"❌ Razón del error: {reason_str}")
                    
                    if "invalid_credentials" in reason_str.lower() or "incorrect" in reason_str.lower():
                        error_msg = "Email o contraseña incorrectos"
                    elif "2fa" in reason_str.lower() or "two" in reason_str.lower():
                        error_msg = "Desactiva la autenticación de dos factores en tu cuenta de IQ Option"
                    elif "network" in reason_str.lower() or "connection" in reason_str.lower():
                        error_msg = "Error de red. Verifica tu conexión a internet"
                    else:
                        error_msg = f"Error: {reason_str[:200]}"

                return jsonify({
                    'success': False, 
                    'message': error_msg
                }), 401

            # Obtener balance
            try:
                balance = api.get_balance()
                logger.info(f"💰 Balance obtenido: ${balance}")
            except Exception as e:
                logger.warning(f"⚠️ No se pudo obtener balance: {e}")
                balance = 0

            # Crear sesión
            user_id = email.split('@')[0]
            session.clear()  # Limpiar sesión anterior
            session['user_id'] = user_id
            session['email'] = email
            session['password'] = password
            session['api_connected'] = True
            session['login_time'] = datetime.now().isoformat()
            session.permanent = True

            # Guardar en caché de APIs activas
            if user_id not in active_bots:
                active_bots[user_id] = {}
            active_bots[user_id]['api'] = api

            logger.info(f"✅ Login exitoso para {user_id}")
            logger.info(f"🔑 Session ID: {session.get('_id', 'N/A')}")

            response = jsonify({
                'success': True,
                'message': 'Login exitoso',
                'user': {
                    'id': user_id,
                    'name': user_id,
                    'email': email,
                    'balance': float(balance) if balance else 0
                }
            })
            
            # Agregar headers CORS explícitos
            origin = request.headers.get('Origin')
            if origin in allowed_origins:
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Access-Control-Allow-Credentials'] = 'true'
            
            return response

        except Exception as e:
            logger.error(f"❌ Error en proceso de login: {str(e)}")
            logger.error(f"📋 Traceback: {traceback.format_exc()}")
            return jsonify({
                'success': False, 
                'message': f'Error conectando con IQ Option: {str(e)[:100]}'
            }), 503

    except Exception as e:
        logger.error(f"❌ Error general en login: {str(e)}")
        logger.error(f"📋 Traceback: {traceback.format_exc()}")
        return jsonify({
            'success': False, 
            'message': 'Error interno del servidor'
        }), 500

@app.route('/api/logout', methods=['POST'])
def logout():
    try:
        user_id = session.get('user_id')
        if user_id in active_bots:
            del active_bots[user_id]
        session.clear()
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error en logout: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/strategies', methods=['GET'])
def get_strategies():
    strategies_list = []
    for strategy_id, strategy in STRATEGIES.items():
        strategies_list.append({
            'id': strategy_id,
            'name': strategy['name'],
            'risk_level': strategy['risk_level'],
            'description': strategy['description'],
            'min_confidence': strategy['min_confidence'],
            'timeframe': strategy['timeframe']
        })
    return jsonify({'strategies': strategies_list})


def get_user_api():
    try:
        user_id = session.get('user_id')

        if user_id in active_bots and 'api' in active_bots[user_id]:
            api = active_bots[user_id]['api']
            try:
                api.get_balance()
                return api
            except Exception:
                logger.warning("API en caché desconectada")

        email = session.get('email')
        password = session.get('password')

        if email and password:
            logger.info("Reconectando API...")
            api = IQ_Option(email, password)
            check, _reason = api.connect()
            if check:
                if user_id not in active_bots:
                    active_bots[user_id] = {}
                active_bots[user_id]['api'] = api
                return api

        return None

    except Exception as e:
        logger.error(f"Error obteniendo API: {str(e)}")
        return None

# --- TODO: aquí sigue tu código sin cambios: TradingBot, /api/symbols, /api/balance, /api/start_bot, etc.
# Deja todo igual desde aquí hacia abajo.

# Clase TradingBot completa con todas las funcionalidades
class TradingBot:
    def __init__(self, user_id: str, api: IQ_Option, config: dict):
        self.user_id = user_id
        self.api = api
        self.config = config
        self.running = False
        self.operations_count = 0
        self.consecutive_losses = 0
        self.session_profit = 0
        self.strategy = STRATEGIES[config['strategy']]
        self.results_history = []
        self.current_candles = []  # Para almacenar velas en tiempo real
        
    async def start(self):
        """Inicia el bot de trading"""
        self.running = True
        logger.info(f"Bot iniciado para usuario {self.user_id}")
        
        try:
            while self.running:
                # Verificar límites
                if self._check_limits():
                    logger.info("Límites alcanzados, deteniendo bot")
                    break
                
                # Analizar mercado
                signal = await self._analyze_market()
                
                if signal and signal['confidence'] >= self.strategy['min_confidence']:
                    # Ejecutar operación
                    result = await self._execute_trade(signal)
                    self._update_stats(result)
                
                # Esperar antes de la siguiente análisis
                await asyncio.sleep(10)
                
        except Exception as e:
            logger.error(f"Error en bot: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            self.running = False
            logger.info(f"Bot detenido para usuario {self.user_id}")
    
    def stop(self):
        """Detiene el bot"""
        self.running = False
    
    def _check_limits(self) -> bool:
        """Verifica si se han alcanzado los límites configurados"""
        # Límite de operaciones
        if self.config['max_operations'] > 0 and self.operations_count >= self.config['max_operations']:
            send_telegram_notification(
                f"🛑 Bot detenido - Límite de operaciones alcanzado ({self.operations_count})"
            )
            return True
        
        # Límite de pérdidas consecutivas
        if self.consecutive_losses >= self.config['max_loss_operations']:
            send_telegram_notification(
                f"🚨 Bot detenido - Pérdidas consecutivas: {self.consecutive_losses}"
            )
            return True
        
        return False
    
    async def _analyze_market(self) -> Optional[dict]:
        """Analiza el mercado y genera señales"""
        try:
            symbol = self.config['symbol']
            timeframe = self.strategy['timeframe']
            
            # Obtener datos históricos
            candles = self.api.get_candles(symbol, timeframe, 100, time.time())
            
            if not candles:
                return None
            
            # Guardar las últimas velas para mostrar en tiempo real
            self.current_candles = candles[-30:]  # Últimas 30 velas
            
            # Convertir a DataFrame
            df = pd.DataFrame(candles)
            df['time'] = pd.to_datetime(df['from'], unit='s')
            df.set_index('time', inplace=True)
            
            # Calcular indicadores técnicos
            indicators = self._calculate_indicators(df)
            
            # Generar señal según la estrategia
            signal = self._generate_signal(indicators, df)
            
            return signal
            
        except Exception as e:
            logger.error(f"Error analizando mercado: {str(e)}")
            return None
    
    def _calculate_indicators(self, df: pd.DataFrame) -> dict:
        """Calcula los indicadores técnicos"""
        indicators = {}
        
        # RSI
        if "rsi" in self.strategy['indicators']:
            rsi = RSIIndicator(close=df['close'], window=14)
            indicators['rsi'] = rsi.rsi().iloc[-1]
        
        # MACD
        if "macd" in self.strategy['indicators']:
            macd = MACD(close=df['close'])
            indicators['macd'] = macd.macd().iloc[-1]
            indicators['macd_signal'] = macd.macd_signal().iloc[-1]
            indicators['macd_diff'] = macd.macd_diff().iloc[-1]
        
        # Bollinger Bands
        if "bollinger" in self.strategy['indicators']:
            bb = BollingerBands(close=df['close'])
            indicators['bb_upper'] = bb.bollinger_hband().iloc[-1]
            indicators['bb_lower'] = bb.bollinger_lband().iloc[-1]
            indicators['bb_middle'] = bb.bollinger_mavg().iloc[-1]
        
        # Stochastic
        if "stochastic" in self.strategy['indicators']:
            stoch = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'])
            indicators['stoch_k'] = stoch.stoch().iloc[-1]
            indicators['stoch_d'] = stoch.stoch_signal().iloc[-1]
        
        # CCI
        if "cci" in self.strategy['indicators']:
            cci = CCIIndicator(high=df['high'], low=df['low'], close=df['close'])
            indicators['cci'] = cci.cci().iloc[-1]
        
        # EMA
        if "ema" in self.strategy['indicators']:
            ema_20 = EMAIndicator(close=df['close'], window=20)
            ema_50 = EMAIndicator(close=df['close'], window=50)
            indicators['ema_20'] = ema_20.ema_indicator().iloc[-1]
            indicators['ema_50'] = ema_50.ema_indicator().iloc[-1]
        
        # ATR (para volatilidad)
        if "atr" in self.strategy['indicators']:
            atr = AverageTrueRange(high=df['high'], low=df['low'], close=df['close'])
            indicators['atr'] = atr.average_true_range().iloc[-1]
        
        # Precio actual y tendencia
        indicators['price'] = df['close'].iloc[-1]
        indicators['trend'] = "up" if df['close'].iloc[-1] > df['close'].iloc[-5] else "down"
        
        return indicators
    
    def _generate_signal(self, indicators: dict, df: pd.DataFrame) -> Optional[dict]:
        """Genera señal de trading según la estrategia"""
        signal = {
            'direction': None,
            'confidence': 0,
            'indicators': indicators
        }
        
        strategy_id = self.config['strategy']
        
        if strategy_id == "conservative_rsi":
            signal = self._conservative_rsi_signal(indicators, df)
        elif strategy_id == "macd_cross":
            signal = self._macd_cross_signal(indicators, df)
        elif strategy_id == "bollinger_bounce":
            signal = self._bollinger_bounce_signal(indicators, df)
        elif strategy_id == "multi_indicator":
            signal = self._multi_indicator_signal(indicators, df)
        elif strategy_id == "momentum_scalper":
            signal = self._momentum_scalper_signal(indicators, df)
        
        return signal if signal['confidence'] > 0 else None
    
    def _conservative_rsi_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """Estrategia conservadora basada en RSI"""
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        
        rsi = indicators.get('rsi', 50)
        ema_20 = indicators.get('ema_20', 0)
        ema_50 = indicators.get('ema_50', 0)
        price = indicators['price']
        
        # Señal de CALL
        if rsi < 35 and price > ema_20 and ema_20 > ema_50:
            signal['direction'] = 'call'
            signal['confidence'] = 85 - rsi  # Mayor confianza cuanto más sobrevendido
        
        # Señal de PUT
        elif rsi > 65 and price < ema_20 and ema_20 < ema_50:
            signal['direction'] = 'put'
            signal['confidence'] = rsi - 15  # Mayor confianza cuanto más sobrecomprado
        
        return signal
    
    def _macd_cross_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """Estrategia basada en cruces de MACD"""
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        
        macd = indicators.get('macd', 0)
        macd_signal = indicators.get('macd_signal', 0)
        macd_diff = indicators.get('macd_diff', 0)
        
        # Obtener valores anteriores
        macd_prev = MACD(close=df['close']).macd().iloc[-2]
        macd_signal_prev = MACD(close=df['close']).macd_signal().iloc[-2]
        
        # Cruce alcista
        if macd > macd_signal and macd_prev <= macd_signal_prev:
            signal['direction'] = 'call'
            signal['confidence'] = min(75 + abs(macd_diff) * 10, 90)
        
        # Cruce bajista
        elif macd < macd_signal and macd_prev >= macd_signal_prev:
            signal['direction'] = 'put'
            signal['confidence'] = min(75 + abs(macd_diff) * 10, 90)
        
        return signal
    
    def _bollinger_bounce_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """Estrategia de rebote en bandas de Bollinger"""
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        
        price = indicators['price']
        bb_upper = indicators.get('bb_upper', 0)
        bb_lower = indicators.get('bb_lower', 0)
        bb_middle = indicators.get('bb_middle', 0)
        rsi = indicators.get('rsi', 50)
        
        # Rebote en banda inferior
        if price <= bb_lower * 1.001 and rsi < 40:
            signal['direction'] = 'call'
            signal['confidence'] = 70 + (40 - rsi) * 0.5
        
        # Rebote en banda superior
        elif price >= bb_upper * 0.999 and rsi > 60:
            signal['direction'] = 'put'
            signal['confidence'] = 70 + (rsi - 60) * 0.5
        
        return signal
    
    def _multi_indicator_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """Estrategia que combina múltiples indicadores"""
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        
        rsi = indicators.get('rsi', 50)
        macd_diff = indicators.get('macd_diff', 0)
        stoch_k = indicators.get('stoch_k', 50)
        stoch_d = indicators.get('stoch_d', 50)
        
        call_signals = 0
        put_signals = 0
        
        # RSI
        if rsi < 30:
            call_signals += 2
        elif rsi > 70:
            put_signals += 2
        
        # MACD
        if macd_diff > 0:
            call_signals += 1
        else:
            put_signals += 1
        
        # Stochastic
        if stoch_k < 20 and stoch_k > stoch_d:
            call_signals += 2
        elif stoch_k > 80 and stoch_k < stoch_d:
            put_signals += 2
        
        # Determinar dirección
        if call_signals > put_signals and call_signals >= 3:
            signal['direction'] = 'call'
            signal['confidence'] = 50 + call_signals * 10
        elif put_signals > call_signals and put_signals >= 3:
            signal['direction'] = 'put'
            signal['confidence'] = 50 + put_signals * 10
        
        return signal
    
    def _momentum_scalper_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """Estrategia de scalping basada en momentum"""
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        
        cci = indicators.get('cci', 0)
        atr = indicators.get('atr', 0)
        price = indicators['price']
        ema_20 = indicators.get('ema_20', price)
        
        # Calcular momentum
        momentum = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5] * 100
        
        # Alta volatilidad es buena para scalping
        volatility_factor = min(atr / price * 100, 2)
        
        # Señal de CALL con momentum positivo
        if cci < -100 and momentum > 0.1 and price > ema_20:
            signal['direction'] = 'call'
            signal['confidence'] = 60 + volatility_factor * 10 + abs(momentum) * 5
        
        # Señal de PUT con momentum negativo
        elif cci > 100 and momentum < -0.1 and price < ema_20:
            signal['direction'] = 'put'
            signal['confidence'] = 60 + volatility_factor * 10 + abs(momentum) * 5
        
        return signal
    
    async def _execute_trade(self, signal: dict) -> dict:
        """Ejecuta una operación con velas en tiempo real"""
        try:
            amount = self._calculate_trade_amount()
            
            # Verificar que el monto no exceda el 50% del balance
            balance = self.api.get_balance()
            max_amount = balance * 0.5
            
            if amount > max_amount:
                amount = max_amount
                logger.warning(f"Monto ajustado al 50% del balance: ${amount}")
            
            # Obtener velas actuales para mostrar
            symbol = self.config['symbol']
            current_candles = self.api.get_candles(symbol, 60, 30, time.time())
            
            # Ejecutar operación
            logger.info(f"Ejecutando {signal['direction']} por ${amount} en {symbol}")
            success, order_id = self.api.buy(amount, symbol, signal['direction'], 1)
            
            if success:
                # Esperar resultado
                await asyncio.sleep(70)  # Esperar a que termine la operación de 60 segundos
                
                # Verificar resultado
                result = self.api.check_win_v3(order_id)
                
                trade_result = {
                    'order_id': order_id,
                    'direction': signal['direction'],
                    'amount': amount,
                    'result': result,
                    'profit': amount * 0.85 if result > 0 else -amount,
                    'timestamp': datetime.now(),
                    'confidence': signal['confidence'],
                    'candles': current_candles,  # Incluir velas reales
                    'indicators': signal['indicators']
                }
                
                # Notificar por Telegram con velas
                self._send_trade_notification(trade_result, signal)
                
                # Guardar en base de datos
                try:
                    db = get_database()
                    if db:
                        db.save_trade(self.user_id, {
                            **trade_result,
                            'strategy': self.config['strategy'],
                            'symbol': self.config['symbol']
                        })
                except:
                    pass
                
                # Registrar en monitor
                try:
                    monitor = get_monitor()
                    if monitor:
                        monitor.record_operation(result > 0, trade_result['profit'])
                except:
                    pass
                
                return trade_result
            else:
                logger.error("Error ejecutando operación")
                return None
                
        except Exception as e:
            logger.error(f"Error en ejecución de trade: {str(e)}")
            return None
    
    def _calculate_trade_amount(self) -> float:
        """Calcula el monto de la operación según Martingala modificada"""
        base_amount = self.config['amount']
        
        if self.consecutive_losses == 0:
            return base_amount
        
        # Martingala suave según el nivel de riesgo
        multiplier = self.strategy['max_loss_multiplier']
        return min(base_amount * (multiplier ** self.consecutive_losses), base_amount * 10)
    
    def _update_stats(self, result: dict):
        """Actualiza las estadísticas del bot"""
        if not result:
            return
        
        self.operations_count += 1
        self.results_history.append(result)
        
        if result['result'] > 0:
            self.consecutive_losses = 0
            self.session_profit += result['profit']
        else:
            self.consecutive_losses += 1
            self.session_profit += result['profit']
    
    def _send_trade_notification(self, result: dict, signal: dict):
        """Envía notificación de trade a Telegram"""
        emoji = "✅" if result['result'] > 0 else "❌"
        direction = "📈 CALL" if result['direction'] == 'call' else "📉 PUT"
        
        # Formatear información de velas
        last_candle = result['candles'][-1] if result['candles'] else None
        candle_info = ""
        if last_candle:
            candle_info = f"\n📊 Última vela: O:{last_candle['open']:.5f} H:{last_candle['max']:.5f} L:{last_candle['min']:.5f} C:{last_candle['close']:.5f}"
        
        message = f"""
{emoji} **Operación Ejecutada**
{direction} - ${result['amount']:.2f}
Confianza: {signal['confidence']:.1f}%
Resultado: {'GANADA' if result['result'] > 0 else 'PERDIDA'}
Profit: ${result['profit']:.2f}
Balance Session: ${self.session_profit:.2f}
Operaciones: {self.operations_count}
{candle_info}
"""
        send_telegram_notification(message)
    
    def get_status(self) -> dict:
        """Obtiene el estado actual del bot con velas en tiempo real"""
        return {
            'running': self.running,
            'operations_count': self.operations_count,
            'consecutive_losses': self.consecutive_losses,
            'session_profit': self.session_profit,
            'strategy': self.strategy['name'],
            'last_operations': self.results_history[-10:] if self.results_history else [],
            'current_candles': self.current_candles  # Incluir velas actuales
        }

@app.route('/api/symbols', methods=['GET'])
@require_auth
def get_symbols():
    """Obtiene los símbolos disponibles para trading"""
    try:
        # Reconectar si es necesario
        api = get_user_api()
        if not api:
            return jsonify({'error': 'No autenticado'}), 401
        
        # Obtener activos
        all_assets = api.get_all_open_time()
        
        symbols = []
        is_otc = is_otc_time()
        
        # Filtrar activos según el horario
        for asset, data in all_assets['binary'].items():
            if data['open']:
                # En fin de semana, solo mostrar OTC
                if is_otc and '-OTC' in asset:
                    symbols.append({
                        'symbol': asset,
                        'name': asset.replace('-OTC', ' OTC'),
                        'type': 'OTC'
                    })
                # Entre semana, mostrar no-OTC
                elif not is_otc and '-OTC' not in asset:
                    symbols.append({
                        'symbol': asset,
                        'name': asset.replace('/', ' '),
                        'type': 'Forex' if '/' in asset else 'Stock'
                    })
        
        # Ordenar por nombre
        symbols.sort(key=lambda x: x['name'])
        
        return jsonify({'symbols': symbols})
        
    except Exception as e:
        logger.error(f"Error obteniendo símbolos: {str(e)}")
        return jsonify({'error': 'Error obteniendo símbolos'}), 500

@app.route('/api/balance', methods=['GET'])
@require_auth
def get_balance():
    """Obtiene el balance actual"""
    try:
        api = get_user_api()
        if not api:
            return jsonify({'error': 'No autenticado'}), 401
        
        balance = api.get_balance()
        
        # Calcular métricas
        user_id = session.get('user_id')
        metrics = calculate_user_metrics(user_id)
        
        return jsonify({
            'balance': balance,
            'metrics': metrics
        })
        
    except Exception as e:
        logger.error(f"Error obteniendo balance: {str(e)}")
        return jsonify({'error': 'Error obteniendo balance'}), 500

@app.route('/api/optimal_amount', methods=['POST'])
def calculate_optimal_amount():
    """Calcula el monto óptimo según la estrategia"""
    try:
        data = request.get_json()
        strategy_id = data.get('strategy')
        base_amount = data.get('base_amount', 1)
        
        api = get_user_api()
        if not api:
            return jsonify({'error': 'No autenticado'}), 401
        
        balance = api.get_balance()
        strategy = STRATEGIES.get(strategy_id)
        
        if not strategy:
            return jsonify({'error': 'Estrategia no válida'}), 400
        
        # Calcular según el nivel de riesgo
        risk_factors = {
            'very_low': 0.01,
            'low': 0.02,
            'medium': 0.03,
            'high': 0.05,
            'very_high': 0.08
        }
        
        risk_factor = risk_factors.get(strategy['risk_level'], 0.02)
        optimal = balance * risk_factor
        
        # No exceder el 50% del balance
        max_allowed = balance * 0.5
        optimal = min(optimal, max_allowed)
        
        # Redondear a múltiplos de base_amount
        optimal = max(base_amount, round(optimal / base_amount) * base_amount)
        
        return jsonify({
            'optimal_amount': optimal,
            'risk_level': strategy['risk_level'],
            'balance': balance
        })
        
    except Exception as e:
        logger.error(f"Error calculando monto óptimo: {str(e)}")
        return jsonify({'error': 'Error en cálculo'}), 500

@app.route('/api/start_bot', methods=['POST'])
@require_auth
def start_bot():
    """Inicia el bot de trading"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'No autenticado'}), 401
        
        # Verificar si ya hay un bot activo
        if user_id in active_bots and 'bot' in active_bots[user_id]:
            bot = active_bots[user_id]['bot']
            if bot.running:
                return jsonify({'error': 'Ya hay un bot activo'}), 400
        
        data = request.get_json()
        
        # Validar parámetros de trading
        is_valid, error_msg = validate_trading_params(data)
        if not is_valid:
            return jsonify({'error': error_msg}), 400
        
        # Validar configuración
        config = {
            'symbol': data.get('symbol'),
            'amount': float(data.get('amount', 1)),
            'strategy': data.get('strategy'),
            'account_type': data.get('account_type', 'PRACTICE'),
            'max_operations': int(data.get('max_operations', 0)),
            'max_loss_operations': int(data.get('max_loss_operations', 5))
        }
        
        # Obtener API
        api = get_user_api()
        if not api:
            return jsonify({'error': 'No autenticado'}), 401
        
        # Cambiar tipo de cuenta si es necesario
        if config['account_type'] == 'REAL':
            api.change_balance('REAL')
        else:
            api.change_balance('PRACTICE')
        
        # Crear y ejecutar bot
        bot = TradingBot(user_id, api, config)
        
        if user_id not in active_bots:
            active_bots[user_id] = {}
        active_bots[user_id]['bot'] = bot
        
        # Ejecutar bot en background
        try:
            async_handler = get_async_handler()
            if async_handler:
                async_handler.create_task(bot.start())
            else:
                # Fallback si no hay async handler
                import threading
                thread = threading.Thread(target=lambda: asyncio.run(bot.start()))
                thread.daemon = True
                thread.start()
        except:
            # Fallback simple
            import threading
            thread = threading.Thread(target=lambda: asyncio.run(bot.start()))
            thread.daemon = True
            thread.start()
        
        # Notificar inicio
        strategy_info = STRATEGIES[config['strategy']]
        send_telegram_notification(
            f"🤖 Bot iniciado\n"
            f"📊 Estrategia: {strategy_info['name']}\n"
            f"💵 Monto: ${config['amount']}\n"
            f"🎯 Símbolo: {config['symbol']}\n"
            f"💼 Cuenta: {config['account_type']}"
        )
        
        return jsonify({
            'success': True,
            'message': 'Bot iniciado correctamente',
            'strategy_info': strategy_info
        })
        
    except Exception as e:
        logger.error(f"Error iniciando bot: {str(e)}")
        return jsonify({'error': 'Error al iniciar bot'}), 500

@app.route('/api/stop_bot', methods=['POST'])
def stop_bot():
    """Detiene el bot de trading"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'No autenticado'}), 401
        
        if user_id not in active_bots or 'bot' not in active_bots[user_id]:
            return jsonify({'error': 'No hay bot activo'}), 400
        
        bot = active_bots[user_id]['bot']
        status = bot.get_status()
        bot.stop()
        
        # Esperar a que se detenga
        time.sleep(1)
        
        # Notificar
        send_telegram_notification(
            f"🛑 Bot detenido\n"
            f"📊 Operaciones: {status['operations_count']}\n"
            f"💰 Profit sesión: ${status['session_profit']:.2f}"
        )
        
        return jsonify({
            'success': True,
            'message': 'Bot detenido',
            'final_stats': status
        })
        
    except Exception as e:
        logger.error(f"Error deteniendo bot: {str(e)}")
        return jsonify({'error': 'Error al detener bot'}), 500

@app.route('/api/bot_status', methods=['GET'])
def get_bot_status():
    """Obtiene el estado actual del bot"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'No autenticado'}), 401
        
        if user_id not in active_bots or 'bot' not in active_bots[user_id]:
            return jsonify({
                'running': False,
                'message': 'No hay bot activo'
            })
        
        bot = active_bots[user_id]['bot']
        status = bot.get_status()
        
        return jsonify(status)
        
    except Exception as e:
        logger.error(f"Error obteniendo estado del bot: {str(e)}")
        return jsonify({'error': 'Error obteniendo estado'}), 500

@app.route('/api/live_data', methods=['GET'])
def get_live_data():
    """Obtiene datos en tiempo real del mercado con velas reales"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'No autenticado'}), 401
        
        api = get_user_api()
        if not api:
            return jsonify({'error': 'No autenticado'}), 401
        
        # Obtener símbolo actual del bot o usar default
        symbol = 'EURUSD'
        if user_id in active_bots and 'bot' in active_bots[user_id]:
            symbol = active_bots[user_id]['bot'].config['symbol']
        
        # Obtener velas reales
        candles = api.get_candles(symbol, 60, 30, time.time())
        
        # Convertir para frontend
        candles_data = []
        for candle in candles:
            candles_data.append({
                'time': candle['from'],
                'open': candle['open'],
                'high': candle['max'],
                'low': candle['min'],
                'close': candle['close'],
                'volume': candle.get('volume', 0)
            })
        
        # Calcular indicadores si hay bot activo
        indicators = {}
        signal = {}
        bot_status = None
        
        if user_id in active_bots and 'bot' in active_bots[user_id]:
            bot = active_bots[user_id]['bot']
            bot_status = bot.get_status()
            
            # Calcular indicadores
            if candles:
                df = pd.DataFrame(candles)
                df['time'] = pd.to_datetime(df['from'], unit='s')
                df.set_index('time', inplace=True)
                
                indicators = bot._calculate_indicators(df)
                
                # Obtener señal actual
                signal = bot._generate_signal(indicators, df)
                
                # Añadir volatilidad
                returns = df['close'].pct_change()
                indicators['volatility'] = returns.std() * 100
                
                # Añadir tendencia de corto plazo
                indicators['short_trend'] = "up" if df['close'].iloc[-1] > df['close'].iloc[-5] else "down"
                indicators['price_change'] = ((df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]) * 100
        
        return jsonify({
            'candles': candles_data,
            'indicators': indicators,
            'signal': signal,
            'bot_status': bot_status,
            'symbol': symbol,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error obteniendo datos en vivo: {str(e)}")
        return jsonify({'error': 'Error obteniendo datos'}), 500

# Funciones helper adicionales
def is_otc_time() -> bool:
    """Verifica si es fin de semana (mercado OTC)"""
    now = datetime.now()
    # Sábado = 5, Domingo = 6
    return now.weekday() >= 5

def calculate_user_metrics(user_id: str) -> dict:
    """Calcula métricas del usuario"""
    try:
        db = get_database()
        if db:
            stats = db.get_user_stats(user_id)
            return {
                'total_trades': stats['total_trades'],
                'win_rate': stats['win_rate'],
                'total_profit': stats['total_profit'],
                'strategy_performance': stats['strategy_performance']
            }
    except:
        pass
    
    return {
        'total_trades': 0,
        'win_rate': 0,
        'total_profit': 0,
        'strategy_performance': {}
    }

# Función para enviar notificaciones a Telegram
def send_telegram_notification(message: str):
    """Envía notificación a Telegram"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
        
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, data=data, timeout=5)
    except Exception as e:
        logger.error(f"Error enviando notificación Telegram: {str(e)}")

# Iniciar aplicación
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = not is_production
    
    logger.info(f"🚀 Iniciando servidor en puerto {port}")
    logger.info(f"🌍 Modo: {'Producción' if is_production else 'Desarrollo'}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)
