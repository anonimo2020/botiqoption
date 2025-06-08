#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Trading Bot Pro - Opciones Binarias Optimizado
Sistema automatizado especializado en opciones binarias con 5 estrategias clasificadas por riesgo
"""

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
import signal
import atexit

# Configuración de logging optimizada para Render
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/tmp/trading_bot.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# Suprimir logs problemáticos de websocket e IQOptionAPI
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('websocket').setLevel(logging.WARNING)
logging.getLogger('iqoptionapi.ws.client').setLevel(logging.WARNING)
logging.getLogger('iqoptionapi').setLevel(logging.WARNING)

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
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'trading-bot-binary-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_COOKIE_NAME'] = 'binary_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24

os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

Session(app)

# CORS configuración
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
user_sessions = {}
active_bots = {}
sessions_lock = Lock()
bots_lock = Lock()

# Configuración Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# ESTRATEGIAS DE OPCIONES BINARIAS CLASIFICADAS POR RIESGO

class BinaryStrategy:
    def __init__(self, name, risk_level, description, min_confidence=70, timeframe=1):
        self.name = name
        self.risk_level = risk_level  # 'LOW', 'MEDIUM', 'HIGH'
        self.description = description
        self.min_confidence = min_confidence
        self.timeframe = timeframe  # minutos para expiración
        
    def get_signal(self, indicators):
        raise NotImplementedError("Cada estrategia debe implementar get_signal")
    
    def get_risk_color(self):
        colors = {
            'LOW': '#10b981',      # Verde
            'MEDIUM': '#f59e0b',   # Amarillo
            'HIGH': '#ef4444'      # Rojo
        }
        return colors.get(self.risk_level, '#6366f1')

# 1. ESTRATEGIA CONSERVADORA - RSI + BOLLINGER BANDS (BAJO RIESGO)
class RSIBollingerStrategy(BinaryStrategy):
    def __init__(self):
        super().__init__(
            name="RSI + Bollinger Bands",
            risk_level="LOW", 
            description="Combina RSI sobrecomprado/sobrevendido con bandas de Bollinger para señales conservadoras",
            min_confidence=75,
            timeframe=5  # 5 minutos
        )
    
    def get_signal(self, indicators):
        try:
            rsi = indicators.get('rsi', 50)
            price = indicators.get('price', 0)
            bb_upper = indicators.get('bb_upper', 0)
            bb_lower = indicators.get('bb_lower', 0)
            
            confidence = 0
            direction = None
            
            # Señal CALL: RSI sobreventa + precio cerca banda inferior
            if rsi <= 30 and price <= bb_lower * 1.001:  # 0.1% tolerancia
                direction = "call"
                confidence = 85 if rsi <= 25 else 75
                
            # Señal PUT: RSI sobrecompra + precio cerca banda superior  
            elif rsi >= 70 and price >= bb_upper * 0.999:  # 0.1% tolerancia
                direction = "put"
                confidence = 85 if rsi >= 75 else 75
            
            return direction, confidence, {
                "strategy": self.name,
                "rsi": rsi,
                "price_vs_bb_upper": round((price / bb_upper - 1) * 100, 2),
                "price_vs_bb_lower": round((price / bb_lower - 1) * 100, 2)
            }
            
        except Exception as e:
            logger.error(f"Error en RSIBollingerStrategy: {e}")
            return None, 0, {}

# 2. ESTRATEGIA EQUILIBRADA - MACD + SMA (RIESGO MEDIO)
class MACDSMAStrategy(BinaryStrategy):
    def __init__(self):
        super().__init__(
            name="MACD + SMA Crossover",
            risk_level="MEDIUM",
            description="Utiliza cruce de MACD y SMA para identificar cambios de tendencia",
            min_confidence=70,
            timeframe=3  # 3 minutos
        )
    
    def get_signal(self, indicators):
        try:
            macd = indicators.get('macd', 0)
            macd_signal = indicators.get('macd_signal', 0)
            macd_histogram = indicators.get('macd_histogram', 0)
            price = indicators.get('price', 0)
            sma20 = indicators.get('sma20', 0)
            
            confidence = 0
            direction = None
            
            # Señal CALL: MACD cruza al alza + precio sobre SMA
            if (macd > macd_signal and macd_histogram > 0 and 
                price > sma20 * 1.002):  # precio 0.2% sobre SMA
                direction = "call"
                confidence = 75 if abs(macd_histogram) > 0.0001 else 70
                
            # Señal PUT: MACD cruza a la baja + precio bajo SMA
            elif (macd < macd_signal and macd_histogram < 0 and 
                  price < sma20 * 0.998):  # precio 0.2% bajo SMA
                direction = "put"
                confidence = 75 if abs(macd_histogram) > 0.0001 else 70
            
            return direction, confidence, {
                "strategy": self.name,
                "macd_histogram": round(macd_histogram, 6),
                "price_vs_sma": round((price / sma20 - 1) * 100, 2),
                "macd_cross": "bullish" if macd > macd_signal else "bearish"
            }
            
        except Exception as e:
            logger.error(f"Error en MACDSMAStrategy: {e}")
            return None, 0, {}

# 3. ESTRATEGIA AGRESIVA - STOCHASTIC + MOMENTUM (RIESGO MEDIO-ALTO)
class StochasticMomentumStrategy(BinaryStrategy):
    def __init__(self):
        super().__init__(
            name="Stochastic Momentum",
            risk_level="MEDIUM",
            description="Combina oscilador estocástico con momentum para operaciones rápidas",
            min_confidence=65,
            timeframe=1  # 1 minuto - operaciones rápidas
        )
    
    def get_signal(self, indicators):
        try:
            stoch_k = indicators.get('stoch_k', 50)
            stoch_d = indicators.get('stoch_d', 50)
            volatility = indicators.get('volatility', 0)
            atr = indicators.get('atr', 0)
            
            confidence = 0
            direction = None
            
            # Señal CALL: Stoch K cruza D al alza desde sobreventa
            if (stoch_k > stoch_d and stoch_k <= 25 and stoch_d <= 25 and 
                volatility > 1.0):  # requiere volatilidad
                direction = "call"
                confidence = 75 if stoch_k <= 20 else 65
                
            # Señal PUT: Stoch K cruza D a la baja desde sobrecompra
            elif (stoch_k < stoch_d and stoch_k >= 75 and stoch_d >= 75 and 
                  volatility > 1.0):
                direction = "put"
                confidence = 75 if stoch_k >= 80 else 65
            
            return direction, confidence, {
                "strategy": self.name,
                "stoch_k": stoch_k,
                "stoch_d": stoch_d,
                "volatility": volatility,
                "momentum": "strong" if volatility > 2.0 else "normal"
            }
            
        except Exception as e:
            logger.error(f"Error en StochasticMomentumStrategy: {e}")
            return None, 0, {}

# 4. ESTRATEGIA DE RUPTURA - BOLLINGER SQUEEZE (RIESGO ALTO)
class BollingerSqueezeStrategy(BinaryStrategy):
    def __init__(self):
        super().__init__(
            name="Bollinger Squeeze Breakout",
            risk_level="HIGH",
            description="Detecta compresión de volatilidad y opera rupturas explosivas",
            min_confidence=80,
            timeframe=2  # 2 minutos
        )
    
    def get_signal(self, indicators):
        try:
            bb_upper = indicators.get('bb_upper', 0)
            bb_lower = indicators.get('bb_lower', 0)
            bb_middle = indicators.get('bb_middle', 0)
            price = indicators.get('price', 0)
            volatility = indicators.get('volatility', 0)
            atr = indicators.get('atr', 0)
            
            confidence = 0
            direction = None
            
            # Calcular ancho de banda (squeeze detection)
            bb_width = ((bb_upper - bb_lower) / bb_middle) * 100
            
            # Detectar squeeze (baja volatilidad) seguido de ruptura
            squeeze_threshold = 2.0  # 2% ancho de banda
            
            if bb_width < squeeze_threshold:  # En squeeze
                # Ruptura alcista
                if price > bb_upper and volatility > 1.5:
                    direction = "call"
                    confidence = 85
                # Ruptura bajista
                elif price < bb_lower and volatility > 1.5:
                    direction = "put"
                    confidence = 85
            
            return direction, confidence, {
                "strategy": self.name,
                "bb_width": round(bb_width, 2),
                "squeeze_active": bb_width < squeeze_threshold,
                "breakout_strength": "strong" if volatility > 2.0 else "normal",
                "price_position": "above_upper" if price > bb_upper else "below_lower" if price < bb_lower else "inside"
            }
            
        except Exception as e:
            logger.error(f"Error en BollingerSqueezeStrategy: {e}")
            return None, 0, {}

# 5. ESTRATEGIA SCALPING - TRIPLE CONFIRMACIÓN (RIESGO ALTO)
class TripleConfirmationStrategy(BinaryStrategy):
    def __init__(self):
        super().__init__(
            name="Triple Confirmation Scalping",
            risk_level="HIGH",
            description="Requiere confirmación de RSI, MACD y Bollinger para máxima precisión",
            min_confidence=85,
            timeframe=1  # 1 minuto - scalping
        )
    
    def get_signal(self, indicators):
        try:
            rsi = indicators.get('rsi', 50)
            macd = indicators.get('macd', 0)
            macd_signal = indicators.get('macd_signal', 0)
            price = indicators.get('price', 0)
            bb_upper = indicators.get('bb_upper', 0)
            bb_lower = indicators.get('bb_lower', 0)
            bb_middle = indicators.get('bb_middle', 0)
            volatility = indicators.get('volatility', 0)
            
            confidence = 0
            direction = None
            confirmations = []
            
            # Confirmaciones para CALL
            call_confirmations = 0
            if rsi <= 35:  # RSI sobreventa
                call_confirmations += 1
                confirmations.append("RSI_OVERSOLD")
            if macd > macd_signal:  # MACD alcista
                call_confirmations += 1
                confirmations.append("MACD_BULLISH")
            if price <= bb_lower * 1.001:  # Precio en banda inferior
                call_confirmations += 1
                confirmations.append("BB_LOWER_TOUCH")
            
            # Confirmaciones para PUT
            put_confirmations = 0
            if rsi >= 65:  # RSI sobrecompra
                put_confirmations += 1
                confirmations.append("RSI_OVERBOUGHT")
            if macd < macd_signal:  # MACD bajista
                put_confirmations += 1
                confirmations.append("MACD_BEARISH")
            if price >= bb_upper * 0.999:  # Precio en banda superior
                put_confirmations += 1
                confirmations.append("BB_UPPER_TOUCH")
            
            # Requiere al menos 3 confirmaciones
            if call_confirmations >= 3 and volatility > 0.5:
                direction = "call"
                confidence = 90 if call_confirmations == 3 else 85
            elif put_confirmations >= 3 and volatility > 0.5:
                direction = "put"
                confidence = 90 if put_confirmations == 3 else 85
            
            return direction, confidence, {
                "strategy": self.name,
                "confirmations": confirmations,
                "confirmation_count": max(call_confirmations, put_confirmations),
                "volatility_check": volatility > 0.5
            }
            
        except Exception as e:
            logger.error(f"Error en TripleConfirmationStrategy: {e}")
            return None, 0, {}

# Instanciar estrategias
STRATEGIES = {
    "rsi_bollinger": RSIBollingerStrategy(),
    "macd_sma": MACDSMAStrategy(), 
    "stochastic_momentum": StochasticMomentumStrategy(),
    "bollinger_squeeze": BollingerSqueezeStrategy(),
    "triple_confirmation": TripleConfirmationStrategy()
}

# Métricas de trading por usuario
class TradingMetrics:
    def __init__(self):
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.draws = 0
        self.total_profit = 0.0
        self.consecutive_losses = 0
        self.max_consecutive_losses = 0
        self.start_balance = 0.0
        self.current_balance = 0.0
        self.best_profit = 0.0
        self.worst_loss = 0.0
        self.strategy_stats = {}  # estadísticas por estrategia
        
    def update_strategy_stats(self, strategy_name, result, profit):
        if strategy_name not in self.strategy_stats:
            self.strategy_stats[strategy_name] = {
                "trades": 0, "wins": 0, "losses": 0, "profit": 0.0
            }
        
        stats = self.strategy_stats[strategy_name]
        stats["trades"] += 1
        stats["profit"] += profit
        
        if result == "WIN":
            stats["wins"] += 1
        elif result == "LOSS":
            stats["losses"] += 1
        
    def to_dict(self):
        win_rate = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "draws": self.draws,
            "win_rate": round(win_rate, 2),
            "total_profit": round(self.total_profit, 2),
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "best_profit": round(self.best_profit, 2),
            "worst_loss": round(self.worst_loss, 2),
            "roi": round(((self.current_balance - self.start_balance) / self.start_balance * 100) if self.start_balance > 0 else 0, 2),
            "strategy_stats": self.strategy_stats
        }

user_metrics = {}

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

# Cálculo de indicadores técnicos optimizado para opciones binarias
def calculate_indicators(candles):
    """Calcula indicadores técnicos optimizados para trading de opciones binarias"""
    try:
        if len(candles) < 50:
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        
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
        
        # EMA para MACD
        def calculate_ema(data, period):
            ema = np.zeros_like(data)
            ema[0] = data[0]
            multiplier = 2 / (period + 1)
            for i in range(1, len(data)):
                ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
            return ema
        
        # MACD (12, 26, 9)
        ema12 = calculate_ema(closes, 12)
        ema26 = calculate_ema(closes, 26)
        macd_line = ema12 - ema26
        signal_line = calculate_ema(macd_line, 9)
        macd_histogram = macd_line - signal_line
        
        # Stochastic optimizado (14, 3, 3)
        period = 14
        lowest_low = np.min(lows[-period:])
        highest_high = np.max(highs[-period:])
        
        if highest_high != lowest_low:
            stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
        else:
            stoch_k = 50
        
        # Promedio de últimos 3 K para D
        recent_k = []
        for i in range(max(0, len(closes)-3), len(closes)):
            if i >= period:
                ll = np.min(lows[i-period:i])
                hh = np.max(highs[i-period:i])
                if hh != ll:
                    k_val = 100 * ((closes[i] - ll) / (hh - ll))
                else:
                    k_val = 50
                recent_k.append(k_val)
        
        stoch_d = np.mean(recent_k) if recent_k else stoch_k
        
        # Bollinger Bands optimizado (20, 2)
        bb_period = 20
        bb_std = 2
        sma20 = np.mean(closes[-bb_period:])
        std20 = np.std(closes[-bb_period:])
        bb_upper = sma20 + (bb_std * std20)
        bb_lower = sma20 - (bb_std * std20)
        
        # ATR para volatilidad
        tr = []
        for i in range(1, len(candles)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr.append(max(high_low, high_close, low_close))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else 0
        
        # Volatilidad normalizada
        volatility = (std20 / sma20 * 100) if sma20 > 0 else 0
        
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
            "volatility": round(volatility, 2),
            "candles_data": {
                "current": {
                    "open": round(float(candles[-1]['open']), 5),
                    "high": round(float(candles[-1]['max']), 5),
                    "low": round(float(candles[-1]['min']), 5),
                    "close": round(float(candles[-1]['close']), 5),
                    "timestamp": int(candles[-1]['from'])
                },
                "previous": {
                    "open": round(float(candles[-2]['open']), 5),
                    "high": round(float(candles[-2]['max']), 5),
                    "low": round(float(candles[-2]['min']), 5),
                    "close": round(float(candles[-2]['close']), 5),
                    "timestamp": int(candles[-2]['from'])
                } if len(candles) > 1 else None
            }
        }
        
    except Exception as e:
        logger.error(f"Error calculando indicadores: {e}")
        return None

def get_best_signal(indicators, selected_strategy=None):
    """Obtiene la mejor señal basada en todas las estrategias o una específica"""
    if not indicators:
        return None, 0, {}
    
    best_signal = None
    best_confidence = 0
    best_analysis = {}
    
    strategies_to_check = [STRATEGIES[selected_strategy]] if selected_strategy else STRATEGIES.values()
    
    for strategy in strategies_to_check:
        try:
            direction, confidence, analysis = strategy.get_signal(indicators)
            
            if direction and confidence >= strategy.min_confidence:
                if confidence > best_confidence:
                    best_signal = direction
                    best_confidence = confidence
                    best_analysis = {
                        "strategy_used": strategy.name,
                        "risk_level": strategy.risk_level,
                        "timeframe": strategy.timeframe,
                        "analysis": analysis,
                        "all_strategies": {}
                    }
                    
        except Exception as e:
            logger.error(f"Error en estrategia {strategy.name}: {e}")
    
    # Agregar análisis de todas las estrategias para debug
    for name, strategy in STRATEGIES.items():
        try:
            direction, confidence, analysis = strategy.get_signal(indicators)
            best_analysis.setdefault("all_strategies", {})[name] = {
                "direction": direction,
                "confidence": confidence,
                "risk": strategy.risk_level,
                "min_confidence": strategy.min_confidence
            }
        except:
            pass
    
    return best_signal, best_confidence, best_analysis

# Clase Bot de Trading optimizado para opciones binarias
class BinaryTradingBot:
    def __init__(self, iq_api, config, email):
        self.iq_api = iq_api
        self.config = config
        self.email = email
        self.running = False
        self.thread = None
        self.current_amount = config['amount']
        self.consecutive_losses = 0
        self.session_profit = 0
        self.max_trades_reached = False
        self.max_loss_trades_reached = False
        self.total_session_trades = 0
        
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
        """Loop principal del bot optimizado para opciones binarias"""
        try:
            logger.info(f"🚀 Bot de Opciones Binarias iniciado para {self.email}")
            
            send_telegram_message(f"""🚀 *BOT OPCIONES BINARIAS INICIADO*
👤 Usuario: {self.email}
📈 Par: {self.config['symbol']}
💰 Monto inicial: ${self.config['amount']:.2f}
🎯 Estrategia: {self.config.get('strategy', 'Auto-selección')}
🎲 Martingalas: {self.config['martingalas']}
🏦 Cuenta: {self.config['account_type']}
🛑 Stop Loss: {self.config.get('max_loss_trades', 'Sin límite')} pérdidas
🎯 Take Profit: {self.config.get('max_trades', 'Sin límite')} trades
💼 Capital máximo: 50% del balance""")
            
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
                    
                    # Verificar límite de trades por pérdidas (Stop Loss por número de pérdidas)
                    if (self.config.get('max_loss_trades', 0) > 0 and 
                        self.consecutive_losses >= self.config['max_loss_trades']):
                        self.max_loss_trades_reached = True
                        logger.info(f"Límite de pérdidas consecutivas alcanzado para {self.email}")
                        send_telegram_message(f"""🛑 *STOP LOSS POR PÉRDIDAS ALCANZADO*
👤 Usuario: {self.email}
💸 Pérdidas consecutivas: {self.consecutive_losses}
📊 Total trades de sesión: {self.total_session_trades}
💰 P&L de sesión: ${self.session_profit:.2f}
🏁 Bot detenido automáticamente""")
                        break
                    
                    # Verificar límite de trades totales (Take Profit por número de trades)
                    if (self.config.get('max_trades', 0) > 0 and 
                        self.total_session_trades >= self.config['max_trades']):
                        self.max_trades_reached = True
                        logger.info(f"Límite de trades totales alcanzado para {self.email}")
                        send_telegram_message(f"""🎯 *LÍMITE DE TRADES ALCANZADO*
👤 Usuario: {self.email}
📊 Total trades ejecutados: {self.total_session_trades}
💰 P&L de sesión: ${self.session_profit:.2f}
🏁 Bot detenido automáticamente""")
                        break
                    
                    # Verificar capital máximo (50% del balance)
                    current_balance = self.iq_api.get_balance()
                    max_allowed_trade = current_balance * 0.5  # 50% del balance
                    
                    if self.current_amount > max_allowed_trade:
                        logger.warning(f"Monto ajustado de ${self.current_amount:.2f} a ${max_allowed_trade:.2f} (50% del balance)")
                        self.current_amount = max_allowed_trade
                    
                    # Verificar balance mínimo
                    if self.current_amount > current_balance:
                        logger.error(f"Fondos insuficientes. Balance: ${current_balance:.2f}, Requerido: ${self.current_amount:.2f}")
                        send_telegram_message(f"""❌ *FONDOS INSUFICIENTES*
💰 Balance: ${current_balance:.2f}
💸 Requerido: ${self.current_amount:.2f}
🛑 Bot detenido""")
                        break
                    
                    # Obtener velas (solo necesitamos datos de 1 minuto para opciones binarias)
                    candles = self.iq_api.get_candles(self.config['symbol'], 60, 100, time.time())
                    
                    if not candles or len(candles) < 50:
                        logger.warning(f"Datos insuficientes para {self.config['symbol']}")
                        time.sleep(30)
                        continue
                    
                    # Calcular indicadores optimizados para opciones binarias
                    indicators = calculate_indicators(candles)
                    if not indicators:
                        time.sleep(30)
                        continue
                    
                    # Obtener señal de trading
                    selected_strategy = self.config.get('strategy')
                    direction, confidence, analysis = get_best_signal(indicators, selected_strategy)
                    
                    # Log detallado del análisis
                    analysis_msg = f"""📊 *ANÁLISIS OPCIONES BINARIAS*
📈 Par: {self.config['symbol']}
💹 Precio: {indicators['price']}
📊 RSI: {indicators['rsi']}
📈 MACD: {indicators['macd']:.6f}
📉 Signal: {indicators['macd_signal']:.6f}
🎯 Stoch K/D: {indicators['stoch_k']:.1f}/{indicators['stoch_d']:.1f}
📊 Volatilidad: {indicators['volatility']:.2f}%
🎪 BB: {indicators['bb_lower']:.5f} | {indicators['bb_middle']:.5f} | {indicators['bb_upper']:.5f}"""
                    
                    if direction and analysis:
                        strategy_info = analysis.get('strategy_used', 'Unknown')
                        risk_level = analysis.get('risk_level', 'MEDIUM')
                        timeframe = analysis.get('timeframe', 1)
                        
                        analysis_msg += f"\n\n🔔 *SEÑAL: {direction.upper()}*"
                        analysis_msg += f"\n🎯 Confianza: {confidence}%"
                        analysis_msg += f"\n📋 Estrategia: {strategy_info}"
                        analysis_msg += f"\n⚡ Riesgo: {risk_level}"
                        analysis_msg += f"\n⏱️ Expiración: {timeframe}min"
                    else:
                        analysis_msg += "\n\n⏳ Sin señal clara"
                        # Mostrar por qué no hay señal
                        all_strategies = analysis.get('all_strategies', {})
                        for name, data in all_strategies.items():
                            conf = data.get('confidence', 0)
                            min_conf = data.get('min_confidence', 70)
                            if conf > 0 and conf < min_conf:
                                analysis_msg += f"\n• {name}: {conf}% (req: {min_conf}%)"
                    
                    logger.info(f"Análisis: {analysis_msg}")
                    
                    # Ejecutar operación si hay señal válida
                    if direction and confidence >= 60:  # Umbral mínimo global
                        strategy_used = analysis.get('strategy_used', 'Unknown')
                        timeframe = analysis.get('timeframe', 1)
                        
                        # Ejecutar trade de opción binaria
                        result = self._execute_binary_trade(direction, timeframe, strategy_used, analysis)
                        
                        # Actualizar métricas
                        self.total_session_trades += 1
                        
                        if self.email in user_metrics:
                            metrics = user_metrics[self.email]
                            metrics.total_trades += 1
                            metrics.update_strategy_stats(strategy_used, result['result'], result['profit'])
                            
                            if result['result'] == 'WIN':
                                metrics.wins += 1
                                self.consecutive_losses = 0
                                self.session_profit += result['profit']
                                self.current_amount = self.config['amount']  # Reset a monto inicial
                                
                                if result['profit'] > metrics.best_profit:
                                    metrics.best_profit = result['profit']
                                    
                            elif result['result'] == 'LOSS':
                                metrics.losses += 1
                                self.consecutive_losses += 1
                                metrics.consecutive_losses = self.consecutive_losses
                                metrics.max_consecutive_losses = max(
                                    metrics.max_consecutive_losses,
                                    self.consecutive_losses
                                )
                                self.session_profit += result['profit']  # Negativo
                                
                                if result['profit'] < metrics.worst_loss:
                                    metrics.worst_loss = result['profit']
                                
                                # Aplicar Martingala solo si está configurada
                                if self.consecutive_losses <= self.config['martingalas'] and self.config['martingalas'] > 0:
                                    new_amount = self.current_amount * 2
                                    max_allowed = current_balance * 0.5
                                    
                                    if new_amount <= max_allowed:
                                        self.current_amount = new_amount
                                        logger.info(f"Aplicando Martingala {self.consecutive_losses}: ${self.current_amount:.2f}")
                                    else:
                                        logger.warning(f"Martingala limitada por capital máximo: ${max_allowed:.2f}")
                                        self.current_amount = max_allowed
                                else:
                                    # Reset a monto inicial si no hay más martingalas
                                    self.current_amount = self.config['amount']
                                    
                            else:  # DRAW/EMPATE
                                metrics.draws += 1
                                self.current_amount = self.config['amount']  # Reset
                                self.consecutive_losses = 0
                            
                            metrics.total_profit = self.session_profit
                            metrics.current_balance = self.iq_api.get_balance()
                        
                        # Pausa entre operaciones (ajustada para opciones binarias)
                        wait_time = max(timeframe * 60 + 30, 90)  # Esperar expiración + 30s mínimo
                        time.sleep(wait_time)
                    else:
                        # Sin señal clara, esperar menos tiempo
                        time.sleep(45)
                        
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
            
            # Resumen final detallado
            win_rate = 0
            if self.email in user_metrics:
                metrics = user_metrics[self.email]
                win_rate = (metrics.wins / metrics.total_trades * 100) if metrics.total_trades > 0 else 0
            
            final_message = f"""🏁 *BOT OPCIONES BINARIAS FINALIZADO*
👤 Usuario: {self.email}
📈 Par: {self.config['symbol']}
📊 Trades ejecutados: {self.total_session_trades}
💰 P&L Sesión: ${self.session_profit:.2f}
📈 Win Rate: {win_rate:.1f}%
🎲 Pérdidas consecutivas: {self.consecutive_losses}
⏰ Finalizado: {datetime.datetime.now().strftime('%H:%M:%S')}"""
            
            if self.max_loss_trades_reached:
                final_message += "\n🛑 Razón: Límite de pérdidas alcanzado"
            elif self.max_trades_reached:
                final_message += "\n🎯 Razón: Límite de trades alcanzado"
            elif self.consecutive_losses > self.config['martingalas']:
                final_message += "\n💀 Razón: Martingalas agotadas"
            else:
                final_message += "\n👋 Razón: Detenido manualmente"
            
            send_telegram_message(final_message)
            logger.info(f"Bot de opciones binarias finalizado para {self.email}")
    
    def _execute_binary_trade(self, direction, timeframe, strategy_used, analysis):
        """Ejecuta una operación de opción binaria y espera el resultado"""
        try:
            logger.info(f"🎯 Ejecutando {direction.upper()} en {self.config['symbol']} por ${self.current_amount:.2f} ({timeframe}min)")
            
            # Abrir operación binaria
            status, order_id = self.iq_api.buy(self.current_amount, self.config['symbol'], direction, timeframe)
            
            if not status:
                logger.error(f"Error abriendo posición: {order_id}")
                return {"result": "ERROR", "profit": 0, "message": str(order_id)}
            
            # Información detallada para Telegram
            risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}
            risk_level = analysis.get('risk_level', 'MEDIUM')
            
            opening_msg = f"""🎯 *OPERACIÓN BINARIA ABIERTA*
📈 Par: {self.config['symbol']}
🎯 Dirección: {direction.upper()}
💰 Monto: ${self.current_amount:.2f}
⏱️ Expiración: {timeframe} minuto(s)
📋 Estrategia: {strategy_used}
{risk_emoji.get(risk_level, '🟡')} Riesgo: {risk_level}
🆔 ID: {order_id}
⏰ Apertura: {datetime.datetime.now().strftime('%H:%M:%S')}
🎲 Martingala: {self.consecutive_losses}
💼 Balance: ${self.iq_api.get_balance():.2f}"""
            
            # Agregar detalles del análisis si están disponibles
            analysis_details = analysis.get('analysis', {})
            if analysis_details:
                opening_msg += f"\n\n📊 *ANÁLISIS DETALLADO*"
                for key, value in analysis_details.items():
                    if isinstance(value, (int, float)):
                        opening_msg += f"\n• {key}: {value}"
                    else:
                        opening_msg += f"\n• {key}: {value}"
            
            send_telegram_message(opening_msg)
            
            # Esperar resultado (timeframe en minutos + buffer)
            wait_time = (timeframe * 60) + 10  # Añadir 10 segundos de buffer
            logger.info(f"Esperando {wait_time} segundos para resultado...")
            time.sleep(wait_time)
            
            # Verificar resultado
            result = self.iq_api.check_win_v3(order_id)
            
            # Procesar resultado
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
                profit = win_amount - self.current_amount  # Ganancia neta
            elif win_amount < 0:
                trade_result = "LOSS"
                profit = -self.current_amount  # Pérdida total
            else:
                trade_result = "DRAW"
                profit = 0  # Empate, recupera inversión
            
            # Notificar resultado detallado
            result_emoji = "✅" if trade_result == "WIN" else "❌" if trade_result == "LOSS" else "⚪"
            result_text = "GANADA" if trade_result == "WIN" else "PERDIDA" if trade_result == "LOSS" else "EMPATE"
            
            payout_rate = 0
            if trade_result == "WIN" and self.current_amount > 0:
                payout_rate = (win_amount / self.current_amount - 1) * 100
            
            result_msg = f"""{result_emoji} *OPERACIÓN {result_text}*
📈 Par: {self.config['symbol']}
🎯 Dirección: {direction.upper()}
💰 Monto: ${self.current_amount:.2f}
💵 Resultado: {'+' if profit >= 0 else ''}${profit:.2f}"""
            
            if trade_result == "WIN":
                result_msg += f"\n💎 Payout: {payout_rate:.1f}%"
                result_msg += f"\n🎉 Ganancia neta: ${profit:.2f}"
            elif trade_result == "LOSS":
                result_msg += f"\n💸 Pérdida total: ${abs(profit):.2f}"
                
            result_msg += f"""
📊 Balance actual: ${self.iq_api.get_balance():.2f}
📈 P&L Sesión: ${self.session_profit + profit:.2f}
⏰ Cierre: {datetime.datetime.now().strftime('%H:%M:%S')}
🔄 Trades de sesión: {self.total_session_trades + 1}"""
            
            send_telegram_message(result_msg)
            
            return {
                "result": trade_result,
                "profit": profit,
                "order_id": order_id,
                "amount": self.current_amount,
                "strategy": strategy_used,
                "payout_rate": payout_rate,
                "timeframe": timeframe
            }
            
        except Exception as e:
            logger.error(f"Error ejecutando trade binario: {e}")
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
        "active_bots": len([b for b in active_bots.values() if b.running]),
        "strategies_available": list(STRATEGIES.keys()),
        "system": "Binary Options Trading Bot Pro"
    }), 200

@app.route('/api/login', methods=['POST', 'OPTIONS'])
@limiter.limit("5 per minute")
def login():
    """Login endpoint optimizado"""
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
            
            # Normalizar el motivo del error
            if isinstance(reason, dict):
                code = reason.get("code", "")
                raw_msg = reason.get("message", "")
            else:
                try:
                    parsed = json.loads(reason)
                    code = parsed.get("code", "")
                    raw_msg = parsed.get("message", "")
                except Exception:
                    code = str(reason)
                    raw_msg = str(reason)
            
            if code == "2FA":
                return jsonify({
                    "success": False,
                    "message": "Autenticación de dos factores requerida",
                    "code": "2FA_REQUIRED"
                }), 401
            elif code == "invalid_credentials":
                return jsonify({
                    "success": False,
                    "message": "Correo o contraseña incorrecta",
                    "code": "INVALID_CREDENTIALS"
                }), 401
            
            return jsonify({
                "success": False,
                "message": f"Error de conexión: {raw_msg}"
            }), 503
        
        # Verificar conexión establecida
        if not iq.check_connect():
            return jsonify({
                "success": False,
                "message": "Correo o contraseña incorrecta"
            }), 401
        
        # Configurar cuenta para opciones binarias
        iq.change_balance("PRACTICE")  # Iniciar en práctica por seguridad
        
        # Obtener información del usuario
        try:
            user_email = iq.email if hasattr(iq, 'email') else email
            user_name = user_email.split('@')[0].title()
            balance = iq.get_balance()
            account_type = iq.get_balance_mode()
            
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
            send_telegram_message(f"""🎯 *LOGIN EXITOSO - OPCIONES BINARIAS*
👤 Usuario: {user_name}
📧 Email: {email}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}
🎯 Modo: Opciones Binarias
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""")
            
            return jsonify({
                "success": True,
                "user": {
                    "name": user_name,
                    "email": email,
                    "balance": float(balance),
                    "account_type": account_type,
                    "currency": "USD",
                    "trading_mode": "Binary Options"
                },
                "message": "Login exitoso - Modo Opciones Binarias activado"
            }), 200
            
        except Exception as e:
            logger.error(f"Error obteniendo datos del usuario: {e}")
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
                    "currency": "USD",
                    "trading_mode": "Binary Options"
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
        
        send_telegram_message(f"👋 *LOGOUT OPCIONES BINARIAS*\n📧 {email}\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
        
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
            "max_trade_amount": float(balance * 0.5),  # Máximo 50% del balance
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
        
        # Símbolos más populares para opciones binarias
        symbols = [
            {"symbol": "EURUSD", "name": "EUR/USD", "type": "major_pairs", "popular": True},
            {"symbol": "GBPUSD", "name": "GBP/USD", "type": "major_pairs", "popular": True},
            {"symbol": "USDJPY", "name": "USD/JPY", "type": "major_pairs", "popular": True},
            {"symbol": "AUDUSD", "name": "AUD/USD", "type": "major_pairs", "popular": False},
            {"symbol": "USDCAD", "name": "USD/CAD", "type": "major_pairs", "popular": False},
            {"symbol": "EURJPY", "name": "EUR/JPY", "type": "major_pairs", "popular": True},
            {"symbol": "GBPJPY", "name": "GBP/JPY", "type": "major_pairs", "popular": False},
            {"symbol": "EURGBP", "name": "EUR/GBP", "type": "major_pairs", "popular": False}
        ]
        
        # Intentar obtener activos abiertos de IQ Option para verificar disponibilidad
        try:
            if hasattr(iq, 'get_all_open_time'):
                all_assets = iq.get_all_open_time()
                
                # Verificar qué símbolos están disponibles para trading binario
                if 'turbo' in all_assets:  # Opciones binarias turbo
                    available_symbols = []
                    for symbol_info in symbols:
                        symbol = symbol_info['symbol']
                        if symbol in all_assets['turbo'] and all_assets['turbo'][symbol].get('open', False):
                            symbol_info['available'] = True
                            available_symbols.append(symbol_info)
                        else:
                            symbol_info['available'] = False
                            available_symbols.append(symbol_info)
                    
                    symbols = available_symbols
                else:
                    # Si no hay datos de turbo, marcar todos como disponibles
                    for symbol_info in symbols:
                        symbol_info['available'] = True
                        
        except Exception as e:
            logger.warning(f"No se pudieron verificar activos disponibles: {e}")
            # Marcar todos como disponibles por defecto
            for symbol_info in symbols:
                symbol_info['available'] = True
        
        return jsonify({"symbols": symbols}), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo símbolos: {str(e)}")
        return jsonify({"error": "Error obteniendo símbolos"}), 500

@app.route('/api/strategies', methods=['GET'])
@require_auth
def get_strategies():
    """Obtener estrategias disponibles para opciones binarias"""
    try:
        strategies_info = []
        
        for key, strategy in STRATEGIES.items():
            strategies_info.append({
                "id": key,
                "name": strategy.name,
                "risk_level": strategy.risk_level,
                "description": strategy.description,
                "min_confidence": strategy.min_confidence,
                "timeframe": strategy.timeframe,
                "risk_color": strategy.get_risk_color()
            })
        
        # Ordenar por nivel de riesgo
        risk_order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        strategies_info.sort(key=lambda x: risk_order.get(x["risk_level"], 2))
        
        return jsonify({"strategies": strategies_info}), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo estrategias: {str(e)}")
        return jsonify({"error": "Error obteniendo estrategias"}), 500

@app.route('/api/start_bot', methods=['POST'])
@require_auth
@limiter.limit("3 per minute")
def start_bot():
    """Iniciar bot de opciones binarias"""
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
        strategy = data.get('strategy', None)  # None = auto-selección
        max_loss_trades = int(data.get('max_loss_trades', 0))  # Stop loss por número de pérdidas
        max_trades = int(data.get('max_trades', 0))  # Take profit por número de trades
        
        # Validaciones específicas para opciones binarias
        if amount <= 0 or amount > 1000:
            return jsonify({"error": "El monto debe estar entre $1 y $1,000 para opciones binarias"}), 400
        
        if martingalas < 0 or martingalas > 3:
            return jsonify({"error": "Las martingalas deben estar entre 0 y 3 para opciones binarias"}), 400
        
        if max_loss_trades < 0 or max_loss_trades > 10:
            return jsonify({"error": "El stop loss debe estar entre 0 y 10 pérdidas consecutivas"}), 400
        
        if max_trades < 0 or max_trades > 100:
            return jsonify({"error": "El límite de trades debe estar entre 0 y 100"}), 400
        
        if strategy and strategy not in STRATEGIES:
            return jsonify({"error": f"Estrategia '{strategy}' no válida"}), 400
        
        # Cambiar tipo de cuenta
        iq = user_sessions[email]
        iq.change_balance(account_type)
        time.sleep(1)  # Dar tiempo para el cambio
        
        # Verificar balance y calcular riesgo máximo
        balance = iq.get_balance()
        max_allowed_amount = balance * 0.5  # Máximo 50% del balance
        
        if amount > max_allowed_amount:
            return jsonify({
                "error": f"El monto máximo permitido es ${max_allowed_amount:.2f} (50% del balance de ${balance:.2f})"
            }), 400
        
        # Calcular riesgo máximo con martingalas
        max_risk = amount * (2**(martingalas + 1) - 1) if martingalas > 0 else amount
        
        if max_risk > max_allowed_amount:
            return jsonify({
                "error": f"Riesgo máximo con martingalas (${max_risk:.2f}) excede el 50% del balance (${max_allowed_amount:.2f})"
            }), 400
        
        # Configuración del bot
        bot_config = {
            'symbol': symbol,
            'amount': amount,
            'martingalas': martingalas,
            'strategy': strategy,
            'max_loss_trades': max_loss_trades,
            'max_trades': max_trades,
            'account_type': account_type
        }
        
        # Crear e iniciar bot de opciones binarias
        bot = BinaryTradingBot(iq, bot_config, email)
        
        with bots_lock:
            active_bots[email] = bot
        
        bot.start()
        
        # Información de la estrategia seleccionada
        strategy_info = "Auto-selección (mejor señal)" if not strategy else STRATEGIES[strategy].name
        risk_level = "MEDIUM" if not strategy else STRATEGIES[strategy].risk_level
        
        return jsonify({
            "message": "Bot de opciones binarias iniciado correctamente",
            "config": bot_config,
            "strategy_info": strategy_info,
            "risk_level": risk_level,
            "max_risk": max_risk,
            "max_allowed_amount": max_allowed_amount
        }), 200
        
    except Exception as e:
        logger.error(f"Error iniciando bot: {str(e)}")
        return jsonify({"error": f"Error iniciando bot: {str(e)}"}), 500

@app.route('/api/stop_bot', methods=['POST'])
@require_auth
def stop_bot():
    """Detener bot de opciones binarias"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                bot.stop()
                del active_bots[email]
                
                send_telegram_message(f"🛑 *BOT OPCIONES BINARIAS DETENIDO MANUALMENTE*\n👤 {email}")
                
                return jsonify({"message": "Bot detenido correctamente"}), 200
            else:
                return jsonify({"error": "No hay bot activo para detener"}), 400
                
    except Exception as e:
        logger.error(f"Error deteniendo bot: {str(e)}")
        return jsonify({"error": "Error deteniendo bot"}), 500

@app.route('/api/bot_status', methods=['GET'])
@require_auth
def bot_status():
    """Obtener estado del bot de opciones binarias"""
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
                    "total_session_trades": bot.total_session_trades,
                    "max_trades_reached": bot.max_trades_reached,
                    "max_loss_trades_reached": bot.max_loss_trades_reached,
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
    """Obtener métricas de trading detalladas"""
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
        time.sleep(1)  # Dar tiempo para el cambio
        
        # Verificar cambio
        new_balance = iq.get_balance()
        new_type = iq.get_balance_mode()
        
        return jsonify({
            "success": True,
            "account_type": new_type,
            "balance": float(new_balance),
            "max_trade_amount": float(new_balance * 0.5)
        }), 200
        
    except Exception as e:
        logger.error(f"Error cambiando cuenta: {str(e)}")
        return jsonify({"error": "Error cambiando cuenta"}), 500

@app.route('/api/market_analysis', methods=['GET'])
@require_auth
def get_market_analysis():
    """Obtener análisis de mercado en tiempo real"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        symbol = request.args.get('symbol', 'EURUSD')
        
        # Obtener datos de velas
        candles = iq.get_candles(symbol, 60, 100, time.time())
        
        if not candles or len(candles) < 50:
            return jsonify({"error": "Datos insuficientes para análisis"}), 400
        
        # Calcular indicadores
        indicators = calculate_indicators(candles)
        if not indicators:
            return jsonify({"error": "Error calculando indicadores"}), 500
        
        # Obtener señales de todas las estrategias
        all_signals = {}
        best_signal = None
        best_confidence = 0
        
        for strategy_key, strategy in STRATEGIES.items():
            try:
                direction, confidence, analysis = strategy.get_signal(indicators)
                all_signals[strategy_key] = {
                    "name": strategy.name,
                    "risk_level": strategy.risk_level,
                    "direction": direction,
                    "confidence": confidence,
                    "min_confidence": strategy.min_confidence,
                    "timeframe": strategy.timeframe,
                    "analysis": analysis,
                    "valid_signal": direction is not None and confidence >= strategy.min_confidence
                }
                
                if direction and confidence >= strategy.min_confidence and confidence > best_confidence:
                    best_signal = direction
                    best_confidence = confidence
                    
            except Exception as e:
                logger.error(f"Error analizando estrategia {strategy_key}: {e}")
                all_signals[strategy_key] = {
                    "name": strategy.name,
                    "error": str(e)
                }
        
        return jsonify({
            "symbol": symbol,
            "indicators": indicators,
            "best_signal": {
                "direction": best_signal,
                "confidence": best_confidence
            },
            "strategies": all_signals,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error en análisis de mercado: {str(e)}")
        return jsonify({"error": "Error obteniendo análisis"}), 500

@app.route('/api/live_candles', methods=['GET'])
@require_auth
def get_live_candles():
    """Obtener datos de velas en tiempo real para gráficos"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        symbol = request.args.get('symbol', 'EURUSD')
        timeframe = int(request.args.get('timeframe', 60))  # segundos
        count = int(request.args.get('count', 50))
        
        # Obtener velas
        candles = iq.get_candles(symbol, timeframe, count, time.time())
        
        if not candles:
            return jsonify({"error": "No se pudieron obtener datos de velas"}), 400
        
        # Formatear datos para gráficos
        formatted_candles = []
        for candle in candles:
            formatted_candles.append({
                "timestamp": int(candle['from']),
                "datetime": datetime.datetime.fromtimestamp(int(candle['from'])).isoformat(),
                "open": float(candle['open']),
                "high": float(candle['max']),
                "low": float(candle['min']),
                "close": float(candle['close']),
                "volume": int(candle.get('volume', 0))
            })
        
        return jsonify({
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": formatted_candles,
            "count": len(formatted_candles)
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo velas: {str(e)}")
        return jsonify({"error": "Error obteniendo datos de velas"}), 500

@app.route('/api/trading_signals', methods=['GET'])
@require_auth
def get_trading_signals():
    """Obtener señales de trading en tiempo real"""
    try:
        email = session['user_email']
        iq = user_sessions[email]
        
        symbol = request.args.get('symbol', 'EURUSD')
        strategy = request.args.get('strategy', None)
        
        # Obtener datos de mercado
        candles = iq.get_candles(symbol, 60, 100, time.time())
        
        if not candles or len(candles) < 50:
            return jsonify({"error": "Datos insuficientes"}), 400
        
        # Calcular indicadores
        indicators = calculate_indicators(candles)
        if not indicators:
            return jsonify({"error": "Error calculando indicadores"}), 500
        
        # Obtener señal
        direction, confidence, analysis = get_best_signal(indicators, strategy)
        
        # Información de riesgo y recomendaciones
        risk_assessment = "LOW"
        if confidence >= 80:
            risk_assessment = "LOW"
        elif confidence >= 70:
            risk_assessment = "MEDIUM"
        else:
            risk_assessment = "HIGH"
        
        # Calcular precio objetivo y stop loss sugeridos
        current_price = indicators['price']
        atr = indicators['atr']
        
        suggested_expiry = 1  # minutos por defecto
        if analysis.get('strategy_used'):
            strategy_obj = None
            for s in STRATEGIES.values():
                if s.name == analysis['strategy_used']:
                    strategy_obj = s
                    break
            if strategy_obj:
                suggested_expiry = strategy_obj.timeframe
        
        return jsonify({
            "symbol": symbol,
            "signal": {
                "direction": direction,
                "confidence": confidence,
                "strategy": analysis.get('strategy_used', 'Auto'),
                "risk_level": analysis.get('risk_level', 'MEDIUM'),
                "suggested_expiry": suggested_expiry,
                "current_price": current_price,
                "risk_assessment": risk_assessment
            },
            "indicators": {
                "rsi": indicators['rsi'],
                "macd": indicators['macd'],
                "macd_signal": indicators['macd_signal'],
                "stoch_k": indicators['stoch_k'],
                "stoch_d": indicators['stoch_d'],
                "bb_upper": indicators['bb_upper'],
                "bb_middle": indicators['bb_middle'],
                "bb_lower": indicators['bb_lower'],
                "volatility": indicators['volatility']
            },
            "analysis": analysis,
            "timestamp": datetime.datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo señales: {str(e)}")
        return jsonify({"error": "Error obteniendo señales"}), 500

@app.route('/api/strategy_performance', methods=['GET'])
@require_auth  
def get_strategy_performance():
    """Obtener rendimiento histórico de estrategias"""
    try:
        email = session['user_email']
        
        if email not in user_metrics:
            return jsonify({"error": "No hay datos de métricas"}), 400
        
        metrics = user_metrics[email]
        strategy_stats = metrics.strategy_stats
        
        # Calcular métricas por estrategia
        performance_data = []
        
        for strategy_name, stats in strategy_stats.items():
            trades = stats['trades']
            wins = stats['wins']
            losses = stats['losses']
            profit = stats['profit']
            
            win_rate = (wins / trades * 100) if trades > 0 else 0
            avg_profit = profit / trades if trades > 0 else 0
            
            # Buscar información de la estrategia
            strategy_info = None
            for s in STRATEGIES.values():
                if s.name == strategy_name:
                    strategy_info = s
                    break
            
            performance_data.append({
                "strategy_name": strategy_name,
                "total_trades": trades,
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 2),
                "total_profit": round(profit, 2),
                "avg_profit_per_trade": round(avg_profit, 2),
                "risk_level": strategy_info.risk_level if strategy_info else "UNKNOWN",
                "risk_color": strategy_info.get_risk_color() if strategy_info else "#6366f1"
            })
        
        # Ordenar por rentabilidad
        performance_data.sort(key=lambda x: x['total_profit'], reverse=True)
        
        return jsonify({
            "strategy_performance": performance_data,
            "total_trades": metrics.total_trades,
            "overall_profit": metrics.total_profit
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo rendimiento de estrategias: {str(e)}")
        return jsonify({"error": "Error obteniendo datos de rendimiento"}), 500

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
                        logger.warning(f"Error verificando sesión de {email}, eliminando")
                        del user_sessions[email]
        except Exception as e:
            logger.error(f"Error en limpieza de sesiones: {e}")

# Función de monitoreo en tiempo real
def send_market_updates():
    """Envía actualizaciones de mercado cada 30 segundos"""
    while True:
        time.sleep(30)
        try:
            # Solo si hay bots activos
            if not active_bots:
                continue
                
            # Obtener datos de mercado para símbolos activos
            active_symbols = set()
            with bots_lock:
                for bot in active_bots.values():
                    if bot.running:
                        active_symbols.add(bot.config['symbol'])
            
            # Procesar cada símbolo activo
            for symbol in active_symbols:
                try:
                    # Buscar una sesión activa para obtener datos
                    iq = None
                    with sessions_lock:
                        if user_sessions:
                            iq = list(user_sessions.values())[0]
                    
                    if not iq:
                        continue
                        
                    # Obtener datos de mercado
                    candles = iq.get_candles(symbol, 60, 50, time.time())
                    if not candles:
                        continue
                        
                    indicators = calculate_indicators(candles)
                    if not indicators:
                        continue
                    
                    # Obtener señales
                    direction, confidence, analysis = get_best_signal(indicators)
                    
                    # Solo enviar si hay señal fuerte
                    if direction and confidence >= 75:
                        market_update = f"""📊 *SEÑAL DE MERCADO*
📈 {symbol}: {indicators['price']}
🎯 Señal: {direction.upper()}
💪 Confianza: {confidence}%
📋 Estrategia: {analysis.get('strategy_used', 'Auto')}
⚡ Riesgo: {analysis.get('risk_level', 'MEDIUM')}
⏰ {datetime.datetime.now().strftime('%H:%M:%S')}"""
                        
                        # Enviar solo si hay cambios significativos
                        send_telegram_message(market_update)
                        
                except Exception as e:
                    logger.error(f"Error procesando {symbol}: {e}")
                    
        except Exception as e:
            logger.error(f"Error en actualizaciones de mercado: {e}")

# Iniciar threads de fondo
cleanup_thread = Thread(target=cleanup_inactive_sessions, daemon=True)
cleanup_thread.start()

market_updates_thread = Thread(target=send_market_updates, daemon=True)
market_updates_thread.start()

# Manejador de señales para cierre limpio
def signal_handler(sig, frame):
    logger.info("Cerrando aplicación...")
    
    # Detener todos los bots
    with bots_lock:
        for bot in list(active_bots.values()):
            bot.stop()
        active_bots.clear()
    
    # Cerrar todas las sesiones
    with sessions_lock:
        for iq in user_sessions.values():
            try:
                iq.close_websocket()
            except:
                pass
        user_sessions.clear()
    
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Main
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 60)
    logger.info(f"🚀 INICIANDO BOT DE OPCIONES BINARIAS PRO")
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🔧 IQ Option API: {'Disponible' if IQ_AVAILABLE else 'No disponible'}")
    logger.info(f"📱 Telegram: {'Configurado' if TELEGRAM_BOT_TOKEN else 'No configurado'}")
    logger.info(f"🎯 Estrategias: {len(STRATEGIES)} disponibles")
    logger.info(f"📊 Modo: Solo Opciones Binarias")
    logger.info("=" * 60)
    
    for strategy_key, strategy in STRATEGIES.items():
        logger.info(f"  📋 {strategy.name} ({strategy.risk_level} risk) - {strategy.timeframe}min")
    
    if not IQ_AVAILABLE:
        logger.error("IQOptionAPI no está disponible. El servidor no funcionará correctamente.")
        logger.error("Instala con: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
    
    send_telegram_message(f"""🚀 *BOT OPCIONES BINARIAS PRO INICIADO*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🔧 API: {'OK' if IQ_AVAILABLE else 'ERROR'}
🎯 Estrategias: {len(STRATEGIES)} activas
📊 Modo: Solo Opciones Binarias
💼 Capital máximo: 50% del balance""")
    
    # Usar servidor de desarrollo Flask con threading
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
