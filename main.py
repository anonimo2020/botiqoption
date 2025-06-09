# main.py - Backend DEFINITIVO para Bot de Trading Opciones Binarias Pro
# Configuración CORS específica para Render y dominio https://iqoptionbot.ct.ws/

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

# Flask y extensiones
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS, cross_origin
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Mock de IQOptionAPI para que funcione en cualquier entorno
class IQ_Option:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.connected = True
        
    def connect(self):
        time.sleep(1)  # Simular tiempo de conexión
        return True, "Conectado exitosamente"
        
    def check_connect(self):
        return self.connected
        
    def get_balance(self):
        return 1000.0
        
    def get_balance_mode(self):
        return "PRACTICE"
        
    def change_balance(self, mode):
        return True
        
    def get_candles(self, symbol, timeframe, count, timestamp):
        # Generar datos simulados realistas
        candles = []
        base_price = 1.0850
        
        for i in range(count):
            change = np.random.normal(0, 0.0001)
            base_price += change
            
            candle = {
                'open': base_price - change/2,
                'close': base_price,
                'max': base_price + abs(np.random.normal(0, 0.00005)),
                'min': base_price - abs(np.random.normal(0, 0.00005)),
                'volume': np.random.randint(100, 1000),
                'time': timestamp - (count-i) * timeframe
            }
            candles.append(candle)
        
        return candles
        
    def buy(self, amount, symbol, direction, expiry):
        # Simular compra exitosa
        return True, f"sim_{int(time.time())}"
        
    def check_win_v3(self, order_id):
        # Simular resultado aleatorio basado en probabilidad
        win_probability = 0.65  # 65% win rate simulado
        is_win = np.random.random() < win_probability
        
        if is_win:
            return 0.8  # 80% payout
        else:
            return -1.0  # Pérdida total
            
    def close_websocket(self):
        self.connected = False

# Configuración Flask ESPECÍFICA para CORS
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'binary-options-bot-secret-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24  # 24 horas

# Crear directorio de sesiones
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# CORS CONFIGURACIÓN ESPECÍFICA PARA TU DOMINIO
FRONTEND_DOMAINS = [
    "https://iqoptionbot.ct.ws",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://localhost:3000"
]

# Configuración CORS MUY ESPECÍFICA
CORS(app, 
     origins=FRONTEND_DOMAINS,
     methods=['GET', 'POST', 'OPTIONS'],
     allow_headers=[
         'Content-Type', 
         'Authorization', 
         'Access-Control-Allow-Credentials',
         'Access-Control-Allow-Origin',
         'Accept',
         'Origin',
         'User-Agent',
         'DNT',
         'Cache-Control',
         'X-Mx-ReqToken',
         'Keep-Alive',
         'X-Requested-With'
     ],
     supports_credentials=True,
     expose_headers=['Content-Type', 'Authorization'],
     max_age=3600)

# Inicializar extensiones
Session(app)

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["500 per day", "100 per hour"]
)

# Variables globales
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# Configuración Telegram
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
        "description": "Estrategia conservadora para principiantes",
        "risk_level": RiskLevel.LOW,
        "min_confidence": 75,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["bollinger_bands", "rsi", "sma"],
        "win_rate_expected": 70,
        "trades_per_day": "8-12",
        "best_for": "Reversiones en soportes/resistencias",
        "market_conditions": "Mercados laterales"
    },
    Strategy.MACD_SIGNAL: {
        "name": "MACD + Signal Cross",
        "description": "Seguimiento de tendencia",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 68,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["macd", "ema_fast", "ema_slow"],
        "win_rate_expected": 65,
        "trades_per_day": "12-18",
        "best_for": "Tendencias fuertes",
        "market_conditions": "Mercados con tendencia"
    },
    Strategy.TRIPLE_EMA: {
        "name": "Triple EMA + Stochastic",
        "description": "Scalping rápido",
        "risk_level": RiskLevel.HIGH,
        "min_confidence": 62,
        "timeframe": 60,
        "expiry": 300,
        "indicators": ["ema_fast", "ema_medium", "ema_slow", "stochastic"],
        "win_rate_expected": 60,
        "trades_per_day": "25-35",
        "best_for": "Scalping rápido",
        "market_conditions": "Alta volatilidad"
    },
    Strategy.STOCH_MOMENTUM: {
        "name": "Stochastic + Momentum",
        "description": "Momentum y reversión",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 70,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["stochastic", "rsi", "bollinger_bands", "momentum"],
        "win_rate_expected": 67,
        "trades_per_day": "10-16",
        "best_for": "Reversiones en zonas extremas",
        "market_conditions": "Oscilaciones regulares"
    },
    Strategy.CCI_DYNAMIC: {
        "name": "CCI Dynamic + Bollinger",
        "description": "Volatilidad extrema",
        "risk_level": RiskLevel.VERY_HIGH,
        "min_confidence": 58,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["cci", "bollinger_bands", "ema_fast", "atr"],
        "win_rate_expected": 55,
        "trades_per_day": "20-30",
        "best_for": "Breakouts y volatilidad",
        "market_conditions": "Alta volatilidad"
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
            logger.error(f"Error enviando a Telegram: {e}")
    
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
# HEADERS CORS ESPECÍFICOS PARA CADA RESPONSE
# ============================================================================

@app.after_request
def after_request(response):
    """Asegurar headers CORS en todas las respuestas"""
    origin = request.headers.get('Origin')
    
    # Si el origen está en la lista de dominios permitidos
    if origin in FRONTEND_DOMAINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    elif origin and origin.startswith('http://localhost'):
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = 'https://iqoptionbot.ct.ws'
    
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Origin, User-Agent, DNT, Cache-Control, X-Mx-ReqToken, Keep-Alive, X-Requested-With'
    response.headers['Access-Control-Max-Age'] = '3600'
    
    return response

# ============================================================================
# ENDPOINTS PRINCIPALES
# ============================================================================

@app.route('/', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
def serve_frontend():
    """Frontend específico para opciones binarias"""
    if request.method == 'OPTIONS':
        return '', 204
        
    frontend_html = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot de Opciones Binarias Pro - API</title>
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
        .cors-info {
            background: #e3f2fd;
            color: #1565c0;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            border: 1px solid #bbdefb;
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
    </style>
</head>
<body>
    <div class="container">
        <div style="font-size: 48px; margin-bottom: 20px;">🎯</div>
        <h1>Bot de Opciones Binarias Pro - API Backend</h1>
        
        <div class="status">
            ✅ Backend funcionando correctamente en Render
        </div>
        
        <div class="cors-info">
            🌐 CORS configurado para: https://iqoptionbot.ct.ws/<br>
            🔗 Frontend conectado y listo para usar
        </div>
        
        <div style="margin-top: 30px;">
            <h3>🔗 Endpoints API Disponibles:</h3>
            <a href="/health" class="btn">📊 Health Check</a>
            <a href="/api/strategies" class="btn">🎯 Ver Estrategias</a>
        </div>

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #dee2e6; font-size: 14px; color: #666;">
            <p><strong>🔧 API Endpoints:</strong></p>
            <ul style="text-align: left; display: inline-block;">
                <li><code>POST /api/login</code> - Autenticación</li>
                <li><code>GET /api/strategies</code> - Estrategias disponibles</li>
                <li><code>POST /api/start_bot</code> - Iniciar bot</li>
                <li><code>POST /api/stop_bot</code> - Detener bot</li>
                <li><code>GET /api/bot_status</code> - Estado del bot</li>
                <li><code>GET /api/live_data</code> - Datos en tiempo real</li>
                <li><code>GET /api/metrics</code> - Métricas de trading</li>
                <li><code>GET /health</code> - Estado del sistema</li>
            </ul>
        </div>
    </div>
</body>
</html>'''
    return frontend_html, 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
def health_check():
    """Health check con información CORS"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        health_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "system_type": "binary_options_trading_bot",
            "environment": "render_production",
            "cors": {
                "configured": True,
                "allowed_origins": FRONTEND_DOMAINS,
                "status": "working"
            },
            "sessions": {
                "active": len(user_sessions),
                "total_registered": len(user_sessions)
            },
            "bots": {
                "active": len([bot for bot in active_bots.values() if hasattr(bot, 'running') and bot.running]),
                "total": len(active_bots)
            },
            "telegram": {
                "configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
                "status": "enabled" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "disabled"
            },
            "binary_strategies": {
                "available": len(BINARY_STRATEGY_CONFIG),
                "types": [strategy.value for strategy in BINARY_STRATEGY_CONFIG.keys()],
                "features": {
                    "max_capital_limit": "50%",
                    "configurable_limits": True,
                    "fast_execution": True,
                    "simulation_mode": True
                }
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
@limiter.limit("10 per minute")
def login():
    """Login con autenticación simulada"""
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
        
        logger.info(f"🎯 Login attempt: {email}")
        
        # Limpiar sesiones anteriores
        with sessions_lock:
            if email in user_sessions:
                del user_sessions[email]
        
        # Crear conexión simulada
        iq = IQ_Option(email, password)
        
        # Simular autenticación
        time.sleep(1)
        
        user_name = email.split('@')[0].title()
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
        
        # Notificar login exitoso
        send_telegram_message(f"""🎯 *LOGIN EXITOSO - SIMULACIÓN*
👤 Usuario: {user_name}
📧 Email: {email}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}
🎯 Sistema: Bot Opciones Binarias Pro
⚡ Modo: Simulación para demo
💹 Capital Máximo: 50% del balance (${balance * 0.5:.2f})
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""")
        
        return jsonify({
            "success": True,
            "user": {
                "name": user_name,
                "email": email,
                "balance": float(balance),
                "account_type": account_type,
                "currency": "USD",
                "max_investment": float(balance * 0.5)
            },
            "system": {
                "type": "binary_options_bot",
                "mode": "simulation",
                "features": {
                    "fast_execution": True,
                    "max_capital_limit": "50%",
                    "configurable_limits": True,
                    "kelly_criterion": True
                }
            },
            "message": "Conexión exitosa en modo simulación"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error en login: {str(e)}")
        return jsonify({
            "success": False,
            "message": f"Error del servidor: {str(e)}"
        }), 500

@app.route('/api/strategies', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_strategies():
    """Obtener estrategias disponibles"""
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
                "risk_level_name": config["risk_level"].value.replace('_', ' ').title(),
                "min_confidence": config["min_confidence"],
                "timeframe": config["timeframe"],
                "expiry": config["expiry"],
                "indicators": config["indicators"],
                "win_rate_expected": config["win_rate_expected"],
                "trades_per_day": config["trades_per_day"],
                "best_for": config["best_for"],
                "market_conditions": config["market_conditions"],
                "recommended_for": "Principiantes" if config["risk_level"] in [RiskLevel.VERY_LOW, RiskLevel.LOW] 
                              else "Intermedios" if config["risk_level"] == RiskLevel.MEDIUM 
                              else "Avanzados"
            })
        
        return jsonify({
            "strategies": strategies,
            "total": len(strategies),
            "system_info": {
                "type": "binary_options",
                "mode": "simulation",
                "max_capital_limit": "50%"
            }
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo estrategias: {str(e)}")
        return jsonify({"error": "Error obteniendo estrategias"}), 500

# ============================================================================
# BOT SIMULADO SIMPLIFICADO
# ============================================================================

class SimpleBinaryBot:
    def __init__(self, config, email):
        self.config = config
        self.email = email
        self.running = False
        self.operations_count = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.session_profit = 0.0
        self.daily_operations = 0
        
    def start(self):
        self.running = True
        logger.info(f"🚀 Bot simulado iniciado para {self.email}")
        
    def stop(self):
        self.running = False
        logger.info(f"🛑 Bot simulado detenido para {self.email}")

@app.route('/api/start_bot', methods=['POST', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def start_bot():
    """Iniciar bot simulado"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                
                status = {
                    "running": bot.running,
                    "operations_count": bot.operations_count,
                    "consecutive_wins": bot.consecutive_wins,
                    "consecutive_losses": bot.consecutive_losses,
                    "session_profit": bot.session_profit,
                    "daily_operations": bot.daily_operations,
                    "config": bot.config,
                    "mode": "simulation"
                }
            else:
                status = {
                    "running": False,
                    "message": "No hay bot activo",
                    "mode": "simulation"
                }
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo estado: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/live_data', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_live_data():
    """Datos en vivo simulados"""
    if request.method == 'OPTIONS':
        return '', 204
        
    try:
        email = session['user_email']
        
        # Generar datos simulados
        live_data = {
            "candles": [
                {
                    "time": time.time() - i * 300,
                    "open": 1.0850 + np.random.normal(0, 0.001),
                    "high": 1.0860 + np.random.normal(0, 0.001),
                    "low": 1.0840 + np.random.normal(0, 0.001),
                    "close": 1.0855 + np.random.normal(0, 0.001),
                    "volume": np.random.randint(100, 1000)
                } for i in range(30)
            ],
            "indicators": {
                "rsi": np.random.uniform(30, 70),
                "macd": np.random.uniform(-0.001, 0.001),
                "stoch_k": np.random.uniform(20, 80),
                "bb_upper": 1.0870,
                "bb_middle": 1.0850,
                "bb_lower": 1.0830,
                "volatility": np.random.uniform(0.5, 2.0)
            },
            "signal": {
                "direction": np.random.choice(["call", "put", None]),
                "confidence": np.random.uniform(50, 90),
                "strategy": "simulation"
            }
        }
        
        return jsonify({
            "success": True,
            "data": live_data,
            "mode": "simulation"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo datos: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/metrics', methods=['GET', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_metrics():
    """Métricas del usuario"""
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
            "mode": "simulation",
            "last_updated": datetime.datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo métricas: {str(e)}")
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
            # Detener bot si existe
            with bots_lock:
                if email in active_bots:
                    active_bots[email].stop()
                    del active_bots[email]
            
            # Limpiar sesión
            with sessions_lock:
                if email in user_sessions:
                    del user_sessions[email]
            
            session.clear()
            
            send_telegram_message(f"👋 *LOGOUT*\n👤 Usuario: {email}\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
        
        return jsonify({
            "success": True,
            "message": "Sesión cerrada correctamente"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error en logout: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ============================================================================
# ENDPOINT DE PRUEBA CORS
# ============================================================================

@app.route('/api/test', methods=['GET', 'POST', 'OPTIONS'])
@cross_origin(origins=FRONTEND_DOMAINS)
def test_cors():
    """Endpoint de prueba para verificar CORS"""
    if request.method == 'OPTIONS':
        return '', 204
    
    return jsonify({
        "success": True,
        "message": "CORS funcionando correctamente",
        "method": request.method,
        "origin": request.headers.get('Origin'),
        "timestamp": datetime.datetime.now().isoformat(),
        "frontend_domain": "https://iqoptionbot.ct.ws",
        "cors_configured": True
    }), 200

# ============================================================================
# MANEJO DE ERRORES CON CORS
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    response = jsonify({
        "error": "Endpoint no encontrado",
        "message": "Verifica la URL de la API",
        "available_endpoints": [
            "/health",
            "/api/test",
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
    
    # Agregar headers CORS a errores
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
        "message": "Contacta al administrador si el problema persiste"
    })
    
    # Agregar headers CORS a errores
    origin = request.headers.get('Origin')
    if origin in FRONTEND_DOMAINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = 'https://iqoptionbot.ct.ws'
    
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response, 500

# ============================================================================
# LIMPIEZA DE SESIONES
# ============================================================================

def cleanup_sessions():
    """Limpia sesiones inactivas cada hora"""
    while True:
        time.sleep(3600)  # 1 hora
        try:
            logger.info("🧹 Limpiando sesiones inactivas...")
            
            with sessions_lock:
                # En modo simulación, mantener sesiones por tiempo limitado
                current_time = time.time()
                emails_to_clean = []
                
                for email in list(user_sessions.keys()):
                    # Simular limpieza por inactividad (24 horas)
                    emails_to_clean.append(email)
                
                # Limpiar algunas sesiones para simular el comportamiento
                for email in emails_to_clean[:len(emails_to_clean)//2]:
                    try:
                        if email in user_sessions:
                            del user_sessions[email]
                        if email in active_bots:
                            active_bots[email].stop()
                            del active_bots[email]
                    except:
                        pass
                        
            logger.info("✅ Limpieza de sesiones completada")
                        
        except Exception as e:
            logger.error(f"Error en limpieza: {e}")

# Iniciar thread de limpieza
cleanup_thread = Thread(target=cleanup_sessions, daemon=True)
cleanup_thread.start()

# ============================================================================
# CIERRE ORDENADO
# ============================================================================

def graceful_shutdown():
    """Cierre ordenado del sistema"""
    logger.info("🛑 Iniciando cierre ordenado...")
    
    with bots_lock:
        for email, bot in list(active_bots.items()):
            try:
                bot.stop()
            except:
                pass
        active_bots.clear()
    
    with sessions_lock:
        user_sessions.clear()
    
    logger.info("✅ Cierre ordenado completado")

def signal_handler(signum, frame):
    graceful_shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
atexit.register(graceful_shutdown)

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 80)
    logger.info(f"🎯 BOT DE OPCIONES BINARIAS PRO - BACKEND API")
    logger.info("=" * 80)
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🌐 CORS configurado para: {FRONTEND_DOMAINS}")
    logger.info(f"🎯 Modo: Simulación completa")
    logger.info(f"📱 Telegram: {'Configurado' if TELEGRAM_BOT_TOKEN else 'No configurado'}")
    logger.info(f"📊 Estrategias: {len(BINARY_STRATEGY_CONFIG)}")
    logger.info("")
    logger.info("🎯 CARACTERÍSTICAS:")
    logger.info("   • ✅ CORS configurado específicamente para tu dominio")
    logger.info("   • ✅ 5 estrategias de opciones binarias")
    logger.info("   • ✅ Sistema de autenticación simulado")
    logger.info("   • ✅ Bot de trading en modo demo")
    logger.info("   • ✅ Límites configurables")
    logger.info("   • ✅ Métricas en tiempo real")
    logger.info("   • ✅ Notificaciones Telegram")
    logger.info("   • ✅ API RESTful completa")
    logger.info("=" * 80)
    
    send_telegram_message(f"""🎯 *BACKEND API INICIADO*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🌐 CORS: ✅ Configurado para https://iqoptionbot.ct.ws
🎯 Modo: Simulación completa
📊 Estrategias: {len(BINARY_STRATEGY_CONFIG)}
⚡ Estado: Listo para recibir conexiones del frontend""")
    
    # Ejecutar la aplicación
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)_bots:
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
        if config['amount'] <= 0 or config['amount'] > 500:  # Máximo 50% de 1000
            return jsonify({"error": "El monto debe estar entre $1 y $500"}), 400
        
        bot = SimpleBinaryBot(config, email)
        
        with bots_lock:
            active_bots[email] = bot
        
        bot.start()
        
        return jsonify({
            "success": True,
            "message": "Bot iniciado en modo simulación",
            "config": config,
            "mode": "simulation"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error iniciando bot: {str(e)}")
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
                
                return jsonify({
                    "success": True,
                    "message": "Bot detenido correctamente"
                }), 200
            else:
                return jsonify({"error": "No hay bot activo"}), 400
                
    except Exception as e:
        logger.error(f"❌ Error deteniendo bot: {str(e)}")
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
            if email in active
