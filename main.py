# main.py - Backend Trading Bot Pro v2.0 - OPTIMIZADO PARA RENDER
# Configurado específicamente para despliegue en Render.com

import os
import sys
import logging
import datetime
import time
import requests
import numpy as np
import json
import math
import signal
import atexit
from functools import wraps
from threading import Thread, Lock, Event, RLock
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum
import asyncio
from concurrent.futures import ThreadPoolExecutor

# ============================================================================
# CONFIGURACIÓN ESPECÍFICA PARA RENDER
# ============================================================================

# Variables de entorno específicas para Render
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL', 'https://your-app.onrender.com')
RENDER_INTERNAL_HOST = os.environ.get('RENDER_INTERNAL_HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', 10000))  # Render usa puerto 10000 por defecto

# Configuración de logging optimizada para Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)  # Solo stdout para Render
    ],
    force=True
)

logger = logging.getLogger(__name__)

# Configuración de paths para Render (ephemeral filesystem)
TEMP_DIR = '/tmp'
SESSION_DIR = os.path.join(TEMP_DIR, 'flask_sessions')
LOGS_DIR = os.path.join(TEMP_DIR, 'bot_logs')

# Crear directorios necesarios
os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ============================================================================
# PARCHE WEBSOCKET SIMPLIFICADO PARA RENDER
# ============================================================================

class RenderWebSocketPatcher:
    """Parchea WebSocket de forma optimizada para Render"""
    
    @staticmethod
    def apply_render_patch():
        """Aplica parche específico para Render"""
        try:
            logger.info("🔧 Aplicando parche WebSocket para Render...")
            
            import websocket
            from websocket import WebSocketApp
            
            # Parche simplificado que funciona en Render
            original_init = WebSocketApp.__init__
            
            def patched_init(self, url, **kwargs):
                # Wrapper simple para callbacks
                def safe_callback(original_callback):
                    if original_callback is None:
                        return None
                    
                    def wrapper(*args, **kwargs_inner):
                        try:
                            return original_callback(*args, **kwargs_inner)
                        except TypeError:
                            # Argumento incorrecto, usar solo el primero
                            try:
                                return original_callback(args[0] if args else None)
                            except:
                                return None
                    return wrapper
                
                # Aplicar wrapper a callbacks
                for cb_name in ['on_open', 'on_close', 'on_error', 'on_message']:
                    if cb_name in kwargs:
                        kwargs[cb_name] = safe_callback(kwargs[cb_name])
                
                return original_init(self, url, **kwargs)
            
            WebSocketApp.__init__ = patched_init
            
            logger.info("✅ Parche WebSocket para Render aplicado")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error aplicando parche: {e}")
            return False

# Aplicar parche antes de importar otras librerías
RenderWebSocketPatcher.apply_render_patch()

# ============================================================================
# IMPORTACIONES
# ============================================================================

from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, disconnect, join_room, leave_room

# Importar IQOptionAPI con manejo de errores para Render
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando IQOptionAPI: {e}")
    IQ_AVAILABLE = False
    # En Render, continuar sin IQOptionAPI para testing
    logger.warning("⚠️ Continuando sin IQOptionAPI para testing en Render")

# ============================================================================
# CONFIGURACIÓN FLASK OPTIMIZADA PARA RENDER
# ============================================================================

app = Flask(__name__)

# Configuración optimizada para Render
app.config.update({
    'SECRET_KEY': os.environ.get('SECRET_KEY', 'trading-bot-render-secret-2024'),
    'SESSION_TYPE': 'filesystem',
    'SESSION_FILE_DIR': SESSION_DIR,
    'SESSION_COOKIE_NAME': 'trading_session_render',
    'SESSION_COOKIE_SAMESITE': 'None',
    'SESSION_COOKIE_SECURE': True,  # HTTPS en Render
    'SESSION_COOKIE_HTTPONLY': True,
    'PERMANENT_SESSION_LIFETIME': 3600 * 12,  # 12 horas para Render
    'MAX_CONTENT_LENGTH': 16 * 1024 * 1024,
    'SEND_FILE_MAX_AGE_DEFAULT': 0  # Desactivar cache para desarrollo
})

# Inicializar Session
Session(app)

# CORS optimizado para Render
CORS(app, 
     resources={r"/*": {
         "origins": [
             RENDER_EXTERNAL_URL,
             "http://localhost:3000", 
             "http://localhost:3001", 
             "https://localhost:3000",
             "https://*.onrender.com",
             "https://*.netlify.app",
             "https://*.vercel.app",
             "*"  # Para desarrollo
         ],
         "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
         "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept"],
         "expose_headers": ["Content-Type", "Authorization"],
         "supports_credentials": True,
         "max_age": 3600
     }})

# SocketIO configurado para Render
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',  # Mejor para Render
    ping_timeout=120,        # Más tiempo para conexiones lentas
    ping_interval=30,        # Ping cada 30 segundos
    logger=False,
    engineio_logger=False,
    manage_session=False,
    transports=['websocket', 'polling'],  # Polling como fallback
    allow_upgrades=True
)

# Rate limiting más permisivo para Render
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["2000 per day", "500 per hour"],  # Más permisivo
    strategy="moving-window"
)

# ============================================================================
# VARIABLES GLOBALES OPTIMIZADAS PARA RENDER
# ============================================================================

# Locks simples para Render
sessions_lock = RLock()
bots_lock = RLock()
metrics_lock = RLock()

# Diccionarios con gestión optimizada para Render
user_sessions = {}
active_bots = {}
user_metrics = {}

# Pool de threads reducido para Render
thread_pool = ThreadPoolExecutor(max_workers=5, thread_name_prefix="RenderBot")

# Configuración Telegram (variables de entorno de Render)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

# ============================================================================
# CLASES Y ENUMS (SIMPLIFICADOS PARA RENDER)
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

class ConnectionStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"

# Configuración de estrategias
STRATEGY_CONFIG = {
    Strategy.BOLLINGER_RSI: {
        "name": "Bandas de Bollinger + RSI",
        "description": "Estrategia conservadora basada en sobreventa/sobrecompra",
        "risk_level": RiskLevel.LOW,
        "min_confidence": 70,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["bb", "rsi"]
    },
    Strategy.MACD_SIGNAL: {
        "name": "MACD + Señal",
        "description": "Seguimiento de tendencia con cruzamiento de señales",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 65,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["macd", "ema"]
    },
    Strategy.TRIPLE_EMA: {
        "name": "Triple EMA + Estocástico",
        "description": "Scalping rápido con múltiples confirmaciones",
        "risk_level": RiskLevel.HIGH,
        "min_confidence": 60,
        "timeframe": 60,
        "expiry": 300,
        "indicators": ["ema", "stoch"]
    },
    Strategy.STOCH_MOMENTUM: {
        "name": "Estocástico + Momentum",
        "description": "Reversión de momentum en zonas extremas",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 65,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["stoch", "rsi", "bb"]
    },
    Strategy.CCI_DYNAMIC: {
        "name": "CCI Dinámico + Bollinger",
        "description": "Volatilidad dinámica para breakouts",
        "risk_level": RiskLevel.VERY_HIGH,
        "min_confidence": 55,
        "timeframe": 300,
        "expiry": 300,
        "indicators": ["cci", "bb", "ema"]
    }
}

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

# ============================================================================
# GESTIÓN DE CONEXIONES SIMPLIFICADA PARA RENDER
# ============================================================================

class RenderConnectionManager:
    """Gestión de conexiones optimizada para Render"""
    
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.iq_instance = None
        self.status = ConnectionStatus.DISCONNECTED
        self.last_ping = 0
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3  # Reducido para Render
        self.connection_lock = RLock()
        
    def connect(self, timeout: int = 30) -> Tuple[bool, str]:
        """Conecta con timeout optimizado para Render"""
        if not IQ_AVAILABLE:
            # Modo demo para testing en Render
            logger.info(f"🧪 Modo demo para {self.email} (IQOptionAPI no disponible)")
            self.status = ConnectionStatus.CONNECTED
            return True, "Conexión demo exitosa"
        
        with self.connection_lock:
            try:
                self.status = ConnectionStatus.CONNECTING
                logger.info(f"🔄 Conectando en Render: {self.email}")
                
                # Limpiar conexión anterior
                self._cleanup_connection()
                
                # Crear nueva instancia con configuración para Render
                self.iq_instance = IQ_Option(self.email, self.password)
                
                # Configurar timeouts más largos para Render
                if hasattr(self.iq_instance, 'api'):
                    try:
                        self.iq_instance.api.timeout = timeout
                    except:
                        pass
                
                # Conectar con timeout
                result = self._connect_with_render_timeout(timeout)
                
                if result[0]:
                    self.status = ConnectionStatus.CONNECTED
                    self.reconnect_attempts = 0
                    self.last_ping = time.time()
                    logger.info(f"✅ Conectado en Render: {self.email}")
                    return True, "Conexión exitosa"
                else:
                    self.status = ConnectionStatus.FAILED
                    return False, result[1]
                    
            except Exception as e:
                self.status = ConnectionStatus.FAILED
                logger.error(f"❌ Error conectando en Render {self.email}: {e}")
                return False, f"Error de conexión: {str(e)}"
    
    def _connect_with_render_timeout(self, timeout: int) -> Tuple[bool, str]:
        """Conecta con timeout específico para Render"""
        result = {'success': False, 'reason': 'Timeout'}
        event = Event()
        
        def connect_thread():
            try:
                check, reason = self.iq_instance.connect()
                result['success'] = check
                result['reason'] = reason
            except Exception as e:
                result['success'] = False
                result['reason'] = str(e)
            finally:
                event.set()
        
        thread = Thread(target=connect_thread, daemon=True)
        thread.start()
        
        if event.wait(timeout=timeout):
            return result['success'], result['reason']
        else:
            return False, "Timeout de conexión en Render"
    
    def is_connected(self) -> bool:
        """Verifica conexión optimizada para Render"""
        if not IQ_AVAILABLE:
            return self.status == ConnectionStatus.CONNECTED
        
        try:
            if not self.iq_instance:
                return False
            
            if not self.iq_instance.check_connect():
                return False
            
            # Ping menos frecuente para Render
            current_time = time.time()
            if current_time - self.last_ping > 60:  # Cada minuto
                try:
                    balance = self.iq_instance.get_balance()
                    if balance is not None:
                        self.last_ping = current_time
                        return True
                    else:
                        return False
                except:
                    return False
            
            return True
            
        except Exception:
            return False
    
    def reconnect_if_needed(self) -> bool:
        """Reconecta si es necesario (simplificado para Render)"""
        if self.is_connected():
            return True
        
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            return False
        
        self.reconnect_attempts += 1
        logger.warning(f"🔄 Reconectando en Render {self.email} (intento {self.reconnect_attempts})")
        
        success, _ = self.connect()
        return success
    
    def _cleanup_connection(self):
        """Limpia conexión de forma segura para Render"""
        if self.iq_instance:
            try:
                if hasattr(self.iq_instance, 'close_websocket'):
                    self.iq_instance.close_websocket()
            except:
                pass
    
    def disconnect(self):
        """Desconecta de forma limpia"""
        try:
            self.status = ConnectionStatus.DISCONNECTED
            self._cleanup_connection()
            self.iq_instance = None
            logger.info(f"🔌 Desconectado en Render: {self.email}")
        except Exception as e:
            logger.error(f"Error desconectando en Render {self.email}: {e}")

# ============================================================================
# FUNCIONES AUXILIARES OPTIMIZADAS PARA RENDER
# ============================================================================

def send_telegram_message(message: str):
    """Envía mensaje a Telegram optimizado para Render"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram no configurado, saltando mensaje")
        return
    
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
            
            if response.status_code == 200:
                logger.debug("✅ Mensaje Telegram enviado")
            else:
                logger.warning(f"⚠️ Error Telegram: {response.status_code}")
                
        except Exception as e:
            logger.error(f"❌ Error enviando Telegram: {e}")
    
    # Ejecutar en thread pool para no bloquear
    try:
        thread_pool.submit(send)
    except:
        # Si el pool está lleno, ejecutar directamente
        Thread(target=send, daemon=True).start()

def require_auth(f):
    """Decorador de autenticación optimizado para Render"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
            
            connection_manager = user_sessions[email]
            
            # Verificación simplificada para Render
            if not connection_manager.reconnect_if_needed():
                logger.error(f"❌ Conexión perdida en Render para {email}")
                del user_sessions[email]
                session.clear()
                return jsonify({
                    "error": "Conexión perdida", 
                    "code": "CONNECTION_LOST"
                }), 401
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# SISTEMA DE LIMPIEZA SIMPLIFICADO PARA RENDER
# ============================================================================

class RenderConnectionKeeper:
    """Sistema de limpieza optimizado para Render"""
    
    def __init__(self):
        self.running = True
        self.cleanup_thread = None
        
    def start(self):
        """Inicia sistema de limpieza simplificado"""
        self.cleanup_thread = Thread(target=self._cleanup_loop, daemon=True, name="RenderCleaner")
        self.cleanup_thread.start()
        logger.info("🧹 Sistema de limpieza Render iniciado")
    
    def stop(self):
        self.running = False
        logger.info("🛑 Sistema de limpieza Render detenido")
    
    def _cleanup_loop(self):
        """Loop de limpieza optimizado para Render"""
        while self.running:
            try:
                time.sleep(3600)  # Cada hora
                self._cleanup_inactive_sessions()
            except Exception as e:
                logger.error(f"❌ Error en cleanup Render: {e}")
    
    def _cleanup_inactive_sessions(self):
        """Limpia sesiones optimizado para Render"""
        try:
            logger.info("🧹 Limpieza Render iniciada...")
            cleaned_count = 0
            
            with sessions_lock:
                emails_to_clean = []
                
                for email, connection_manager in list(user_sessions.items()):
                    try:
                        if not connection_manager.is_connected():
                            emails_to_clean.append(email)
                    except:
                        emails_to_clean.append(email)
                
                # Limpiar sesiones
                for email in emails_to_clean:
                    try:
                        # Detener bot
                        with bots_lock:
                            if email in active_bots:
                                active_bots[email].stop()
                                del active_bots[email]
                        
                        # Limpiar conexión
                        connection_manager = user_sessions[email]
                        connection_manager.disconnect()
                        del user_sessions[email]
                        
                        cleaned_count += 1
                        logger.info(f"🗑️ Sesión Render limpiada: {email}")
                        
                    except Exception as e:
                        logger.error(f"❌ Error limpiando {email}: {e}")
            
            if cleaned_count > 0:
                logger.info(f"✅ Limpieza Render: {cleaned_count} sesiones eliminadas")
                
        except Exception as e:
            logger.error(f"❌ Error en limpieza Render: {e}")

# Inicializar sistema de limpieza
render_keeper = RenderConnectionKeeper()

# ============================================================================
# WEBSOCKET EVENTS OPTIMIZADOS PARA RENDER
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Maneja conexión WebSocket en Render"""
    try:
        logger.info(f"🔌 Cliente conectado en Render: {request.sid}")
        emit('connected', {
            'status': 'success', 
            'message': 'Conectado al servidor Render',
            'server': 'render'
        })
    except Exception as e:
        logger.error(f"❌ Error conexión WebSocket Render: {e}")

@socketio.on('disconnect')
def handle_disconnect():
    """Maneja desconexión WebSocket en Render"""
    try:
        logger.info(f"🔌 Cliente desconectado en Render: {request.sid}")
    except Exception as e:
        logger.error(f"❌ Error desconexión WebSocket Render: {e}")

@socketio.on('join_user_room')
def handle_join_user_room(data):
    """Une al cliente a su room en Render"""
    try:
        if 'user_email' not in session:
            emit('error', {'message': 'No autenticado'})
            return
        
        email = session['user_email']
        room = f"user_{email}"
        
        join_room(room)
        logger.info(f"👤 Usuario Render {email} unido a room: {room}")
        
        emit('joined_room', {
            'room': room, 
            'email': email,
            'server': 'render'
        })
        
    except Exception as e:
        logger.error(f"❌ Error uniendo a room Render: {e}")
        emit('error', {'message': 'Error uniéndose a room'})

# ============================================================================
# ENDPOINTS OPTIMIZADOS PARA RENDER
# ============================================================================

@app.after_request
def after_request(response):
    """Headers CORS optimizados para Render"""
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept'
    
    # Headers de seguridad para Render
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    return response

@app.route('/', methods=['GET'])
def serve_frontend():
    """Frontend optimizado para Render"""
    frontend_html = f'''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Pro v2.0 - Render Deployment</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }}
        .container {{
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.15);
            text-align: center;
            max-width: 900px;
            width: 100%;
            backdrop-filter: blur(10px);
        }}
        .logo {{
            font-size: 64px;
            margin-bottom: 20px;
            animation: pulse 2s ease-in-out infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.05); }}
        }}
        h1 {{
            color: #333;
            margin-bottom: 20px;
            font-size: 2.5em;
        }}
        .render-badge {{
            background: linear-gradient(45deg, #00d2ff, #3a7bd5);
            color: white;
            padding: 10px 20px;
            border-radius: 25px;
            font-size: 1.1em;
            display: inline-block;
            margin: 20px 0;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }}
        .status {{
            background: linear-gradient(45deg, #d4edda, #c3e6cb);
            color: #155724;
            padding: 20px;
            border-radius: 15px;
            margin: 20px 0;
            border: 2px solid #c3e6cb;
        }}
        .info {{
            background: rgba(248, 249, 250, 0.9);
            padding: 30px;
            border-radius: 15px;
            margin: 30px 0;
            text-align: left;
        }}
        .btn {{
            background: linear-gradient(45deg, #007bff, #0056b3);
            color: white;
            padding: 15px 30px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            margin: 15px;
            transition: all 0.3s ease;
        }}
        .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 16px rgba(0,0,0,0.3);
        }}
        .render-features {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 40px 0;
        }}
        .feature {{
            background: rgba(248, 249, 250, 0.9);
            padding: 25px;
            border-radius: 15px;
            border-left: 6px solid #00d2ff;
            transition: transform 0.3s ease;
        }}
        .feature:hover {{
            transform: translateY(-5px);
        }}
        .render-info {{
            background: linear-gradient(45deg, #667eea, #764ba2);
            color: white;
            padding: 25px;
            border-radius: 15px;
            margin: 30px 0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🚀</div>
        <h1>Trading Bot Pro v2.0</h1>
        <div class="render-badge">
            🌐 Desplegado en Render.com
        </div>
        
        <div class="status">
            ✅ Servidor Render activo y funcionando correctamente
        </div>
        
        <div class="render-info">
            <h3>🌐 Configuración Render</h3>
            <p><strong>URL del Servidor:</strong> {RENDER_EXTERNAL_URL}</p>
            <p><strong>Puerto:</strong> {PORT}</p>
            <p><strong>WebSocket:
