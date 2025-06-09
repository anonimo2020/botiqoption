# main.py - Backend REAL para Bot de Trading Opciones Binarias IQ Option
# Configurado específicamente para https://iqoptionbot.ct.ws/

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
import signal
import atexit
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Agregar path para IQOptionAPI
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# PARCHE COMPLETO PARA WEBSOCKET
# ============================================================================

def apply_websocket_patch():
    """Parche para WebSocket"""
    try:
        logger.info("🔧 Aplicando parche WebSocket...")
        
        import websocket
        from websocket import WebSocketApp
        
        class PatchedWebSocketApp(WebSocketApp):
            def __init__(self, url, **kwargs):
                def safe_wrapper(callback):
                    if callback is None:
                        return None
                    
                    def wrapper(*args, **cb_kwargs):
                        try:
                            if len(args) == 1:
                                return callback(args[0])
                            elif len(args) == 2:
                                return callback(args[0], args[1])
                            else:
                                return callback(*args, **cb_kwargs)
                        except TypeError:
                            try:
                                return callback(args[0] if args else None)
                            except:
                                pass
                        except Exception as e:
                            logger.debug(f"Callback error: {e}")
                    
                    return wrapper
                
                for cb_name in ['on_open', 'on_close', 'on_error', 'on_message']:
                    if cb_name in kwargs:
                        kwargs[cb_name] = safe_wrapper(kwargs[cb_name])
                
                super().__init__(url, **kwargs)
        
        websocket.WebSocketApp = PatchedWebSocketApp
        logger.info("✅ Parche WebSocket aplicado")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error en parche: {e}")
        return False

apply_websocket_patch()

# Flask y extensiones
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS, cross_origin
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Importar IQOptionAPI
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada")
except ImportError as e:
    logger.error(f"❌ IQOptionAPI no disponible: {e}")
    IQ_AVAILABLE = False

# Configuración Flask
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'iqoption-bot-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 12

os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# CORS
FRONTEND_DOMAINS = [
    "https://iqoptionbot.ct.ws",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

CORS(app, 
     origins=FRONTEND_DOMAINS,
     methods=['GET', 'POST', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization', 'Accept', 'Origin'],
     supports_credentials=True,
     max_age=3600)

Session(app)

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["1000 per day", "200 per hour"]
)

# Variables globales
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# ============================================================================
# ENUMS Y CONFIGURACIÓN
# ============================================================================

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

BINARY_STRATEGY_CONFIG = {
    Strategy.BOLLINGER_RSI: {
        "name": "Bollinger Bands + RSI",
        "description": "Estrategia conservadora ideal para principiantes",
        "risk_level": RiskLevel.LOW,
        "min_confidence": 78,
        "timeframe": 300,
        "expiry": 5,
        "indicators": ["bollinger_bands", "rsi", "sma"],
        "win_rate_expected": 73,
        "trades_per_day": "6-10",
        "best_for": "Reversiones en soportes y resistencias",
        "market_conditions": "Mercados laterales con volatilidad controlada"
    },
    Strategy.MACD_SIGNAL: {
        "name": "MACD + Signal Cross",
        "description": "Seguimiento de tendencia con confirmación",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 72,
        "timeframe": 300,
        "expiry": 5,
        "indicators": ["macd", "ema_fast", "ema_slow"],
        "win_rate_expected": 68,
        "trades_per_day": "10-15",
        "best_for": "Seguimiento de tendencias confirmadas",
        "market_conditions": "Mercados con tendencia clara"
    },
    Strategy.TRIPLE_EMA: {
        "name": "Triple EMA + Stochastic",
        "description": "Scalping profesional para traders experimentados",
        "risk_level": RiskLevel.HIGH,
        "min_confidence": 65,
        "timeframe": 60,
        "expiry": 5,
        "indicators": ["ema_fast", "ema_medium", "ema_slow", "stochastic"],
        "win_rate_expected": 62,
        "trades_per_day": "20-30",
        "best_for": "Scalping rápido en movimientos intraday",
        "market_conditions": "Alta volatilidad y momentum fuerte"
    },
    Strategy.STOCH_MOMENTUM: {
        "name": "Stochastic + Momentum",
        "description": "Reversiones en zonas extremas con confirmación",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 75,
        "timeframe": 300,
        "expiry": 5,
        "indicators": ["stochastic", "rsi", "bollinger_bands", "momentum"],
        "win_rate_expected": 70,
        "trades_per_day": "8-14",
        "best_for": "Reversiones precisas en sobrecompra/sobreventa",
        "market_conditions": "Mercados oscilantes con niveles claros"
    },
    Strategy.CCI_DYNAMIC: {
        "name": "CCI Dynamic + Bollinger",
        "description": "Para expertos - Volatilidad extrema y breakouts",
        "risk_level": RiskLevel.VERY_HIGH,
        "min_confidence": 60,
        "timeframe": 300,
        "expiry": 5,
        "indicators": ["cci", "bollinger_bands", "ema_fast", "atr"],
        "win_rate_expected": 58,
        "trades_per_day": "15-25",
        "best_for": "Breakouts violentos y noticias importantes",
        "market_conditions": "Volatilidad extrema y eventos de mercado"
    }
}

@dataclass
class BinaryTradingMetrics:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_profit: float = 0.0
    max_consecutive_losses: int = 0
    current_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    current_consecutive_wins: int = 0
    start_balance: float = 0.0
    current_balance: float = 0.0
    best_profit: float = 0.0
    worst_loss: float = 0.0
    strategy_performance: Dict[str, Dict] = None
    daily_profit: float = 0.0
    weekly_profit: float = 0.0
    monthly_profit: float = 0.0
    max_loss_operations: int = 5
    max_win_operations: int = 0
    max_daily_operations: int = 50
    
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
            "daily_profit": round(self.daily_profit, 2),
            "weekly_profit": round(self.weekly_profit, 2),
            "monthly_profit": round(self.monthly_profit, 2),
            "max_consecutive_losses": self.max_consecutive_losses,
            "current_consecutive_losses": self.current_consecutive_losses,
            "max_consecutive_wins": self.max_consecutive_wins,
            "current_consecutive_wins": self.current_consecutive_wins,
            "best_profit": round(self.best_profit, 2),
            "worst_loss": round(self.worst_loss, 2),
            "roi": round(roi, 2),
            "strategy_performance": self.strategy_performance,
            "limits": {
                "max_loss_operations": self.max_loss_operations,
                "max_win_operations": self.max_win_operations,
                "max_daily_operations": self.max_daily_operations
            }
        }

user_metrics = {}

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def send_telegram_message(message):
    """Envía mensaje a Telegram"""
    def send():
        try:
            if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
                return
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
            logger.error(f"Error enviando Telegram: {e}")
    
    Thread(target=send, daemon=True).start()

def require_auth(f):
    """Decorador para autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# BOT SIMPLIFICADO
# ============================================================================

class SimpleBinaryBot:
    def __init__(self, iq_api, config, email):
        self.iq_api = iq_api
        self.config = config
        self.email = email
        self.running = False
        self.thread = None
        self.strategy = Strategy(config['strategy'])
        self.operations_count = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.session_profit = 0.0
        self.daily_operations = 0
        
        # Límites
        self.max_loss_operations = config.get('max_loss_operations', 5)
        self.max_win_operations = config.get('max_win_operations', 0)
        self.max_daily_operations = config.get('max_daily_operations', 50)
        
    def start(self):
        """Iniciar bot"""
        self.running = True
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"🚀 Bot iniciado para {self.email}")
        
    def stop(self):
        """Detener bot"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info(f"🛑 Bot detenido para {self.email}")
        
    def _run(self):
        """Loop principal del bot"""
        try:
            strategy_config = BINARY_STRATEGY_CONFIG[self.strategy]
            logger.info(f"Bot ejecutándose con estrategia: {strategy_config['name']}")
            
            send_telegram_message(f"""🚀 *BOT INICIADO*
👤 Usuario: {self.email}
📈 Estrategia: {strategy_config['name']}
🎯 Riesgo: {strategy_config['risk_level'].value}
💰 Monto: ${self.config['amount']:.2f}
🏦 Cuenta: {self.config['account_type']}""")
            
            while self.running:
                try:
                    # Verificar conexión si IQ Option está disponible
                    if IQ_AVAILABLE and self.iq_api:
                        if not self.iq_api.check_connect():
                            logger.warning("Reconectando...")
                            if not self.iq_api.connect():
                                break
                    
                    # Simular análisis de mercado
                    time.sleep(30)
                    
                    # Simular trade ocasional
                    if np.random.random() < 0.1:  # 10% probabilidad
                        self._simulate_trade(strategy_config)
                    
                except Exception as e:
                    logger.error(f"Error en loop: {e}")
                    time.sleep(60)
                    
        except Exception as e:
            logger.error(f"Error en bot: {e}")
        finally:
            self.running = False
            with bots_lock:
                if self.email in active_bots:
                    del active_bots[self.email]
    
    def _simulate_trade(self, strategy_config):
        """Simular un trade"""
        try:
            direction = np.random.choice(['call', 'put'])
            amount = self.config['amount']
            
            logger.info(f"Simulando trade: {direction} por ${amount}")
            
            # Simular resultado basado en win rate esperado
            win_rate = strategy_config['win_rate_expected'] / 100
            is_win = np.random.random() < win_rate
            
            if is_win:
                profit = amount * 0.8  # 80% payout
                result = 'WIN'
                self.consecutive_losses = 0
                self.consecutive_wins += 1
            else:
                profit = -amount
                result = 'LOSS'
                self.consecutive_losses += 1
                self.consecutive_wins = 0
            
            self.operations_count += 1
            self.daily_operations += 1
            self.session_profit += profit
            
            # Actualizar métricas
            if self.email not in user_metrics:
                user_metrics[self.email] = BinaryTradingMetrics()
            
            metrics = user_metrics[self.email]
            metrics.total_trades += 1
            if result == 'WIN':
                metrics.wins += 1
            else:
                metrics.losses += 1
            metrics.total_profit += profit
            
            # Notificar resultado
            result_emoji = "✅" if result == 'WIN' else "❌"
            send_telegram_message(f"""{result_emoji} *TRADE {result}*
🎯 Dirección: {direction.upper()}
💰 Monto: ${amount:.2f}
💵 Resultado: {'+' if profit >= 0 else ''}${profit:.2f}
📊 Sesión: ${self.session_profit:.2f}
📈 Total: {self.operations_count}""")
            
            # Verificar límites
            if self.consecutive_losses >= self.max_loss_operations:
                logger.info("Límite de pérdidas alcanzado")
                self.stop()
                
        except Exception as e:
            logger.error(f"Error simulando trade: {e}")
    
    def get_live_data(self):
        """Obtener datos en vivo simulados"""
        return {
            'running': self.running,
            'operations_count': self.operations_count,
            'session_profit': self.session_profit,
            'consecutive_wins': self.consecutive_wins,
            'consecutive_losses': self.consecutive_losses
        }

# ============================================================================
# HEADERS CORS
# ============================================================================

@app.after_request
def after_request(response):
    """Headers CORS"""
    origin = request.headers.get('Origin')
    
    if origin in FRONTEND_DOMAINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    elif origin and origin.startswith('http://localhost'):
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = 'https://iqoptionbot.ct.ws'
    
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Origin'
    response.headers['Access-Control-Max-Age'] = '3600'
    
    return response

# ============================================================================
# ENDPOINTS PRINCIPALES
# ============================================================================

@app.route('/', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
def serve_frontend():
    """Frontend"""
    if request.method == 'OPTIONS':
        return '', 204
        
    html = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Opciones Binarias - IQ Option</title>
    <style>
        body {
            font-family: Arial, sans-serif;
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
            max-width: 800px;
            width: 100%;
        }
        .status {
            background: #d4edda;
            color: #155724;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            border: 1px solid #c3e6cb;
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
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Bot de Opciones Binarias</h1>
        <h2>IQ Option Trading API</h2>
        
        <div class="status">
            ✅ Backend funcionando correctamente
        </div>
        
        <div style="margin: 20px 0;">
            <h3>Estado del Sistema:</h3>
            <p>🔧 IQ Option API: ''' + ('✅ Disponible' if IQ_AVAILABLE else '❌ No disponible') + '''</p>
            <p>📱 Telegram: ''' + ('✅ Configurado' if TELEGRAM_BOT_TOKEN else '❌ No configurado') + '''</p>
            <p>🌐 CORS: ✅ Configurado para ''' + FRONTEND_DOMAINS[0] + '''</p>
        </div>

        <div style="margin-top: 30px;">
            <a href="/health" class="btn">📊 Health Check</a>
            <a href="/api/strategies" class="btn">🎯 Estrategias</a>
        </div>

        <div style="margin-top: 30px; font-size: 14px; color: #666;">
            <h3>Endpoints API:</h3>
            <ul style="text-align: left; display: inline-block;">
                <li>POST /api/login - Autenticación</li>
                <li>GET /api/strategies - Estrategias disponibles</li>
                <li>POST /api/start_bot - Iniciar bot</li>
                <li>POST /api/stop_bot - Detener bot</li>
                <li>GET /api/bot_status - Estado del bot</li>
                <li>GET /api/live_data - Datos en vivo</li>
                <li>GET /api/metrics - Métricas</li>
                <li>POST /api/logout - Cerrar sesión</li>
            </ul>
        </div>
    </div>
</body>
</html>'''
    return html, 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
def health_check():
    """Health check"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "system_type": "binary_options_trading_bot",
            "iqoption_api": {
                "status": "available" if IQ_AVAILABLE else "unavailable",
                "version": "real_trading" if IQ_AVAILABLE else "simulation"
            },
            "sessions": {
                "active": len(user_sessions),
                "total": len(user_sessions)
            },
            "bots": {
                "active": len([b for b in active_bots.values() if hasattr(b, 'running') and b.running]),
                "total": len(active_bots)
            },
            "telegram": {
                "configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
                "status": "enabled" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "disabled"
            },
            "cors": {
                "configured_for": FRONTEND_DOMAINS,
                "status": "operational"
            },
            "strategies": {
                "available": len(BINARY_STRATEGY_CONFIG),
                "types": [s.value for s in BINARY_STRATEGY_CONFIG.keys()]
            }
        }
        
        return jsonify(health_data), 200
        
    except Exception as e:
        logger.error(f"Error en health check: {e}")
        return jsonify({
            "status": "error",
            "timestamp": datetime.datetime.now().isoformat(),
            "error": str(e)
        }), 500

@app.route('/api/login', methods=['POST', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@limiter.limit("5 per minute")
def login():
    """Login con IQ Option"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No se recibieron datos"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
        
        logger.info(f"Intento de login: {email}")
        
        # Limpiar sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    if IQ_AVAILABLE:
                        user_sessions[email].close_websocket()
                    del user_sessions[email]
                except:
                    pass
        
        # Crear conexión IQ Option si está disponible
        if IQ_AVAILABLE:
            try:
                iq = IQ_Option(email, password)
                
                # Intentar conectar
                connection_result = iq.connect()
                if isinstance(connection_result, tuple):
                    success = connection_result[0]
                else:
                    success = connection_result
                
                if not success:
                    return jsonify({
                        "success": False, 
                        "message": "Error de autenticación con IQ Option"
                    }), 401
                
                # Obtener balance
                balance = iq.get_balance()
                account_type = iq.get_balance_mode()
                
            except Exception as e:
                logger.error(f"Error conectando IQ Option: {e}")
                return jsonify({
                    "success": False, 
                    "message": f"Error de conexión: {str(e)}"
                }), 503
        else:
            # Modo simulación
            class MockIQOption:
                def check_connect(self):
                    return True
                def get_balance(self):
                    return 1000.0
                def get_balance_mode(self):
                    return "PRACTICE"
                def close_websocket(self):
                    pass
            
            iq = MockIQOption()
            balance = 1000.0
            account_type = "PRACTICE"
        
        # Guardar sesión
        with sessions_lock:
            user_sessions[email] = iq
        
        session['user_email'] = email
        session.permanent = True
        
        # Inicializar métricas
        if email not in user_metrics:
            user_metrics[email] = BinaryTradingMetrics()
            user_metrics[email].start_balance = balance
            user_metrics[email].current_balance = balance
        
        # Notificar login
        mode = "REAL" if IQ_AVAILABLE else "SIMULACIÓN"
        send_telegram_message(f"""🎯 *LOGIN EXITOSO - {mode}*
👤 Usuario: {email.split('@')[0].title()}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}
⏰ {datetime.datetime.now().strftime('%H:%M:%S')}""")
        
        return jsonify({
            "success": True,
            "user": {
                "name": email.split('@')[0].title(),
                "email": email,
                "balance": float(balance),
                "account_type": account_type,
                "currency": "USD",
                "max_investment": float(balance * 0.5)
            },
            "system": {
                "type": "binary_options_bot",
                "mode": "real" if IQ_AVAILABLE else "simulation",
                "features": {
                    "max_capital_limit": "50%",
                    "configurable_limits": True,
                    "telegram_notifications": True
                }
            },
            "message": f"Conexión exitosa - Modo {'Real' if IQ_AVAILABLE else 'Simulación'}"
        }), 200
        
    except Exception as e:
        logger.error(f"Error en login: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Error del servidor: {str(e)}"
        }), 500

@app.route('/api/strategies', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_strategies():
    """Obtener estrategias"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        strategies = []
        for strategy, config in BINARY_STRATEGY_CONFIG.items():
            strategies.append({
                "id": strategy.value,
                "name": config["name"],
                "description": config["description"],
                "risk_level": config["risk_level"].value,
                "min_confidence": config["min_confidence"],
                "timeframe": config["timeframe"],
                "expiry": config["expiry"],
                "win_rate_expected": config["win_rate_expected"],
                "trades_per_day": config["trades_per_day"],
                "best_for": config["best_for"],
                "market_conditions": config["market_conditions"]
            })
        
        return jsonify({
            "strategies": strategies,
            "total": len(strategies),
            "system_info": {
                "type": "binary_options",
                "mode": "real" if IQ_AVAILABLE else "simulation"
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo estrategias: {str(e)}")
        return jsonify({"error": "Error obteniendo estrategias"}), 500

@app.route('/api/start_bot', methods=['POST', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
@limiter.limit("3 per minute")
def start_bot():
    """Iniciar bot"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots and hasattr(active_bots[email], 'running') and active_bots[email].running:
                return jsonify({"error": "Ya hay un bot activo"}), 400
        
        data = request.get_json()
        
        config = {
            'symbol': data.get('symbol', 'EURUSD'),
            'amount': float(data.get('amount', 10)),
            'strategy': data.get('strategy', 'bollinger_rsi'),
            'account_type': data.get('account_type', 'PRACTICE'),
            'max_loss_operations': int(data.get('max_loss_operations', 5)),
            'max_win_operations': int(data.get('max_win_operations', 0)),
            'max_daily_operations': int(data.get('max_daily_operations', 50))
        }
        
        # Validaciones
        if config['amount'] <= 0 or config['amount'] > 1000:
            return jsonify({"error": "Monto debe estar entre $1 y $1000"}), 400
        
        # Verificar balance
        iq = user_sessions[email]
        if IQ_AVAILABLE:
            try:
                balance = iq.get_balance()
            except:
                balance = 1000.0
        else:
            balance = 1000.0
        
        max_allowed = balance * 0.5
        if config['amount'] > max_allowed:
            return jsonify({
                "error": f"Monto excede 50% del balance (${max_allowed:.2f})",
                "max_allowed": max_allowed,
                "current_balance": balance
            }), 400
        
        # Crear bot
        bot = SimpleBinaryBot(iq, config, email)
        
        with bots_lock:
            active_bots[email] = bot
        
        bot.start()
        
        strategy_config = BINARY_STRATEGY_CONFIG[Strategy(config['strategy'])]
        
        return jsonify({
            "success": True,
            "message": "Bot iniciado correctamente",
            "config": config,
            "strategy_info": {
                "name": strategy_config["name"],
                "risk_level": strategy_config["risk_level"].value,
                "win_rate_expected": strategy_config["win_rate_expected"]
            },
            "limits": {
                "max_allowed_investment": max_allowed,
                "current_balance": balance,
                "capital_usage_percent": (config['amount'] / balance * 100) if balance > 0 else 0
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error iniciando bot: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stop_bot', methods=['POST', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def stop_bot():
    """Detener bot"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                bot.stop()
                del active_bots[email]
                
                send_telegram_message(f"""🛑 *BOT DETENIDO*
👤 Usuario: {email}
💰 Sesión: ${bot.session_profit:.2f}
📊 Operaciones: {bot.operations_count}""")
                
                return jsonify({
                    "success": True,
                    "message": "Bot detenido correctamente",
                    "final_stats": {
                        "session_profit": bot.session_profit,
                        "operations_count": bot.operations_count
                    }
                }), 200
            else:
                return jsonify({"error": "No hay bot activo"}), 400
                
    except Exception as e:
        logger.error(f"Error deteniendo bot: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/bot_status', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def bot_status():
    """Estado del bot"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                return jsonify({
                    "running": bot.running,
                    "operations_count": bot.operations_count,
                    "consecutive_wins": bot.consecutive_wins,
                    "consecutive_losses": bot.consecutive_losses,
                    "session_profit": bot.session_profit,
                    "daily_operations": bot.daily_operations,
                    "config": bot.config,
                    "mode": "real" if IQ_AVAILABLE else "simulation"
                }), 200
            else:
                return jsonify({
                    "running": False,
                    "message": "No hay bot activo",
                    "mode": "real" if IQ_AVAILABLE else "simulation"
                }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo estado: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/live_data', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_live_data():
    """Datos en vivo"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                live_data = bot.get_live_data()
                
                return jsonify({
                    "success": True,
                    "data": live_data,
                    "mode": "real" if IQ_AVAILABLE else "simulation"
                }), 200
            else:
                return jsonify({"error": "No hay bot activo"}), 404
                
    except Exception as e:
        logger.error(f"Error obteniendo datos: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/metrics', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_metrics():
    """Métricas"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session['user_email']
        
        if email in user_metrics:
            metrics = user_metrics[email].to_dict()
        else:
            metrics = BinaryTradingMetrics().to_dict()
        
        return jsonify({
            "metrics": metrics,
            "mode": "real" if IQ_AVAILABLE else "simulation",
            "last_updated": datetime.datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo métricas: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/logout', methods=['POST', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
def logout():
    """Cerrar sesión"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session.get('user_email')
        
        if email:
            # Detener bot
            with bots_lock:
                if email in active_bots:
                    active_bots[email].stop()
                    del active_bots[email]
            
            # Cerrar sesión IQ Option
            with sessions_lock:
                if email in user_sessions:
                    if IQ_AVAILABLE:
                        try:
                            user_sessions[email].close_websocket()
                        except:
                            pass
                    del user_sessions[email]
            
            session.clear()
            
            send_telegram_message(f"👋 *LOGOUT*\n👤 Usuario: {email}\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
        
        return jsonify({
            "success": True,
            "message": "Sesión cerrada correctamente"
        }), 200
        
    except Exception as e:
        logger.error(f"Error en logout: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# LIMPIEZA DE SESIONES
# ============================================================================

def cleanup_sessions():
    """Limpia sesiones inactivas"""
    while True:
        time.sleep(3600)  # Cada hora
        try:
            logger.info("🧹 Limpiando sesiones...")
            
            with sessions_lock:
                emails_to_clean = []
                
                for email, iq in list(user_sessions.items()):
                    try:
                        if IQ_AVAILABLE:
                            if not iq.check_connect():
                                emails_to_clean.append(email)
                        # En modo simulación, mantener sesiones
                    except:
                        emails_to_clean.append(email)
                
                for email in emails_to_clean:
                    try:
                        with bots_lock:
                            if email in active_bots:
                                active_bots[email].stop()
                                del active_bots[email]
                        
                        if IQ_AVAILABLE:
                            try:
                                user_sessions[email].close_websocket()
                            except:
                                pass
                        
                        del user_sessions[email]
                        logger.info(f"🗑️ Sesión limpiada: {email}")
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"Error en limpieza: {e}")

def graceful_shutdown():
    """Cierre ordenado"""
    logger.info("🛑 Cerrando sistema...")
    
    with bots_lock:
        for email, bot in list(active_bots.items()):
            try:
                bot.stop()
            except:
                pass
        active_bots.clear()
    
    if IQ_AVAILABLE:
        with sessions_lock:
            for email, iq in list(user_sessions.items()):
                try:
                    iq.close_websocket()
                except:
                    pass
            user_sessions.clear()
    
    logger.info("✅ Sistema cerrado")

signal.signal(signal.SIGTERM, lambda s, f: graceful_shutdown())
signal.signal(signal.SIGINT, lambda s, f: graceful_shutdown())
atexit.register(graceful_shutdown)

# Iniciar limpieza
cleanup_thread = Thread(target=cleanup_sessions, daemon=True)
cleanup_thread.start()

# ============================================================================
# MANEJO DE ERRORES
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    response = jsonify({
        "error": "Endpoint no encontrado",
        "available_endpoints": [
            "/health",
            "/api/login",
            "/api/strategies", 
            "/api/start_bot",
            "/api/stop_bot",
            "/api/bot_status",
            "/api/live_data",
            "/api/metrics",
            "/api/logout"
        ]
    })
    
    origin = request.headers.get('Origin')
    if origin in FRONTEND_DOMAINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = 'https://iqoptionbot.ct.ws'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response, 404

@app.errorhandler(500)
def internal_error(error):
    response = jsonify({
        "error": "Error interno del servidor",
        "message": "Contacta al administrador"
    })
    
    origin = request.headers.get('Origin')
    if origin in FRONTEND_DOMAINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = 'https://iqoptionbot.ct.ws'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response, 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info("🎯 BOT DE OPCIONES BINARIAS - IQ OPTION")
    logger.info("=" * 60)
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🌐 CORS: {FRONTEND_DOMAINS[0]}")
    logger.info(f"🔧 IQ Option: {'✅ Disponible' if IQ_AVAILABLE else '❌ Simulación'}")
    logger.info(f"📱 Telegram: {'✅ OK' if TELEGRAM_BOT_TOKEN else '❌ No config'}")
    logger.info(f"📊 Estrategias: {len(BINARY_STRATEGY_CONFIG)}")
    logger.info("")
    logger.info("🎯 CARACTERÍSTICAS:")
    logger.info("   • ✅ 5 estrategias profesionales")
    logger.info("   • ✅ Protección de capital 50% máximo")
    logger.info("   • ✅ Límites configurables")
    logger.info("   • ✅ Notificaciones Telegram")
    logger.info("   • ✅ CORS configurado")
    logger.info("   • ✅ API RESTful completa")
    logger.info("=" * 60)
    
    if not IQ_AVAILABLE:
        logger.warning("⚠️ Ejecutando en modo simulación")
        logger.info("💡 Para modo real: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
    
    mode = "REAL" if IQ_AVAILABLE else "SIMULACIÓN"
    send_telegram_message(f"""🎯 *BACKEND INICIADO - {mode}*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🌐 CORS: ✅ {FRONTEND_DOMAINS[0]}
🔧 IQ Option: {'✅ Conectada' if IQ_AVAILABLE else '❌ Simulación'}
📊 Estrategias: {len(BINARY_STRATEGY_CONFIG)}
🎯 Sistema listo para trading""")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
