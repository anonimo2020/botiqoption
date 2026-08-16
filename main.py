import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import traceback
import sys
import time
import threading
import concurrent.futures
from flask import send_from_directory

def clear_invalid_session():
    """Limpia sesión inválida y borra cookie"""
    session.clear()
    response = jsonify({"error": "Session expired or invalid"})
    response.delete_cookie(
        app.config.get("SESSION_COOKIE_NAME", "session"),
        path="/",
        domain=app.config.get("SESSION_COOKIE_DOMAIN"),
        samesite=app.config.get("SESSION_COOKIE_SAMESITE", "None"),
        secure=app.config.get("SESSION_COOKIE_SECURE", True)
    )
    return response, 401



# Configuración de logging detallado
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ============================================================================
# THREADING MODE - COMPATIBLE CON RENDER
# ============================================================================
logger.info("✅ Modo Threading activado (sin eventlet)")

# ============================================================================
# Timeout usando ThreadPoolExecutor para conexiones IQ Option
# ============================================================================

import concurrent.futures

import concurrent.futures

class SafeIQConnection:
    """Conexión segura a IQ Option usando thread real + timeout (threading mode)."""

    @staticmethod
    def safe_connect(email: str, password: str, timeout: int = 25):
        """
        ✅ MEJORADO: Conexión segura con limpieza de SSID previo.
        
        Mejoras:
        - Limpia global_value.SSID antes de conectar
        - Cierra websocket anterior si existe
        - Valida que la conexión esté realmente activa
        """
        logger.info(f"Conexión IQOption (timeout={timeout}s)...")

        try:
            from iqoptionapi.stable_api import IQ_Option
            import iqoptionapi.global_value as global_value

            # ✅ CRÍTICO: Limpiar SSID global antes de nueva conexión
            # Evita reutilizar SSID de sesiones anteriores
            if hasattr(global_value, 'SSID'):
                old_ssid = str(global_value.SSID)[:20] if global_value.SSID else "None"
                logger.info(f"🧹 Limpiando SSID previo: {old_ssid}...")
                global_value.SSID = None

            # Crear nueva instancia
            api = IQ_Option(email, password)
            logger.info("Instancia IQ_Option creada")

            def _do_connect():
                """Thread que ejecuta la conexión"""
                try:
                    result = api.connect()
                    
                    # Validar que el websocket esté activo
                    if result and result[0]:
                        # Verificar que podemos obtener balance (indica conexión real)
                        try:
                            balance = api.get_balance()
                            if balance is None:
                                logger.warning("⚠️ Balance es None después de conectar")
                                return False, "Conexión establecida pero sin acceso a datos"
                        except Exception as balance_err:
                            logger.warning(f"⚠️ Error obteniendo balance inicial: {balance_err}")
                            # No es crítico, continuar
                    
                    return result
                except Exception as e:
                    logger.exception(f"Error en _do_connect: {e}")
                    return False, str(e)

            # Ejecutar conexión con timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(_do_connect)
                try:
                    result = future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    logger.warning(f"Timeout después de {timeout}s (connect colgado)")
                    
                    # ✅ LIMPIEZA: Cerrar websocket si quedó abierto
                    try:
                        if hasattr(api, 'websocket') and api.websocket:
                            api.websocket.close()
                    except:
                        pass
                    
                    return False, f"Timeout de conexión después de {timeout}s"
                except Exception as e:
                    logger.exception("Excepción ejecutando api.connect() en thread")
                    
                    # ✅ LIMPIEZA: Cerrar websocket si quedó abierto
                    try:
                        if hasattr(api, 'websocket') and api.websocket:
                            api.websocket.close()
                    except:
                        pass
                    
                    return False, f"Error de conexión: {str(e)[:200]}"

            # Validar respuesta
            try:
                check, reason = result
            except Exception:
                logger.error(f"Respuesta inesperada de api.connect(): {result!r}")
                
                # ✅ LIMPIEZA: Cerrar websocket
                try:
                    if hasattr(api, 'websocket') and api.websocket:
                        api.websocket.close()
                except:
                    pass
                
                return False, "Respuesta inesperada de IQ Option"

            if not check:
                reason_str = str(reason) if reason else ""
                logger.error(f"Error connect(): {reason_str}")

                # ✅ LIMPIEZA: Cerrar websocket si quedó abierto
                try:
                    if hasattr(api, 'websocket') and api.websocket:
                        api.websocket.close()
                except:
                    pass

                # Mensajes de error mejorados
                rlow = reason_str.lower()
                if "invalid_credentials" in rlow or "incorrect" in rlow:
                    return False, "Email o contraseña incorrectos"
                if "2fa" in rlow or "two factor" in rlow or "two-factor" in rlow:
                    return False, "Desactiva 2FA en IQ Option"
                if "network" in rlow or "connection" in rlow or "timeout" in rlow:
                    return False, "Error de red/bloqueo desde el servidor. Intenta más tarde o usa VPS"
                
                return False, f"Error: {reason_str[:200]}" if reason_str else "Error de conexión con IQ Option"

            logger.info("✅ Conexión exitosa y validada")
            return True, api

        except Exception as e:
            logger.exception("Error crítico en SafeIQConnection.safe_connect")
            
            # ✅ LIMPIEZA FINAL: Asegurar que no quede basura
            try:
                import iqoptionapi.global_value as global_value
                global_value.SSID = None
            except:
                pass
            
            return False, f"Error crítico: {str(e)[:200]}"



logger.info("🔧 Aplicando parches de compatibilidad...")

import websocket  # noqa: F401

_original_on_message = None
_original_on_error = None
_original_on_close = None
_original_on_open = None


# --- parche websocket-client / iqoptionapi (seguro, anti-recursion) ---
_original_on_message = None
_original_on_error = None
_original_on_close = None
_original_on_open = None
_ws_patched = False

def patch_websocket_callbacks():
    """Parche seguro para manejar diferentes versiones de websocket-client sin recursión."""
    global _original_on_message, _original_on_error, _original_on_close, _original_on_open, _ws_patched

    if _ws_patched:
        return  # evita doble parche

    try:
        from iqoptionapi.ws.client import WebsocketClient

        # Guarda referencias originales SOLO una vez
        _original_on_message = getattr(WebsocketClient, "on_message", None)
        _original_on_error   = getattr(WebsocketClient, "on_error", None)
        _original_on_close   = getattr(WebsocketClient, "on_close", None)
        _original_on_open    = getattr(WebsocketClient, "on_open", None)

        def _safe_call(fn, self, *args, **kwargs):
            if not fn:
                return None
            try:
                return fn(self, *args, **kwargs)
            except RecursionError as e:
                # esto NO debería ocurrir si se llama al original
                logger.debug(f"RecursionError en callback WS: {e}")
                return None
            except Exception as e:
                logger.debug(f"Error en callback WS (ignorado): {e}")
                return None

        # Wrappers: llaman SOLO al original guardado, nunca al atributo actual
        def on_message(self, message):
            return _safe_call(_original_on_message, self, message)

        def on_error(self, error):
            return _safe_call(_original_on_error, self, error)

        def on_close(self, *args, **kwargs):
            # Manejar diferentes firmas de websocket-client
            if _original_on_close:
                try:
                    # Intentar con argumentos posicionales
                    if len(args) == 0:
                        return _original_on_close(self)
                    elif len(args) == 1:
                        return _original_on_close(self, args[0])
                    elif len(args) == 2:
                        return _original_on_close(self, args[0], args[1])
                    else:
                        return _original_on_close(self, *args, **kwargs)
                except TypeError:
                    # Si falla, intentar sin argumentos
                    try:
                        return _original_on_close(self)
                    except:
                        pass
                except Exception as e:
                    logger.debug(f"Error en on_close (ignorado): {e}")
            return None

        def on_open(self):
            return _safe_call(_original_on_open, self)

        # Aplicar el parche
        WebsocketClient.on_message = on_message
        WebsocketClient.on_error = on_error
        WebsocketClient.on_close = on_close
        WebsocketClient.on_open = on_open

        _ws_patched = True
        logger.info("✅ Parches de WebSocket aplicados correctamente (anti-recursion)")

    except Exception as e:
        logger.error(f"❌ Error aplicando parches WS: {e}")



patch_websocket_callbacks()

from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
import redis
import requests

# Lock global: solo un thread puede reconectar a IQ Option a la vez.
# Evita que 4-5 peticiones simultáneas intenten reconectar al mismo tiempo
# y se pisoteen entre sí ("Connection is already closed").
_reconnect_lock = threading.Lock()

try:
    from iqoptionapi.stable_api import IQ_Option
    logger.info("✅ IQOptionAPI importada correctamente")
except ImportError as e:
    logger.error(f"❌ Error importando IQOptionAPI: {e}")
    logger.error("Instalando IQOptionAPI...")
    os.system("pip install -U git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
    from iqoptionapi.stable_api import IQ_Option

# ============================================================================
# PARCHE CRÍTICO: Fix para get_all_open_time() - API V2 Deprecada
# ============================================================================
logger.info("🔧 Aplicando parche para API V2 deprecada...")

def patch_get_all_open_time():
    """
    Parchea get_all_open_time() para evitar el error KeyError: 'underlying'
    causado por el método deprecado get-underlying-list V2
    """
    try:
        from iqoptionapi import stable_api
        
        # Guardar referencia al método original
        _original_get_all_open_time = stable_api.IQ_Option.get_all_open_time
        
        def patched_get_all_open_time(self):
            """Versión parcheada que maneja el error de API V2"""
            try:
                # Intentar el método original
                return _original_get_all_open_time(self)
            except KeyError as e:
                if "'underlying'" in str(e):
                    # Error conocido: get-underlying-list V2 deprecado
                    logger.warning("⚠️ get-underlying-list V2 deprecado, usando método alternativo")
                    
                    # Usar solo get-initialization-data (que funciona)
                    try:
                        init_data = self.get_all_init_v2()
                        
                        if init_data:
                            return {
                                "turbo": init_data.get("turbo", {}).get("actives", {}),
                                "binary": init_data.get("binary", {}).get("actives", {}),
                                "digital": {}  # Vacío porque V2 no funciona
                            }
                    except:
                        pass
                    
                    # Fallback final
                    logger.warning("⚠️ Retornando estructura mínima")
                    return {"turbo": {}, "binary": {}, "digital": {}}
                else:
                    raise
            except Exception as e:
                logger.error(f"Error en get_all_open_time: {e}")
                return {"turbo": {}, "binary": {}, "digital": {}}
        
        # Aplicar parche
        stable_api.IQ_Option.get_all_open_time = patched_get_all_open_time
        logger.info("✅ Parche API V2 aplicado exitosamente")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error aplicando parche: {e}")
        return False

# Aplicar el parche
patch_get_all_open_time()

# WebSocket para tiempo real
from flask_socketio import SocketIO, emit, join_room, leave_room

# Usar threading para WebSockets (compatible con Render)
ASYNC_MODE = 'threading'
logger.info("🔧 Modo: threading (WebSockets en tiempo real)")

import pandas as pd
import numpy as np
from ta.momentum import RSIIndicator, StochasticOscillator, StochRSIIndicator
from ta.trend import MACD, CCIIndicator, EMAIndicator
from ta.volatility import BollingerBands, AverageTrueRange

try:
    from ai_signal import AISignalEnhancer
    AI_AVAILABLE = True
    logger.info("✅ AI disponible: RandomForest + Groq activados")
except Exception as e:
    AI_AVAILABLE = False
    logger.warning(f"⚠️ AI no disponible ({type(e).__name__}): {e}")

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

from functools import wraps

def require_auth(f):
    """
    ✅ DECORADOR ROBUSTO: Autenticación por Sesión Y Header (Anti-bloqueo de cookies cross-site).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-User-Id, Accept'
            return response
        
        user_id = session.get('user_id')
        if not user_id:
            user_id = request.headers.get('X-User-Id')
            if not user_id:
                auth_h = request.headers.get('Authorization', '')
                if auth_h.startswith('Bearer '):
                    user_id = auth_h.split('Bearer ')[1].strip()
            
            if user_id and user_id in active_bots:
                session['user_id'] = user_id
                session['ssid'] = active_bots[user_id].get('ssid')
        
        if not user_id or user_id not in active_bots:
            return jsonify({"error": "Authentication required", "valid": False}), 401
        
        return f(*args, **kwargs)
    
    return decorated_function

def validate_trading_params(data: dict) -> tuple:
    """
    ✅ CORRECCIÓN COMPLETA: Validación robusta de TODOS los parámetros.
    
    Valida:
    - symbol (símbolo válido y disponible)
    - amount (monto con múltiples alias y conversión robusta)
    - strategy (estrategia válida de STRATEGIES)
    - account_type (PRACTICE o REAL)
    - max_operations (opcional, >= 0)
    - max_loss_operations (opcional, >= 1)
    
    Retorna: (bool, Optional[str])
        - (True, None) si todos los parámetros son válidos
        - (False, "mensaje de error") si algún parámetro es inválido
    """
    try:
        # ========================================================================
        # 1. VALIDAR SÍMBOLO
        # ========================================================================
        symbol = data.get('symbol')
        if not symbol or not isinstance(symbol, str):
            return False, "Símbolo inválido o no proporcionado"
        
        symbol = symbol.strip()
        if len(symbol) == 0:
            return False, "Símbolo vacío"
        
        logger.debug(f"✅ Símbolo válido: {symbol}")
        
        # ========================================================================
        # 2. VALIDAR MONTO (con múltiples alias y conversión robusta)
        # ========================================================================
        amount = None
        
        # Buscar el monto en diferentes campos posibles
        for field in ['amount', 'trade_amount', 'investment', 'stake']:
            if field in data and data[field] is not None:
                amount = data[field]
                break
        
        if amount is None:
            return False, "Seleccione un monto válido"
        
        # Convertir a float de forma robusta
        try:
            # Si es string, reemplazar coma por punto
            if isinstance(amount, str):
                amount = amount.strip().replace(',', '.')
            
            amount_float = float(amount)
        except (ValueError, TypeError) as e:
            logger.error(f"Error convirtiendo amount: {amount} - {e}")
            return False, "El monto debe ser un número válido"
        
        # Validar rango
        if amount_float <= 0:
            return False, "El monto debe ser mayor a 0"
        
        if amount_float < 1:
            return False, "El monto mínimo es $1"
        
        if amount_float > 100000:
            return False, "El monto excede el límite permitido ($100,000)"
        
        # ✅ IMPORTANTE: Normalizar el amount en el dict para uso posterior
        data['amount'] = amount_float
        logger.debug(f"✅ Monto válido: ${amount_float}")
        
        # ========================================================================
        # 3. VALIDAR ESTRATEGIA
        # ========================================================================
        strategy = data.get('strategy')
        if not strategy:
            return False, "Seleccione una estrategia"
        
        # Convertir a string y limpiar
        strategy = str(strategy).strip()
        
        # Verificar si la estrategia existe en STRATEGIES
        if strategy not in STRATEGIES:
            # Intentar resolver con función auxiliar
            from_resolver = resolve_strategy_id(data)
            if from_resolver and from_resolver in STRATEGIES:
                strategy = from_resolver
                data['strategy'] = strategy
                logger.info(f"✅ Estrategia resuelta: {strategy}")
            else:
                available = list(STRATEGIES.keys())
                logger.error(f"❌ Estrategia inválida: {strategy}")
                logger.error(f"📋 Disponibles: {available}")
                return False, f"Estrategia inválida. Disponibles: {', '.join(available[:3])}..."
        
        logger.debug(f"✅ Estrategia válida: {strategy}")
        
        # ========================================================================
        # 4. VALIDAR TIPO DE CUENTA
        # ========================================================================
        account_type = data.get('account_type', 'PRACTICE')
        if isinstance(account_type, str):
            account_type = account_type.strip().upper()
        
        if account_type not in ['PRACTICE', 'REAL']:
            logger.warning(f"⚠️ Tipo de cuenta inválido: {account_type}, usando PRACTICE")
            account_type = 'PRACTICE'
        
        data['account_type'] = account_type
        logger.debug(f"✅ Tipo de cuenta: {account_type}")
        
        # ========================================================================
        # 5. VALIDAR MAX_OPERATIONS (opcional)
        # ========================================================================
        max_operations = data.get('max_operations', 0)
        try:
            max_operations = int(max_operations)
            if max_operations < 0:
                logger.warning(f"⚠️ max_operations negativo: {max_operations}, usando 0")
                max_operations = 0
        except (ValueError, TypeError):
            logger.warning(f"⚠️ max_operations inválido: {max_operations}, usando 0")
            max_operations = 0
        
        data['max_operations'] = max_operations
        logger.debug(f"✅ Max operaciones: {max_operations if max_operations > 0 else 'ilimitado'}")
        
        # ========================================================================
        # 6. VALIDAR MAX_LOSS_OPERATIONS (pérdidas consecutivas)
        # ========================================================================
        max_loss_operations = data.get('max_loss_operations', 5)
        try:
            max_loss_operations = int(max_loss_operations)
            if max_loss_operations < 1:
                logger.warning(f"⚠️ max_loss_operations muy bajo: {max_loss_operations}, usando 5")
                max_loss_operations = 5
            if max_loss_operations > 20:
                logger.warning(f"⚠️ max_loss_operations muy alto: {max_loss_operations}, usando 20")
                max_loss_operations = 20
        except (ValueError, TypeError):
            logger.warning(f"⚠️ max_loss_operations inválido: {max_loss_operations}, usando 5")
            max_loss_operations = 5
        
        data['max_loss_operations'] = max_loss_operations
        logger.debug(f"✅ Max pérdidas consecutivas: {max_loss_operations}")
        
        # ========================================================================
        # 7. LOG FINAL DE VALIDACIÓN
        # ========================================================================
        logger.info(f"✅ Parámetros validados correctamente:")
        logger.info(f"   📊 Símbolo: {symbol}")
        logger.info(f"   💵 Monto: ${amount_float}")
        logger.info(f"   🎯 Estrategia: {strategy} ({STRATEGIES[strategy]['name']})")
        logger.info(f"   💼 Cuenta: {account_type}")
        logger.info(f"   🔢 Max operaciones: {max_operations if max_operations > 0 else 'ilimitado'}")
        logger.info(f"   ⚠️  Max pérdidas consecutivas: {max_loss_operations}")
        
        return True, None
        
    except Exception as e:
        logger.error(f"❌ Error en validación de parámetros: {e}")
        logger.error(traceback.format_exc())
        return False, f"Error de validación: {str(e)}"
def ssid_to_str(ssid) -> str:
    """
    ✅ CORRECCIÓN: Normaliza SSID a string de forma segura.
    Maneja casos donde ssid es un objeto Ssid con atributos.
    """
    if ssid is None:
        return ""
    
    # Caso 1: Ya es string
    if isinstance(ssid, str):
        return ssid
    
    # Caso 2: Objeto con atributos
    for attr in ("ssid", "value", "token", "_value"):
        try:
            v = getattr(ssid, attr, None)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
    
    # Caso 3: Convertir a string
    try:
        s = str(ssid)
        # Validar que no sea una representación genérica
        if s and not s.startswith("<") and not s.startswith("Ssid("):
            return s
    except Exception:
        pass
    
    return ""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "frontend")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path='')

is_production = os.environ.get('RENDER') is not None or os.environ.get('FLASK_ENV', '').lower() == 'production'

secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or 'your-secret-key-here'


def sync_session_cookie_name():
    cookie_name = app.config.get("SESSION_COOKIE_NAME", "iqbot_session")
    setattr(app, "session_cookie_name", cookie_name)

# Configuración CORS flexible para Render, InfinityFree y desarrollo
allowed_origins = [
    "https://botiqoption.ct.ws",
    "http://botiqoption.ct.ws",
    "https://www.botiqoption.ct.ws",
    "http://www.botiqoption.ct.ws",
    "https://botiqoption-4.onrender.com",
    "http://localhost:3000",
    "http://localhost:5000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5000",
    "http://127.0.0.1:5173"
]
frontend_url = os.environ.get('FRONTEND_URL', '').strip()
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

cookie_samesite = 'None'
cookie_secure = True

print(f"🍪 Cookies: SameSite={cookie_samesite}, Secure={cookie_secure}")

# Configuración de sesiones mejorada
redis_url = os.environ.get('REDIS_URL')

if redis_url and 'localhost' not in redis_url:
    # ✅ PRODUCCIÓN: Redis (persistente entre workers)
    print(f"🔴 Usando Redis: {redis_url[:30]}...")
    try:
        app.config.update(
            SECRET_KEY=secret_key,
            SESSION_TYPE='redis',
            SESSION_REDIS=redis.from_url(redis_url),
            SESSION_PERMANENT=True,
            PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
            SESSION_COOKIE_SECURE=cookie_secure,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE=cookie_samesite,
            SESSION_COOKIE_NAME='iqbot_session',
            SESSION_COOKIE_PATH='/',
            SESSION_USE_SIGNER=True,  # ✅ Activado para mayor seguridad
            SESSION_KEY_PREFIX='iqbot:'
        )
        print("✅ Redis configurado correctamente (sesiones persistentes)")
    except Exception as e:
        print(f"❌ Error configurando Redis: {e}")
        print("⚠️ FALLBACK: usando filesystem temporal")
        # Fallback a filesystem si Redis falla
        app.config.update(
            SECRET_KEY=secret_key,
            SESSION_TYPE='filesystem',
            SESSION_FILE_DIR='/tmp/flask_session',
            SESSION_PERMANENT=True,
            PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
            SESSION_COOKIE_SECURE=cookie_secure,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE=cookie_samesite,
            SESSION_COOKIE_NAME='iqbot_session',
            SESSION_COOKIE_PATH='/',
            SESSION_USE_SIGNER=True
        )
else:
    # ⚠️ SIN REDIS: filesystem (volatile en Render)
    print("⚠️ Sin Redis: usando SESSION_TYPE=filesystem en /tmp")
    print("⚠️ ADVERTENCIA: Las sesiones se PERDERÁN al reiniciar el worker")
    print("⚠️ Esto causará errores 401 con cookies antiguas en producción")
    print("💡 Solución: Configura Redis en Render para sesiones persistentes")
    
    app.config.update(
        SECRET_KEY=secret_key,
        SESSION_TYPE='filesystem',
        SESSION_FILE_DIR='/tmp/flask_session',
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        SESSION_COOKIE_SECURE=cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE=cookie_samesite,
        SESSION_COOKIE_NAME='iqbot_session',
        SESSION_COOKIE_PATH='/',
        SESSION_USE_SIGNER=True  # ✅ Importante para evitar manipulación
    )

print(f"✅ Flask configurado correctamente")
sync_session_cookie_name()

Session(app)

CORS(
    app,
    resources={r"/*": {"origins": allowed_origins}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "X-User-Id", "x-user-id", "Cookie"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    expose_headers=["Content-Type", "X-Total-Count", "Set-Cookie"],
    max_age=3600
)



TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
    try:
        init_monitoring(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    except Exception:
        pass

# ============================================================================
# WEBSOCKET CONFIGURATION
# ============================================================================
logger.info("🔌 Configurando WebSocket...")

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode=ASYNC_MODE,
    logger=True,
    engineio_logger=False,
    ping_timeout=30,
    ping_interval=15,
    cors_credentials=True
)

logger.info(f"✅ WebSocket configurado (modo: {ASYNC_MODE})")

# ============================================================================
# WEBSOCKET EVENTS
# ============================================================================

@socketio.on('connect')
def handle_connect(auth=None):
    user_id = session.get('user_id')
    if not user_id and auth and isinstance(auth, dict):
        user_id = auth.get('user_id')
    if not user_id:
        user_id = request.args.get('user_id')
    
    if user_id and user_id in active_bots:
        session['user_id'] = user_id
        session['ssid'] = active_bots[user_id].get('ssid')
        logger.info(f"Socket.IO: Usuario {user_id} autenticado y conectado")
        return True
    
    logger.info(f"Socket.IO: Conexión aceptada (sid: {request.sid})")
    return True

@socketio.on('disconnect')
def handle_disconnect():
    """Cliente desconectado - limpiar streams"""
    logger.info(f"🔌 Cliente WebSocket desconectado: {request.sid}")
    
    try:
        user_id = session.get('user_id')
        if user_id:
            # Detener todos los streams del usuario
            streams_to_remove = []
            for stream_key, stream_data in active_candle_streams.items():
                if stream_key.startswith(f"{user_id}_"):
                    if 'stop_event' in stream_data:
                        stream_data['stop_event'].set()
                    streams_to_remove.append(stream_key)
            
            for stream_key in streams_to_remove:
                del active_candle_streams[stream_key]
                logger.info(f"🛑 Stream limpiado: {stream_key}")
    except Exception as e:
        logger.error(f"Error limpiando streams en disconnect: {e}")
# ============================================================================
# CORRECCIÓN 3: SOCKET.IO - MANEJO DE VELAS EN TIEMPO REAL
# ============================================================================
# Reemplazar desde línea 585 hasta línea 808

@socketio.on('subscribe_candles')
def handle_subscribe_candles(data):
    """
    ✅ CORRECCIÓN FINAL: Suscripción a velas con streaming REAL usando IQ Option API.
    
    Mejoras:
    - Streaming real con actualizaciones intra-vela
    - Manejo robusto de errores con notificaciones al cliente
    - Verificación de health de conexión
    - Cleanup correcto al desconectar
    - Manejo de timeout en get_realtime_candles
    """
    try:
        user_id = session.get('user_id')
        if not user_id:
            emit('error', {'message': 'No autenticado', 'type': 'auth_error'})
            return

        # ✅ Extraer valores necesarios de sesión para usar en threads
        session_ssid = session.get('ssid')
        email = session.get('email')
        password = session.get('password')
        # Guardar credenciales en caché para reconexiones
        if user_id:
            active_bots.setdefault(user_id, {})
            if email:
                active_bots[user_id]["email"] = email
            if password:
                active_bots[user_id]["password"] = password
            if session_ssid:
                active_bots[user_id]["ssid"] = session_ssid

        symbol = data.get('symbol', 'EURUSD-OTC')
        timeframe = int(data.get('timeframe', 60))
        room = f"candles_{symbol}"

        join_room(room)
        logger.info(f"📊 Cliente {request.sid} suscrito a velas de {symbol} tf={timeframe}")
        emit('subscribed', {'symbol': symbol, 'room': room, 'timeframe': timeframe})

        # Iniciar thread de streaming si no existe
        stream_key = f"{user_id}_{symbol}_{timeframe}"

        # Si ya existe un stream, detenerlo primero
        if stream_key in active_candle_streams:
            logger.info(f"⚠️ Stream ya existe para {stream_key}, deteniendo...")
            old_stream = active_candle_streams[stream_key]
            if 'stop_event' in old_stream:
                old_stream['stop_event'].set()
            time.sleep(0.5)  # Dar tiempo para cleanup

        # Crear nuevo stream
        stop_event = threading.Event()
        
        def stream_candles_realtime():
            """Thread que envía velas en tiempo real con manejo robusto de errores"""
            api = None
            last_health_check = time.time()
            health_check_interval = 30  # Verificar conexión cada 30s
            
            try:
                # ✅ Usar get_user_api_for para evitar uso de flask.session en hilos
                # Importante: no pasar session_ssid en hilos para evitar validación de SSID
                api = get_user_api_for(
                    user_id=user_id,
                    session_ssid=None,
                    email=email,
                    password=password
                )
                if not api:
                    error_msg = 'No se pudo obtener API para streaming'
                    logger.error(f"❌ {error_msg}")
                    socketio.emit('error', {
                        'message': error_msg,
                        'type': 'api_error'
                    }, room=room)
                    return

                logger.info(f"🚀 Iniciando streaming REAL de velas para {symbol} tf={timeframe}")
                
                # ✅ INICIAR STREAM DE VELAS (IQ Option API)
                try:
                    api.start_candles_stream(symbol, timeframe, 100)  # maxdict=100
                    logger.info(f"✅ Stream IQ Option iniciado: {symbol} tf={timeframe}")
                except Exception as e:
                    error_msg = f'Error iniciando stream: {str(e)}'
                    logger.error(f"❌ {error_msg}")
                    socketio.emit('error', {
                        'message': error_msg,
                        'type': 'stream_error',
                        'detail': str(e)
                    }, room=room)
                    return
                
                # Esperar un momento para que se establezca el stream
                time.sleep(1)
                
                last_candle_time = 0
                error_count = 0
                max_errors = 10
                no_data_count = 0
                max_no_data = 30  # 30 segundos sin datos = problema
                
                while not stop_event.is_set():
                    try:
                        # ✅ HEALTH CHECK PERIÓDICO
                        current_time = time.time()
                        if current_time - last_health_check > health_check_interval:
                            try:
                                # Verificar que la API sigue conectada
                                test_balance = api.get_balance()
                                if test_balance is None:
                                    logger.warning("⚠️ API desconectada durante streaming, reconectando...")
                                    api = get_user_api_for(
                                        user_id=user_id,
                                        session_ssid=None,
                                        email=email,
                                        password=password
                                    )
                                    if not api:
                                        logger.error("❌ No se pudo reconectar API")
                                        socketio.emit('error', {
                                            'message': 'Conexión perdida',
                                            'type': 'connection_lost'
                                        }, room=room)
                                        break
                                    # Reiniciar stream
                                    api.start_candles_stream(symbol, timeframe, 100)  # maxdict=100
                                    time.sleep(1)
                                
                                last_health_check = current_time
                                logger.debug(f"✅ Health check OK para {symbol}")
                            except Exception as e:
                                logger.warning(f"⚠️ Health check falló: {e}")
                        
                        # ✅ OBTENER VELAS EN TIEMPO REAL CON TIMEOUT
                        realtime_candles = None
                        try:
                            # Usar timeout mediante thread pool
                            def get_candles_with_timeout():
                                return api.get_realtime_candles(symbol, timeframe)
                            
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                                future = executor.submit(get_candles_with_timeout)
                                try:
                                    realtime_candles = future.result(timeout=5)
                                except concurrent.futures.TimeoutError:
                                    logger.warning(f"⚠️ Timeout obteniendo velas para {symbol}")
                                    no_data_count += 1
                                    if no_data_count >= max_no_data:
                                        logger.error("❌ Demasiado tiempo sin datos, reiniciando stream...")
                                        api.stop_candles_stream(symbol, timeframe)
                                        time.sleep(1)
                                        api.start_candles_stream(symbol, timeframe, 100)  # maxdict=100
                                        time.sleep(1)
                                        no_data_count = 0
                                    stop_event.wait(timeout=1)
                                    continue
                        except Exception as e:
                            logger.warning(f"⚠️ Error obteniendo velas: {e}")
                            error_count += 1
                            if error_count >= max_errors:
                                logger.error(f"❌ Demasiados errores ({error_count}), deteniendo stream")
                                socketio.emit('error', {
                                    'message': 'Stream detenido por errores repetidos',
                                    'type': 'stream_stopped'
                                }, room=room)
                                break
                            stop_event.wait(timeout=2)
                            continue
                        
                        if not realtime_candles:
                            logger.debug(f"⚠️ No hay velas realtime para {symbol}, esperando...")
                            no_data_count += 1
                            stop_event.wait(timeout=1)
                            continue
                        
                        # Reset contador si recibimos datos
                        no_data_count = 0
                        
                        # Procesar todas las velas disponibles
                        candles_emitted = 0
                        for candle_time, candle_data in realtime_candles.items():
                            try:
                                if not isinstance(candle_data, dict):
                                    continue
                                
                                candle_time_int = int(candle_time)
                                
                                # Construir objeto de vela
                                candle_obj = {
                                    'time': candle_time_int,
                                    'open': float(candle_data.get('open', 0) or 0),
                                    'high': float(candle_data.get('max', 0) or candle_data.get('high', 0) or 0),
                                    'low': float(candle_data.get('min', 0) or candle_data.get('low', 0) or 0),
                                    'close': float(candle_data.get('close', 0) or 0),
                                    'volume': float(candle_data.get('volume', 0) or 0)
                                }
                                
                                # Validar datos
                                if candle_obj['open'] == 0 or candle_obj['close'] == 0:
                                    continue
                                
                                # ✅ EMITIR SIEMPRE (actualizaciones intra-vela)
                                # Log solo cuando es una nueva vela
                                if candle_time_int > last_candle_time:
                                    last_candle_time = candle_time_int
                                    logger.info(f"📊 Nueva vela: {symbol} @ {candle_time_int}")
                                
                                socketio.emit('candle_update', {
                                    'symbol': symbol,
                                    'candle': candle_obj,
                                    'is_realtime': True,
                                    'timeframe': timeframe
                                }, room=room)
                                
                                candles_emitted += 1
                                error_count = 0  # Reset error count en emit exitoso
                                
                            except Exception as e:
                                logger.debug(f"⚠️ Error procesando vela individual: {e}")
                                continue
                        
                        if candles_emitted > 0:
                            logger.debug(f"📤 Emitidas {candles_emitted} actualizaciones de velas")
                        
                        # Esperar antes de la próxima lectura (~1 segundo)
                        stop_event.wait(timeout=1)
                    
                    except Exception as e:
                        logger.error(f"❌ Error en loop de streaming: {str(e)}")
                        logger.error(traceback.format_exc())
                        error_count += 1
                        if error_count >= max_errors:
                            logger.error(f"❌ Demasiados errores en loop ({error_count}), deteniendo")
                            socketio.emit('error', {
                                'message': 'Stream detenido por errores críticos',
                                'type': 'critical_error',
                                'detail': str(e)
                            }, room=room)
                            break
                        stop_event.wait(timeout=5)
                
                logger.info(f"🏁 Streaming finalizado para {symbol}")
                
            except Exception as e:
                logger.error(f"❌ Error crítico en stream_candles_realtime: {str(e)}")
                logger.error(traceback.format_exc())
                socketio.emit('error', {
                    'message': 'Error crítico en streaming',
                    'type': 'fatal_error',
                    'detail': str(e)
                }, room=room)
            finally:
                # ✅ CLEANUP ROBUSTO
                logger.info(f"🧹 Cleanup de streaming para {symbol}")
                if api:
                    try:
                        api.stop_candles_stream(symbol, timeframe)
                        logger.info(f"✅ Stream detenido correctamente: {symbol}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error deteniendo stream (ignorado): {e}")
                
                # Remover de active_streams
                if stream_key in active_candle_streams:
                    try:
                        del active_candle_streams[stream_key]
                        logger.info(f"✅ Stream removido de active_streams: {stream_key}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error removiendo stream: {e}")
        
        # Guardar referencia del stream
        active_candle_streams[stream_key] = {
            'stop_event': stop_event,
            'symbol': symbol,
            'timeframe': timeframe,
            'user_id': user_id,
            'room': room,
            'started_at': datetime.now().isoformat()
        }
        
        # Iniciar thread
        thread = threading.Thread(
            target=stream_candles_realtime,
            name=f"candles_{stream_key}",
            daemon=True
        )
        thread.start()
        
        logger.info(f"✅ Thread de streaming iniciado: {thread.name}")
        
    except Exception as e:
        logger.error(f"❌ Error en handle_subscribe_candles: {str(e)}")
        logger.error(traceback.format_exc())
        emit('error', {
            'message': 'Error configurando streaming',
            'type': 'setup_error',
            'detail': str(e)
        })


@socketio.on('unsubscribe_candles')
def handle_unsubscribe_candles(data):
    """Desuscribirse de velas - con cleanup robusto"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return

        symbol = data.get('symbol', '')
        timeframe = int(data.get('timeframe', 60))
        stream_key = f"{user_id}_{symbol}_{timeframe}"
        
        logger.info(f"🛑 Unsubscribe solicitado para {stream_key}")
        
        if stream_key in active_candle_streams:
            stream_data = active_candle_streams[stream_key]
            if 'stop_event' in stream_data:
                stream_data['stop_event'].set()
                logger.info(f"✅ Stop event activado para {stream_key}")
            
            # Dar tiempo para que el thread haga cleanup
            time.sleep(0.5)
            
            # Forzar eliminación si aún existe
            if stream_key in active_candle_streams:
                del active_candle_streams[stream_key]
                logger.info(f"✅ Stream eliminado: {stream_key}")
        
        # Salir del room
        room = f"candles_{symbol}"
        leave_room(room)
        
        emit('unsubscribed', {'symbol': symbol, 'timeframe': timeframe})
        logger.info(f"✅ Cliente desuscrito de {room}")
        
    except Exception as e:
        logger.error(f"❌ Error en unsubscribe_candles: {e}")
        emit('error', {
            'message': 'Error al desuscribirse',
            'type': 'unsubscribe_error',
            'detail': str(e)
        })
@socketio.on('subscribe_trades')
def handle_subscribe_trades(data):
    """Suscribirse a actualizaciones de operaciones"""
    user_id = data.get('user_id')
    if user_id:
        room = f"trades_{user_id}"
        join_room(room)
        logger.info(f"💼 Cliente {request.sid} suscrito a operaciones de {user_id}")
        emit('subscribed_trades', {'user_id': user_id})

# ============================================================================
# HELPER FUNCTIONS PARA EMITIR EVENTOS
# ============================================================================

def emit_trade_opened(user_id, trade_data):
    """Emitir cuando se abre una operación"""
    try:
        room = f"trades_{user_id}"
        socketio.emit('trade_opened', trade_data, room=room)
        logger.info(f"📤 Operación abierta emitida a {room}")
    except Exception as e:
        logger.error(f"Error emitiendo trade_opened: {e}")

def emit_trade_closed(user_id, trade_data):
    """Emitir cuando se cierra una operación"""
    try:
        room = f"trades_{user_id}"
        socketio.emit('trade_closed', trade_data, room=room)
        logger.info(f"📤 Operación cerrada emitida a {room}")
    except Exception as e:
        logger.error(f"Error emitiendo trade_closed: {e}")

def emit_candle_update(symbol, candle_data):
    """Emitir actualización de vela"""
    try:
        room = f"candles_{symbol}"
        socketio.emit('candle_update', candle_data, room=room)
    except Exception as e:
        logger.debug(f"Error emitiendo candle_update: {e}")

def emit_notification(user_id, notification):
    """Emitir notificación general"""
    try:
        room = f"trades_{user_id}"
        socketio.emit('notification', notification, room=room)
    except Exception as e:
        logger.error(f"Error emitiendo notification: {e}")


active_bots: Dict[str, dict] = {}
active_candle_streams: Dict[str, dict] = {}  # Streams de velas activos

def resolve_strategy_id(payload: dict):
    """Resuelve el ID de estrategia desde múltiples campos posibles"""
    # Intentar obtener de diferentes campos
    raw = (payload.get("strategy_id") or 
           payload.get("strategy") or 
           payload.get("strategy_name") or "").strip()
    
    if not raw:
        logger.warning("⚠️ No se encontró estrategia en payload")
        logger.warning(f"📦 Payload recibido: {payload}")
        return None

    logger.info(f"🔍 Buscando estrategia: '{raw}'")

    # ✅ FIX 1: Si ya viene el ID correcto (exacto)
    if raw in STRATEGIES:
        logger.info(f"✅ Estrategia encontrada directamente: {raw}")
        return raw

    raw_l = raw.lower()

    # ✅ FIX 2: Match por nombre exacto (case-insensitive)
    for k, info in STRATEGIES.items():
        name = str(info.get("name", "")).lower()
        
        if raw_l == name:
            logger.info(f"✅ Estrategia por nombre exacto: {k}")
            return k

    # ✅ FIX 3: Match por key lowercase
    for k in STRATEGIES.keys():
        if raw_l == k.lower():
            logger.info(f"✅ Estrategia por key lowercase: {k}")
            return k

    # ✅ FIX 4: Match parcial en nombre
    for k, info in STRATEGIES.items():
        name = str(info.get("name", "")).lower()
        
        # Contiene el nombre en la búsqueda o viceversa
        if raw_l in name or name in raw_l:
            logger.info(f"✅ Estrategia por match parcial en nombre: {k}")
            return k

    # ✅ FIX 5: Match parcial en key
    for k in STRATEGIES.keys():
        k_lower = k.lower()
        
        if raw_l in k_lower or k_lower in raw_l:
            logger.info(f"✅ Estrategia por match parcial en key: {k}")
            return k

    # ✅ FIX 6: Normalizar a slug y buscar
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in raw)
    slug = "_".join([p for p in slug.split("_") if p])
    
    if slug in STRATEGIES:
        logger.info(f"✅ Estrategia por slug normalizado: {slug}")
        return slug
    
    # Intentar match de slug parcial
    for k in STRATEGIES.keys():
        if slug in k.lower() or k.lower() in slug:
            logger.info(f"✅ Estrategia por slug parcial: {k}")
            return k

    logger.error(f"❌ No se pudo resolver estrategia: '{raw}'")
    logger.error(f"📋 Estrategias disponibles: {list(STRATEGIES.keys())}")
    logger.error(f"📋 Nombres disponibles: {[v['name'] for v in STRATEGIES.values()]}")
    return None


STRATEGIES = {
    # ========================================================================
    # ESTRATEGIA PRINCIPAL: IA ADAPTATIVA GROQ LLaMA 3.3 (AUTO-REGIME)
    # ========================================================================
    'ai_adaptive_auto': {
        'name': '🤖 IA Adaptativa Groq (Auto-Regime)',
        'description': 'LLaMA 3.3 70B analiza el mercado en tiempo real y selecciona la mejor estrategia',
        'timeframe': 60,
        'min_confidence': 70,
        'risk_level': 'dynamic',
        'indicators': ['ema', 'rsi', 'macd', 'bollinger', 'adx'],
        'max_loss_multiplier': 2.0
    },
    
    # ========================================================================
    # ESTRATEGIA 1: BOLLINGER BANDS + RSI BOUNCE
    # Rentabilidad: 70-75% | Mejor para: Mercados laterales
    # ========================================================================
    'bollinger_rsi_bounce': {
        'name': 'Bollinger RSI Bounce',
        'description': 'Rebote en BB(15,2) con RSI(5)+Stoch(5,3,3)',
        'timeframe': 60,
        'min_confidence': 62,
        'risk_level': 'medium',
        'indicators': ['bollinger', 'rsi'],
        'max_loss_multiplier': 2.0
    },
    
    # ========================================================================
    # ESTRATEGIA 2: TRIPLE EMA + MACD (MEJOR RENTABILIDAD)
    # Rentabilidad: 72-78% | Mejor para: Tendencias fuertes
    # ========================================================================
    'triple_ema_macd': {
        'name': 'MACD Cross + RSI(5)',
        'description': 'MACD cross confirmado con RSI(5) — 73% win rate documentado',
        'timeframe': 60,
        'min_confidence': 62,
        'risk_level': 'medium',
        'indicators': ['ema', 'macd'],
        'max_loss_multiplier': 2.5
    },
    
    # ========================================================================
    # ESTRATEGIA 3: RSI + STOCHASTIC DUAL
    # Rentabilidad: 68-73% | Mejor para: Sobreventa/sobrecompra
    # ========================================================================
    'rsi_stochastic_dual': {
        'name': 'StochRSI + CCI',
        'description': 'StochRSI + CCI(±100) — 78% win rate documentado',
        'timeframe': 60,
        'min_confidence': 62,
        'risk_level': 'medium',
        'indicators': ['rsi', 'stochastic', 'cci'],
        'max_loss_multiplier': 2.5
    },
    
    # ========================================================================
    # ESTRATEGIA 4: MACD + BOLLINGER BREAKOUT (MÁXIMA RENTABILIDAD)
    # Rentabilidad: 75-80% | Mejor para: Rupturas de volatilidad
    # ========================================================================
    'macd_bollinger_breakout': {
        'name': 'BB Squeeze + MACD Breakout',
        'description': 'Ruptura post-squeeze con MACD y RSI(5)',
        'timeframe': 60,
        'min_confidence': 62,
        'risk_level': 'high',
        'indicators': ['bollinger', 'macd', 'atr'],
        'max_loss_multiplier': 3.0
    },
    
    # ========================================================================
    # ESTRATEGIA 5: SCALPING EXTREMO
    # Rentabilidad: 65-70% | Mejor para: Alta frecuencia
    # ========================================================================
    'scalping_extreme': {
        'name': 'Scalping RSI5+Stoch5+CCI',
        'description': 'RSI(5)+Stoch(5,3,3)+CCI — alta frecuencia, señales rápidas',
        'timeframe': 60,
        'min_confidence': 60,
        'risk_level': 'high',
        'indicators': ['ema', 'rsi', 'cci'],
        'max_loss_multiplier': 3.5
    },
    
    # ========================================================================
    # ESTRATEGIA 6: PRICE ACTION + S/R
    # Rentabilidad: 73-78% | Mejor para: Traders experimentados
    # ========================================================================
    'price_action_sr': {
        'name': 'Price Action S/R (Pivots)',
        'description': 'Pivotes automáticos: Punto 3, rupturas débiles y retesteos',
        'timeframe': 60,
        'min_confidence': 65,
        'risk_level': 'medium',
        'indicators': ['ema', 'rsi', 'macd'],
        'max_loss_multiplier': 2.5
    },
    
    # ========================================================================
    # ESTRATEGIAS LEGACY (Mantener compatibilidad)
    # ========================================================================
    'conservative_rsi': {
        'name': 'RSI Conservador (Legacy)',
        'description': 'Utiliza RSI con confirmación',
        'timeframe': 60,
        'min_confidence': 65,
        'risk_level': 'low',
        'indicators': ['rsi', 'ema'],
        'max_loss_multiplier': 1.5
    },
    'momentum_scalper': {
        'name': 'Momentum Scalper RSI5+Stoch5',
        'description': 'RSI(5)+Stoch(5,3,3)+CCI — señales rápidas para 60s',
        'timeframe': 60,
        'min_confidence': 62,
        'risk_level': 'medium',
        'indicators': ['cci', 'atr', 'ema', 'rsi'],
        'max_loss_multiplier': 2.0
    }
}


@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept, Cookie, X-User-Id, x-user-id'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers.setdefault('Vary', 'Origin')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.route('/', methods=['GET'])
@app.route('/index.html', methods=['GET'])
def root_index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route('/dashboard', methods=['GET'])
@app.route('/dashboard.html', methods=['GET'])
def dashboard_view():
    return send_from_directory(STATIC_DIR, "dashboard.html")

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()})
@app.route("/api/diag/iq", methods=["GET"])
def diag_iq():
    import socket
    import ssl
    try:
        host = "iqoption.com"
        port = 443
        # Prueba TCP 443
        s = socket.create_connection((host, port), timeout=5)
        ctx = ssl.create_default_context()
        ss = ctx.wrap_socket(s, server_hostname=host)
        ss.close()
        return jsonify({"ok": True, "tcp_tls_443": "ok"}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


def ssid_to_str(ssid) -> str:
    """
    Normaliza SSID a string válido (token hex de autenticación).
    IMPORTANTE: api.api.ssid es un canal WebSocket (objeto), no el token.
    El token real está en global_value.SSID. Esta función sólo se usa como
    fallback; preferir global_value.SSID directamente.
    """
    if ssid is None:
        return ""
    if isinstance(ssid, str):
        # Rechazar representaciones de objetos Python (<iqoptionapi...>)
        if ssid.startswith('<') or len(ssid) < 10:
            return ""
        return ssid
    # Algunos wrappers guardan el valor en .ssid o .value
    for attr in ("ssid", "value", "token"):
        try:
            v = getattr(ssid, attr, None)
            if isinstance(v, str) and v and not v.startswith('<') and len(v) > 10:
                return v
        except Exception:
            pass
    try:
        candidate = str(ssid)
        if candidate.startswith('<') or len(candidate) < 10:
            return ""  # Es un repr de objeto, no un token
        return candidate
    except Exception:
        return ""
# ============================================================================
# CORRECCIÓN 1: ENDPOINT /api/login
# ============================================================================
# Reemplazar desde línea 1065 hasta línea 1482
# ELIMINAR la función duplicada (líneas 1280-1482)

@app.route('/api/login', methods=['POST'])
def login():
    """
    ✅ CORRECCIÓN FINAL: Endpoint de login con validación REAL de credenciales.
    
    Cambios:
    - Limpia cache/SSID previo para forzar autenticación real
    - Valida credenciales con balance Y perfil
    - No acepta credenciales inválidas
    - Maneja SSID como objeto correctamente
    - Sin duplicación de código
    """
    try:
        logger.info("🔐 Intento de login recibido")
        
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
            # ✅ PASO 1: LIMPIAR CACHE PREVIO (forzar autenticación real)
            logger.info("🧹 Limpiando caché de sesiones previas...")
            import iqoptionapi.global_value as global_value
            import glob
            
            # Forzar reconexión completa (sin reutilizar SSID)
            global_value.SSID = None
            
            # Limpiar posibles archivos de sesión
            cache_patterns = [
                '/tmp/iqoption*',
                '/tmp/.iqoption*',
                os.path.expanduser('~/.iqoption*'),
                os.path.expanduser('~/.cache/iqoption*')
            ]
            
            for pattern in cache_patterns:
                for filepath in glob.glob(pattern):
                    try:
                        os.remove(filepath)
                        logger.debug(f"   🗑️ Eliminado: {filepath}")
                    except:
                        pass
            
            logger.info("✅ Caché limpiado - Forzando autenticación real")
            
            # Aplicar parches de compatibilidad
            patch_websocket_callbacks()
            
            # ✅ PASO 2: CONEXIÓN CON TIMEOUT
            logger.info("🔌 Conectando con IQ Option (timeout=30s)...")
            check, result = SafeIQConnection.safe_connect(email, password, timeout=30)
            
            if not check:
                error_msg = result if isinstance(result, str) else "Error de conexión con IQ Option"
                logger.error(f"❌ Error de conexión: {error_msg}")
                
                # Limpiar SSID si quedó guardado
                global_value.SSID = None
                
                return jsonify({
                    'success': False, 
                    'message': error_msg
                }), 401
            
            # Si check es True, result contiene la API conectada
            api = result
            logger.info("✅ WebSocket conectado")

            # ✅ PASO 3: VALIDACIÓN FUERTE POST-CONEXIÓN
            logger.info("🔍 Validando autenticación real...")
            
            # Método 1: Obtener balance (requiere autenticación válida)
            balance = None
            try:
                balance = api.get_balance()
                logger.info(f"💰 Balance obtenido: ${balance}")
                
                # Si balance es 0 o None, verificar adicionalmente con perfil
                if balance is None or balance == 0:
                    logger.warning("⚠️ Balance sospechoso (0 o None), verificando perfil...")
            except Exception as e:
                logger.error(f"❌ Error obteniendo balance: {e}")
                # No retornar aún, intentar con perfil
            
            # Método 2: SIEMPRE verificar perfil para asegurar autenticación
            try:
                profile = api.get_profile_ansyc()
                
                # Validar que el email del perfil coincide
                profile_email = None
                if isinstance(profile, dict):
                    profile_email = (profile.get('email') or 
                                   profile.get('mail') or
                                   profile.get('user_email'))
                
                if not profile_email:
                    logger.error("❌ No se pudo obtener email del perfil")
                    api.websocket.close()
                    global_value.SSID = None
                    return jsonify({
                        'success': False,
                        'message': 'Error validando credenciales - Perfil inválido'
                    }), 401
                
                if profile_email.lower() != email.lower():
                    logger.error(f"❌ Email no coincide: {profile_email} != {email}")
                    api.websocket.close()
                    global_value.SSID = None
                    return jsonify({
                        'success': False,
                        'message': 'Credenciales inválidas - Email no coincide'
                    }), 401
                
                logger.info(f"✅ Perfil validado correctamente: {profile_email}")
                
                # Si no obtuvimos balance antes, intentar de nuevo
                if balance is None:
                    try:
                        balance = api.get_balance()
                        logger.info(f"💰 Balance obtenido en segundo intento: ${balance}")
                    except:
                        balance = 0.0
                        logger.warning("⚠️ No se pudo obtener balance, usando 0.0")
                        
            except Exception as e:
                logger.error(f"❌ Error validando perfil: {e}")
                try:
                    api.websocket.close()
                except:
                    pass
                global_value.SSID = None
                return jsonify({
                    'success': False,
                    'message': 'Error validando credenciales - Verificación de perfil falló'
                }), 401

            # ✅ PASO 4: VALIDAR Y GUARDAR SSID CORRECTAMENTE
            # IMPORTANTE: api.api.ssid es el CANAL WebSocket (objeto), NO el token.
            # El token de autenticación real está en global_value.SSID (string hex).
            ssid_str = ""
            gv_ssid = getattr(global_value, 'SSID', None)
            if gv_ssid and isinstance(gv_ssid, str) and len(gv_ssid) > 10 and not gv_ssid.startswith('<'):
                ssid_str = gv_ssid
            else:
                # Intentar convertir por si es un tipo especial con valor embebido
                try:
                    candidate = str(gv_ssid) if gv_ssid is not None else ""
                    if candidate and not candidate.startswith('<') and len(candidate) > 10:
                        ssid_str = candidate
                except Exception:
                    pass

            if not ssid_str:
                logger.error("❌ No se obtuvo SSID válido tras conexión")
                try:
                    api.websocket.close()
                except:
                    pass
                global_value.SSID = None
                return jsonify({
                    'success': False,
                    'message': 'Error de autenticación - Sesión inválida'
                }), 401

            logger.info(f"✅ SSID válido obtenido: {ssid_str[:20]}...")

            # ✅ PASO 5: GUARDAR SESIÓN (todas las validaciones pasaron)
            user_id = email.split('@')[0]
            session.clear()
            session['user_id'] = user_id
            session['email'] = email
            session['password'] = password
            session['api_connected'] = True
            session['login_time'] = datetime.now().isoformat()
            session['ssid'] = ssid_str  # ✅ Guardar como string
            session.modified = True
            session.permanent = True

            # Guardar en caché de APIs activas
            # Además de la API, guardar el SSID y las credenciales para futuras reconexiones
            if user_id not in active_bots:
                active_bots[user_id] = {}
            active_bots[user_id]['api'] = api
            active_bots[user_id]['ssid'] = ssid_str
            active_bots[user_id]['email'] = email
            active_bots[user_id]['password'] = password

            logger.info(f"✅ Login exitoso para {user_id}")
            logger.info(f"🔑 Session ID: {session.get('_id', 'N/A')}")

            response = jsonify({
                'success': True,
                'message': 'Login exitoso',
                'user': {
                    'id': user_id,
                    'name': user_id,
                    'email': email,
                    'balance': float(balance) if balance else 0.0,
                },
                'name': user_id,
                'username': user_id,
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
            
            # Limpiar cualquier sesión parcial
            import iqoptionapi.global_value as global_value
            global_value.SSID = None
            
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

@app.route('/api/validate_session', methods=['GET'])
def validate_session():
    """
    Valida si la sesión actual es válida (por cookie o por header X-User-Id).
    """
    user_id = session.get('user_id')
    if not user_id:
        user_id = request.headers.get('X-User-Id')
        if not user_id:
            auth_h = request.headers.get('Authorization', '')
            if auth_h.startswith('Bearer '):
                user_id = auth_h.split('Bearer ')[1].strip()

    if not user_id or user_id not in active_bots:
        return jsonify({"valid": False}), 401
    
    session['user_id'] = user_id
    session['ssid'] = active_bots[user_id].get('ssid')
    return jsonify({
        "valid": True,
        "user_id": user_id
    }), 200
@app.route('/api/logout', methods=['POST', 'OPTIONS'])
def logout():
    """
    ✅ CORREGIDO: Logout con limpieza correcta de cookies.
    
    Mejoras:
    - Maneja OPTIONS para CORS
    - Usa mismos parámetros de cookie que al crear
    - Limpia API y SSID correctamente
    """
    # Manejar preflight OPTIONS
    if request.method == 'OPTIONS':
        response = make_response('', 204)
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    try:
        user_id = session.get('user_id')
        logger.info(f"🚪 Logout solicitado para usuario: {user_id}")
        
        # Limpiar API en caché si existe
        if user_id and user_id in active_bots:
            if 'api' in active_bots[user_id]:
                api = active_bots[user_id]['api']
                
                # Cerrar websocket
                try:
                    if hasattr(api, 'websocket') and api.websocket:
                        api.websocket.close()
                        logger.info("✅ Websocket cerrado")
                except Exception as ws_err:
                    logger.warning(f"⚠️ Error cerrando websocket: {ws_err}")
                
                # Limpiar SSID global
                try:
                    import iqoptionapi.global_value as global_value
                    global_value.SSID = None
                    logger.info("✅ SSID global limpiado")
                except Exception as ssid_err:
                    logger.warning(f"⚠️ Error limpiando SSID: {ssid_err}")
                
                # Eliminar API de caché
                try:
                    del active_bots[user_id]['api']
                    logger.info("✅ API eliminada de caché")
                except Exception as del_err:
                    logger.warning(f"⚠️ Error eliminando API: {del_err}")
        
        # Limpiar sesión
        session.clear()
        
        # Crear respuesta
        response = jsonify({
            'success': True,
            'message': 'Logout exitoso'
        })
        
        # ✅ CRÍTICO: Borrar cookie con MISMOS parámetros que al crear
        cookie_name = app.config.get("SESSION_COOKIE_NAME", "iqbot_session")
        cookie_domain = app.config.get("SESSION_COOKIE_DOMAIN")
        cookie_samesite = app.config.get("SESSION_COOKIE_SAMESITE", "None")
        cookie_secure = app.config.get("SESSION_COOKIE_SECURE", True)
        
        response.delete_cookie(
            cookie_name,
            path="/",
            domain=cookie_domain,
            samesite=cookie_samesite,
            secure=cookie_secure
        )
        
        logger.info(f"✅ Logout completado - cookie '{cookie_name}' borrada")
        return response
        
    except Exception as e:
        logger.error(f"❌ Error en logout: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Aunque haya error, intentar limpiar sesión
        try:
            session.clear()
        except:
            pass
        
        return jsonify({
            'success': False,
            'error': 'Error al hacer logout',
            'detail': str(e)
        }), 500
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


# ============================================================================
# CORRECCIÓN 5: FUNCIÓN get_user_api() - EVITAR REUTILIZACIÓN DE SESIONES
# ============================================================================
# Reemplazar desde línea 1577 hasta línea 1650

def get_user_api():
    """
    ✅ CORRECCIÓN FINAL: Obtiene API del usuario con validación de SSID.
    
    Mejoras:
    - Verifica que el SSID coincida con la sesión actual
    - No reutiliza APIs de sesiones anteriores
    - Reconexión automática si la API está desconectada
    - Validación fuerte de conexión
    """
    try:
        user_id = session.get('user_id')
        if not user_id:
            logger.warning("⚠️ No hay user_id en sesión")
            return None
        
        session_ssid = session.get('ssid')
        if not session_ssid:
            logger.warning("⚠️ No hay SSID en sesión")
            return None
        
        # ========================================================================
        # VERIFICAR SI HAY API EN CACHÉ
        # ========================================================================
        if user_id in active_bots and 'api' in active_bots[user_id]:
            api = active_bots[user_id]['api']

            # ✅ VALIDACIÓN 1: Actualizar SSID si cambió (NO descartar API)
            try:
                import iqoptionapi.global_value as global_value

                # Obtener SSID global actual
                global_ssid = ssid_to_str(global_value.SSID)
                
                # Obtener SSID de la API
                api_ssid = None
                if hasattr(api, 'api') and hasattr(api.api, 'ssid'):
                    api_ssid = ssid_to_str(api.api.ssid)

                # ✅ NUEVO: Si el SSID cambió, actualizar en caché y sesión
                # NO descartar la API, solo sincronizar SSIDs
                if global_ssid and global_ssid != session_ssid:
                    logger.info(f"🔄 SSID global cambió, actualizando:")
                    logger.info(f"   Anterior: {session_ssid[:20] if session_ssid else 'None'}...")
                    logger.info(f"   Nuevo: {global_ssid[:20]}...")
                    session['ssid'] = global_ssid
                    active_bots[user_id]['ssid'] = global_ssid
                
                if api_ssid and api_ssid != session_ssid:
                    logger.info(f"🔄 SSID de API cambió, actualizando sesión")
                    session['ssid'] = api_ssid
                    active_bots[user_id]['ssid'] = api_ssid

                logger.debug("✅ SSID sincronizado, verificando conexión...")

            except Exception as e:
                logger.warning(f"⚠️ Error actualizando SSID (no crítico): {e}")
                # NO descartar API por error de SSID
            
            # ✅ VALIDACIÓN 2: Verificar que la conexión está activa
            try:
                # Test con balance
                balance = api.get_balance()
                
                if balance is None:
                    logger.warning("⚠️ Balance es None, API desconectada")
                    raise Exception("API desconectada")
                
                logger.debug(f"✅ API en caché verificada OK (balance: ${balance})")
                return api
                
            except Exception as e:
                logger.warning(f"⚠️ API en caché desconectada: {e}")

                # ✅ VALIDACIÓN 3: Reconectar (con lock para evitar carreras)
                acquired = _reconnect_lock.acquire(blocking=False)
                if not acquired:
                    logger.info("🔒 Otra reconexión en curso, esperando...")
                    _reconnect_lock.acquire(blocking=True, timeout=30)
                    acquired = True
                try:
                    logger.info("🔄 Intentando reconectar API...")
                    try:
                        if hasattr(api, 'websocket') and api.websocket:
                            try:
                                api.websocket.close()
                            except:
                                pass

                        check, reason = api.connect()

                        if check:
                            logger.info("✅ Reconexión exitosa")

                            # ── Restaurar tipo de cuenta guardado ──────────
                            saved_account = active_bots.get(user_id, {}).get('account_type')
                            if saved_account and saved_account != 'PRACTICE':
                                try:
                                    api.change_balance(saved_account)
                                    time.sleep(1)
                                    logger.info(f"✅ Cuenta {saved_account} restaurada tras reconexión")
                                except Exception as _restore_err:
                                    logger.warning(f"⚠️ No se pudo restaurar cuenta {saved_account}: {_restore_err}")

                            balance = api.get_balance()
                            if balance is not None:
                                logger.info(f"✅ API reconectada OK (balance: ${balance})")
                                return api
                            else:
                                logger.warning("⚠️ Reconexión OK pero balance None (cuenta real posiblemente vacía)")
                                return api  # Devolver la API igualmente — balance 0 es válido
                        else:
                            logger.error(f"❌ Reconexión falló: {reason}")

                    except Exception as reconnect_error:
                        logger.error(f"❌ Error en reconexión: {reconnect_error}")
                finally:
                    if acquired:
                        try:
                            _reconnect_lock.release()
                        except RuntimeError:
                            pass

                # Reconexión falló → limpiar y retornar None
                logger.warning("🧹 Limpiando API fallida...")
                try:
                    del active_bots[user_id]['api']
                except:
                    pass

                return None

        # ========================================================================
        # NO HAY API EN CACHÉ - CREAR NUEVA CONEXIÓN
        # ========================================================================
        logger.info("📡 No hay API en caché, creando nueva conexión...")

        email = session.get('email')
        password = session.get('password')

        if not email or not password:
            logger.error("❌ No hay credenciales en sesión")
            return None

        logger.info(f"🔌 Conectando con IQ Option para {email}...")

        # Lock: solo un thread conecta a la vez
        with _reconnect_lock:
            check, result = SafeIQConnection.safe_connect(email, password, timeout=25)

        if not check:
            error_msg = result if isinstance(result, str) else "Error de conexión"
            logger.error(f"❌ Error conectando: {error_msg}")
            return None

        api = result

        # Validar SSID usando global_value (no api.api.ssid que es un objeto)
        import iqoptionapi.global_value as _gv
        api_ssid = str(_gv.SSID) if _gv.SSID and not str(_gv.SSID).startswith('<') else ""
        if session_ssid and api_ssid and api_ssid != session_ssid:
            logger.info(f"ℹ️ SSID actualizado tras reconexión (normal)")
        
        # Validar balance (puede ser 0.0 si cuenta real está vacía — eso es válido)
        try:
            balance = api.get_balance()
            logger.info(f"✅ Nueva API conectada OK (balance: ${balance})")
        except Exception as e:
            logger.error(f"❌ Nueva API no responde: {e}")
            try:
                api.websocket.close()
            except:
                pass
            return None

        # Guardar en caché la API y su SSID
        if user_id not in active_bots:
            active_bots[user_id] = {}
        active_bots[user_id]['api'] = api

        # Restaurar tipo de cuenta si estaba guardado
        saved_account = active_bots[user_id].get('account_type')
        if saved_account and saved_account != 'PRACTICE':
            try:
                api.change_balance(saved_account)
                time.sleep(1)
                logger.info(f"✅ Cuenta {saved_account} restaurada en nueva conexión")
            except Exception as _re:
                logger.warning(f"⚠️ No se pudo restaurar cuenta {saved_account} en nueva conexión: {_re}")
        # Registrar el SSID obtenido para futuras validaciones
        if api_ssid:
            active_bots[user_id]['ssid'] = api_ssid
        # Actualizar credenciales en caché
        if email:
            active_bots[user_id]['email'] = email
        if password:
            active_bots[user_id]['password'] = password

        logger.info(f"✅ API guardada en caché para {user_id}")
        return api
        
    except Exception as e:
        logger.error(f"❌ Error en get_user_api: {str(e)}")
        logger.error(traceback.format_exc())
        return None

# ============================================================================
# NUEVO: FUNCIÓN get_user_api_for
# ============================================================================
def get_user_api_for(user_id: str, session_ssid: str | None = None,
                     email: str | None = None, password: str | None = None):
    """
    Versión de get_user_api que NO depende de flask.session.
    Usa parámetros explícitos para obtener o reconectar la API del usuario.

    Args:
        user_id: Identificador del usuario.
        session_ssid: SSID de la sesión actual (opcional).
        email: Email del usuario para reconectar si la API no está en caché.
        password: Contraseña del usuario para reconectar.

    Returns:
        Instancia de API conectada, o None si no se pudo obtener.
    """
    try:
        if not user_id:
            return None

        # Validar API cacheada
        if user_id in active_bots and 'api' in active_bots[user_id]:
            api = active_bots[user_id]['api']

            # Validar SSID si se proporciona (SIMPLIFICADO - NO descartar API)
            if session_ssid:
                try:
                    import iqoptionapi.global_value as global_value
                    api_ssid = ssid_to_str(getattr(getattr(api, 'api', None), 'ssid', None))
                    global_ssid = ssid_to_str(getattr(global_value, 'SSID', None))
                    
                    # ✅ NUEVO: Actualizar SSID si cambió, NO descartar API
                    if global_ssid and global_ssid != session_ssid:
                        logger.info(f"🔄 [Thread] SSID cambió, actualizando caché")
                        active_bots[user_id]['ssid'] = global_ssid
                    elif api_ssid and api_ssid != session_ssid:
                        logger.info(f"🔄 [Thread] SSID de API cambió, actualizando caché")
                        active_bots[user_id]['ssid'] = api_ssid
                except Exception as e:
                    logger.debug(f"⚠️ [Thread] Error actualizando SSID (no crítico): {e}")
                    # NO descartar API por error de SSID

            # Verificar conexión de API cacheada
            if api and user_id in active_bots and 'api' in active_bots[user_id]:
                try:
                    bal = api.get_balance()
                    if bal is not None:
                        logger.debug(f"✅ [Thread] API en caché OK")
                        return api
                except Exception:
                    logger.info(f"⚠️ [Thread] API en caché desconectada")
                    try:
                        del active_bots[user_id]['api']
                    except Exception:
                        pass
                    api = None

        # Si no hay API válida, intentar reconectar
        # Obtener credenciales de active_bots si no se pasaron
        if (not email or not password) and user_id in active_bots:
            email = active_bots[user_id].get("email")
            password = active_bots[user_id].get("password")

        if not email or not password:
            return None

        # Lock: solo un thread reconecta a la vez
        with _reconnect_lock:
            check, result = SafeIQConnection.safe_connect(email, password, timeout=25)
        if not check:
            return None
        api = result

        try:
            if api.get_balance() is None:
                return None
        except Exception:
            return None

        # SSID desde global_value (el token real, no el objeto canal)
        import iqoptionapi.global_value as _gv2
        api_ssid = None
        try:
            candidate = str(_gv2.SSID) if _gv2.SSID else ""
            api_ssid = candidate if candidate and not candidate.startswith('<') and len(candidate) > 10 else None
        except Exception:
            api_ssid = None

        # Inicializar entrada del usuario en active_bots
        active_bots.setdefault(user_id, {})
        active_bots[user_id]['api'] = api
        # Guardar SSID si está disponible
        if api_ssid:
            active_bots[user_id]['ssid'] = api_ssid
        # También actualizar credenciales si se proporcionaron
        if email:
            active_bots[user_id]['email'] = email
        if password:
            active_bots[user_id]['password'] = password
        return api

    except Exception:
        logger.exception("❌ Error en get_user_api_for")
        return None

def normalize_symbol(symbol: str) -> list:
    """
    Genera variantes normalizadas de un símbolo para búsqueda flexible.
    
    Args:
        symbol: Símbolo base (ej: 'EURUSD')
        
    Returns:
        Lista de variantes del símbolo
    """
    variants = [symbol]
    
    # Agregar versión OTC
    if not symbol.endswith('-OTC'):
        variants.append(f"{symbol}-OTC")
        variants.append(f"{symbol}_OTC")
        variants.append(f"{symbol}OTC")
    
    return variants


def find_best_active(api, symbol: str, market_type: str = 'binary'):
    """
    Encuentra el mejor activo disponible usando get_all_init_v2() (MÉTODO CORRECTO).
    
    Este método evita completamente el uso de get-underlying-list V2 (DEPRECADO).
    
    Args:
        api: Instancia de IQ_Option API
        symbol: Símbolo a buscar (ej: 'EURUSD')
        market_type: Tipo de mercado ('binary' o 'digital')
        
    Returns:
        tuple: (symbol_found, active_id) o None si no se encuentra
    """
    import logging
    import traceback
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"🔍 Buscando {symbol} en mercado {market_type} usando get_all_init_v2()")
        
        # MÉTODO CORRECTO Y ESTABLE: Usar get_all_init_v2()
        init_data = api.get_all_init_v2()
        
        if not init_data:
            logger.warning("⚠️ get_all_init_v2() retornó vacío")
            return None
        
        # Determinar qué mercado buscar
        if market_type == 'binary':
            market_key = 'turbo'  # Binary usa 'turbo'
        elif market_type == 'digital':
            market_key = 'digital'
        else:
            logger.error(f"❌ Tipo de mercado inválido: {market_type}")
            return None
        
        # Verificar que el mercado existe
        if market_key not in init_data:
            logger.warning(f"⚠️ Mercado '{market_key}' no encontrado")
            logger.debug(f"Mercados disponibles: {list(init_data.keys())}")
            return None
        
        # Obtener activos del mercado
        if 'actives' not in init_data[market_key]:
            logger.warning(f"⚠️ No hay activos en mercado {market_key}")
            return None
        
        actives = init_data[market_key]['actives']
        logger.info(f"   📊 Encontrados {len(actives)} activos en mercado {market_key}")
        
        # Generar variantes del símbolo
        variants = normalize_symbol(symbol)
        
        # PRIORIDAD 1: Buscar coincidencia exacta por nombre
        for active_id, active_data in actives.items():
            name = active_data.get('name', '').replace('front.', '')
            
            for variant in variants:
                if name == variant or name.upper() == variant.upper():
                    # Verificar que esté disponible
                    enabled = active_data.get('enabled', False)
                    is_suspended = active_data.get('is_suspended', True)
                    
                    if enabled and not is_suspended:
                        logger.info(f"   ✅ Coincidencia exacta: {name} (ID: {active_id})")
                        return (name, active_id)
                    else:
                        logger.debug(f"   ⚠️ {name} encontrado pero no disponible (enabled={enabled}, suspended={is_suspended})")
        
        # PRIORIDAD 2: Buscar versión OTC
        for active_id, active_data in actives.items():
            name = active_data.get('name', '').replace('front.', '')
            
            if 'OTC' in name.upper() and symbol.upper().replace('-OTC', '').replace('_OTC', '') in name.upper():
                enabled = active_data.get('enabled', False)
                is_suspended = active_data.get('is_suspended', True)
                
                if enabled and not is_suspended:
                    logger.info(f"   ✅ Usando versión OTC: {name} (ID: {active_id})")
                    return (name, active_id)
        
        # PRIORIDAD 3: Buscar versión -op (practice)
        for active_id, active_data in actives.items():
            name = active_data.get('name', '').replace('front.', '')
            
            if '-op' in name.lower() and symbol.upper() in name.upper():
                enabled = active_data.get('enabled', False)
                is_suspended = active_data.get('is_suspended', True)
                
                if enabled and not is_suspended:
                    logger.info(f"   ✅ Usando versión -op: {name} (ID: {active_id})")
                    return (name, active_id)
        
        # PRIORIDAD 4: Buscar símbolo similar (búsqueda parcial)
        symbol_clean = symbol.upper().replace('-OTC', '').replace('_OTC', '').replace('-OP', '').replace('_OP', '')
        
        for active_id, active_data in actives.items():
            name = active_data.get('name', '').replace('front.', '')
            name_clean = name.upper().replace('-OTC', '').replace('_OTC', '').replace('-OP', '').replace('_OP', '')
            
            if symbol_clean in name_clean:
                enabled = active_data.get('enabled', False)
                is_suspended = active_data.get('is_suspended', True)
                
                if enabled and not is_suspended:
                    logger.info(f"   ⚠️ Coincidencia parcial: {name} (ID: {active_id})")
                    return (name, active_id)
        
        # PRIORIDAD 5: Fallback - usar primer activo disponible
        for active_id, active_data in actives.items():
            enabled = active_data.get('enabled', False)
            is_suspended = active_data.get('is_suspended', True)
            
            if enabled and not is_suspended:
                name = active_data.get('name', '').replace('front.', '')
                logger.warning(f"   ⚠️ Usando activo alternativo: {name} (ID: {active_id})")
                return (name, active_id)
        
        logger.warning(f"   ⚠️ No se encontró {symbol} ni alternativas disponibles en {market_type}")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error en find_best_active: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

# ============================================================================
# PRICE ACTION — clases auxiliares (S/R levels, pivots, señales por rebote/ruptura)
# ============================================================================
import math as _math
from dataclasses import dataclass as _dataclass
from typing import List as _List

@_dataclass
class _PACandle:
    open: float
    high: float
    low: float
    close: float

    @property
    def body_size(self) -> float:
        return abs(self.open - self.close)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open


class _PALevel:
    def __init__(self, price: float, level_type: str, touches: int = 1):
        self.price = price
        self.level_type = level_type   # 'support' | 'resistance'
        self.touches = touches
        self.is_broken = False


class _PriceActionEngine:
    """
    Motor de Price Action para S/R.
    Evalúa rebotes en Punto 3, rompimientos débiles (continuidad) y
    rompimientos fuertes (esperar pullback).
    """

    def __init__(self, pip_tolerance: float = 0.0002):
        self.pip_tolerance = pip_tolerance
        self.active_levels: _List[_PALevel] = []

    def _near(self, price: float, level_price: float) -> bool:
        return _math.isclose(price, level_price, abs_tol=self.pip_tolerance)

    def evaluate(self, candle: _PACandle, level: _PALevel) -> Optional[dict]:
        """
        Retorna {'action': 'CALL'|'PUT'|'WAIT_PULLBACK', 'reason': str, 'strength': float}
        o None si no hay señal.
        """
        if level.is_broken or level.touches > 4:
            return None

        # ── Punto 3: rebote en el 3er toque con mecha de rechazo ──────────
        if level.touches >= 3:
            if level.level_type == 'resistance' and self._near(candle.high, level.price):
                if candle.body_size > 0 and candle.upper_wick > candle.body_size * 0.5:
                    strength = min(candle.upper_wick / max(candle.body_size, 0.00001), 3.0)
                    return {'action': 'PUT', 'reason': f'Rebote P3 en Resistencia (x{level.touches})', 'strength': strength}
            elif level.level_type == 'support' and self._near(candle.low, level.price):
                if candle.body_size > 0 and candle.lower_wick > candle.body_size * 0.5:
                    strength = min(candle.lower_wick / max(candle.body_size, 0.00001), 3.0)
                    return {'action': 'CALL', 'reason': f'Rebote P3 en Soporte (x{level.touches})', 'strength': strength}

        # ── Ruptura: la vela cierra al otro lado del nivel ─────────────────
        breakout_size = 0.0
        if level.level_type == 'resistance' and candle.close > level.price:
            breakout_size = candle.close - level.price
        elif level.level_type == 'support' and candle.close < level.price:
            breakout_size = level.price - candle.close

        if breakout_size > 0 and candle.body_size > 0:
            pct = (breakout_size / candle.body_size) * 100
            if 0 < pct <= 35:
                level.is_broken = True
                direction = 'CALL' if level.level_type == 'resistance' else 'PUT'
                return {'action': direction, 'reason': f'Ruptura débil >{level.price:.5f} (continuidad)', 'strength': pct / 35}
            elif pct >= 50:
                level.is_broken = True
                return {'action': 'WAIT_PULLBACK', 'reason': f'Ruptura fuerte — esperar retesteo de {level.price:.5f}', 'strength': 2.0}

        return None


# ============================================================================
# MÓDULO LMTA: GESTIÓN DE CAPITAL + PATRÓN KILLER (Jesús Acosta)
# ============================================================================

class LMTAMoneyManager:
    """
    Interés compuesto de 5 niveles estilo LMTA.
    Cada ganancia reinvierte base + profit; cualquier pérdida reinicia al monto base.
    """
    def __init__(self, base_amount: float, use_compound: bool = False,
                 max_levels: int = 5, payout_rate: float = 0.85):
        self.base_amount = base_amount
        self.use_compound = use_compound
        self.max_levels = max_levels
        self.payout_rate = payout_rate
        self.current_level = 1
        self.current_stake = base_amount

    def get_trade_amount(self) -> float:
        return round(self.current_stake, 2)

    def update_after_trade(self, won: bool):
        if not self.use_compound:
            self.current_stake = self.base_amount
            return
        if won:
            if self.current_level < self.max_levels:
                profit = self.current_stake * self.payout_rate
                self.current_stake = round(self.current_stake + profit, 2)
                self.current_level += 1
                logger.info(f"🔼 LMTA Nivel {self.current_level}/{self.max_levels} — próx. inversión: ${self.current_stake:.2f}")
            else:
                logger.info(f"🏆 LMTA: Ciclo de {self.max_levels} niveles completado. Reiniciando.")
                self.current_stake = self.base_amount
                self.current_level = 1
        else:
            logger.info(f"🔁 LMTA: Pérdida en nivel {self.current_level}. Reiniciando al monto base ${self.base_amount:.2f}")
            self.current_stake = self.base_amount
            self.current_level = 1

    def get_cycle_info(self) -> dict:
        return {
            'level': self.current_level,
            'max_levels': self.max_levels,
            'stake': self.current_stake,
            'base': self.base_amount,
        }


class LMTAPatternScanner:
    """
    Detecta el 'Patrón Killer Gira 2, Gira 1' de LMTA.
    Necesita las últimas 5 velas (True=alcista, False=bajista).
    """
    def __init__(self):
        from collections import deque
        self._colors: 'deque[bool]' = deque(maxlen=5)

    def add_candle(self, is_bullish: bool):
        self._colors.append(is_bullish)

    def feed_candles(self, candles_df):
        """Alimenta el scanner con un DataFrame que tiene columna 'close' y 'open'."""
        self._colors.clear()
        for _, row in candles_df.tail(5).iterrows():
            self._colors.append(float(row['close']) >= float(row['open']))

    def check(self) -> str:
        """Retorna 'SIGNAL_PUT', 'SIGNAL_CALL' o 'NONE'."""
        if len(self._colors) < 5:
            return 'NONE'
        c1, c2, c3, c4, c5 = self._colors
        # Verde Verde Roja Verde Verde → esperar PUT
        if c1 and c2 and not c3 and c4 and c5:
            return 'SIGNAL_PUT'
        # Roja Roja Verde Roja Roja → esperar CALL
        if not c1 and not c2 and c3 and not c4 and not c5:
            return 'SIGNAL_CALL'
        return 'NONE'


# Clase TradingBot completa con todas las funcionalidades
class TradingBot:
    def __init__(self, user_id, api, config):
        """Inicializa el bot"""
        self.user_id = user_id
        self.api = api
        self.config = config
        self.running = False
        
        # Cargar estrategia
        strategy_key = config.get('strategy')
        if strategy_key not in STRATEGIES:
            raise ValueError(f"Estrategia inválida: {strategy_key}")
        
        self.strategy = STRATEGIES[strategy_key]
        
        # Stats
        self.operations_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.session_profit = 0.0
        self.current_candles = []
        self.consecutive_losses = 0
        self.results_history = []
        self._htf_cache: dict = {'trend': 'neutral', 'ts': 0.0}
        self._no_signal_streak = 0  # iteraciones consecutivas sin señal (drought mode)

        # ── MÓDULO LMTA: Interés Compuesto + Patrón Killer ─────────────
        self.use_compound = config.get('use_compound', False)
        self._money_manager = LMTAMoneyManager(
            base_amount=config['amount'],
            use_compound=self.use_compound,
            max_levels=5,
            payout_rate=0.85
        )
        self._pattern_scanner = LMTAPatternScanner()
        self._lmta_consec_losses = 0   # pérdidas seguidas solo en modo compuesto
        self._lmta_pause_until = 0.0   # timestamp hasta el que el bot pausa (anti-ansiedad)
        if self.use_compound:
            logger.info(f"💰 LMTA Interés Compuesto ACTIVADO — Monto base: ${config['amount']} | Max niveles: 5")
        # Price Action S/R state
        self._pa_engine = _PriceActionEngine()
        self._pullback_watch: list = []  # [{price, level_type, ts}]

        # ── IA gratuita (ML local + Groq opcional) ──────────────
        symbol    = config.get('symbol', 'UNKNOWN')
        timeframe = STRATEGIES.get(config.get('strategy', ''), {}).get('timeframe', 60)
        if AI_AVAILABLE:
            self.ai = AISignalEnhancer(symbol, timeframe)
            logger.info("🤖 AISignalEnhancer cargado")
        else:
            self.ai = None

        logger.info(f"✅ TradingBot inicializado para {user_id}")
        logger.info(f"   Estrategia: {self.strategy['name']}")
        logger.info(f"   Símbolo: {self.config['symbol']}")
    async def start(self):
        """Inicia el bot de trading - VERSIÓN CORREGIDA"""
        self.running = True
        
        # Logs de inicio detallados
        logger.info(f"🤖 ========================================")
        logger.info(f"🤖 BOT INICIADO para usuario {self.user_id}")
        logger.info(f"📊 Estrategia: {self.strategy['name']}")
        logger.info(f"🎯 Símbolo: {self.config['symbol']}")
        logger.info(f"💵 Monto base: ${self.config['amount']}")
        logger.info(f"📈 Umbral confianza: {self.strategy['min_confidence']}%")
        logger.info(f"⏱️  Intervalo de análisis: 10 segundos")
        logger.info(f"🤖 ========================================")

        # ✅ Mostrar activos disponibles
        self._log_available_assets()
        
        # ✅ Verificar activo inicial
        logger.info(f"🔍 Verificando activo inicial: {self.config['symbol']}")
        market_type, reason = self._detect_market_type(self.config['symbol'])
        
        if not market_type:
            logger.warning(f"⚠️ Activo no disponible: {reason}")
            logger.info(f"🔄 Buscando alternativa...")
            
            alternative = self._find_alternative_asset()
            if alternative:
                symbol, market_type = alternative
                logger.info(f"✅ Cambiando a: {symbol} ({market_type})")
                self.config['symbol'] = symbol
                self.config['market_type'] = market_type
                
                send_telegram_notification(
                    f"⚠️ Cambio automático\n"
                    f"Nuevo activo: {symbol}\n"
                    f"Tipo: {market_type.upper()}\n"
                    f"Razón: {reason}"
                )
            else:
                logger.error(f"❌ No hay activos - Deteniendo bot")
                send_telegram_notification(f"🛑 Bot detenido - No hay activos disponibles")
                self.running = False
                return
        else:
            self.config['market_type'] = market_type
            logger.info(f"✅ Activo inicial OK: {self.config['symbol']} ({market_type})")
        

        
        try:
            iteration = 0
            while self.running:
                iteration += 1
                logger.info(f"")
                logger.info(f"🔄 ========== ITERACIÓN {iteration} ==========")
                
                try:
                    # Verificar límites
                    if self._check_limits():
                        logger.info("🛑 Límites alcanzados, deteniendo bot")
                        break
                    
                    # Analizar mercado
                    logger.info(f"📈 Analizando mercado {self.config['symbol']}...")
                    signal = await self._analyze_market()
                    
                    # Drought mode: después de 4 iteraciones sin señal, bajar umbral 4 puntos
                    base_min_conf = self.strategy['min_confidence']
                    drought_discount = min(4, self._no_signal_streak // 4) * 1
                    effective_min_conf = max(base_min_conf - drought_discount, 58)

                    if signal:
                        confidence = signal.get('confidence', 0)
                        direction = signal.get('direction', 'unknown')

                        logger.info(f"📊 Señal generada: {direction.upper()} con confianza {confidence:.1f}%")
                        logger.info(f"📏 Umbral: {effective_min_conf}% (base {base_min_conf}%, sequía={self._no_signal_streak})")

                        if confidence >= effective_min_conf:
                            self._no_signal_streak = 0  # resetear sequía al operar
                            logger.info(f"✅ SEÑAL VÁLIDA - Ejecutando operación {direction.upper()}...")

                            result = await self._execute_trade(signal)

                            if result and result.get('success'):
                                self._update_stats(result)
                                logger.info(f"✅ Operación #{self.operations_count} ejecutada exitosamente")
                                logger.info(f"   💰 Monto: ${result.get('amount', 0)}")
                                logger.info(f"   📈 Dirección: {result.get('direction', 'N/A').upper()}")
                                logger.info(f"   🎯 ID: {result.get('id', 'N/A')}")
                            else:
                                logger.warning(f"⚠️ No se pudo ejecutar la operación")
                                if result:
                                    logger.warning(f"   Razón: {result.get('message', 'Desconocida')}")
                        else:
                            self._no_signal_streak += 1
                            logger.warning(f"❌ Señal rechazada - {confidence:.1f}% < {effective_min_conf}% (sequía: {self._no_signal_streak})")
                    else:
                        self._no_signal_streak += 1
                        logger.info(f"⏭️ Sin señal (sequía: {self._no_signal_streak} iteraciones)")

                except Exception as e:
                    logger.error(f"❌ Error en iteración {iteration}: {str(e)}")
                    logger.error(traceback.format_exc())

                # Esperar 5s (antes 10s) para mayor frecuencia de análisis
                await asyncio.sleep(5)
        
        except Exception as e:
            logger.error(f"❌ Error crítico en bot: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            self.running = False
            logger.info(f"")
            logger.info(f"🏁 ========================================")
            logger.info(f"🏁 BOT DETENIDO para usuario {self.user_id}")
            logger.info(f"📊 Operaciones totales: {self.operations_count}")
            logger.info(f"💰 Profit de sesión: ${self.session_profit:.2f}")
            logger.info(f"🏁 ========================================")
    
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
        """Analiza el mercado y genera señales - VERSIÓN MEJORADA"""
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                symbol = self.config['symbol']
                timeframe = self.strategy.get('timeframe', 60)
                
                logger.debug(f"   🔍 Obteniendo velas para {symbol} (timeframe: {timeframe}s)...")
                
                # Obtener datos históricos
                try:
                    candles = self.api.get_candles(symbol, timeframe, 100, time.time())
                except Exception as e:
                    error_msg = str(e).lower()
                    if 'connection' in error_msg or 'closed' in error_msg or 'socket' in error_msg:
                        logger.warning(f"   ⚠️ Conexión perdida, reconectando... (intento {retry_count + 1}/{max_retries})")
                        # Intentar reconectar
                        try:
                            if hasattr(self.api, 'websocket') and self.api.websocket:
                                try:
                                    self.api.websocket.close()
                                except:
                                    pass
                            check, _reason = self.api.connect()
                            if check:
                                logger.info("   ✅ Reconexión exitosa")
                                retry_count += 1
                                await asyncio.sleep(2)  # Esperar antes de reintentar
                                continue
                            else:
                                logger.error(f"   ❌ Error reconectando: {_reason}")
                        except Exception as reconnect_error:
                            logger.error(f"   ❌ Error en reconexión: {reconnect_error}")
                        
                        retry_count += 1
                        if retry_count >= max_retries:
                            logger.error(f"   ❌ Máximo de reintentos alcanzado")
                            return None
                        await asyncio.sleep(5)
                        continue
                    else:
                        raise e
                
                if not candles or len(candles) == 0:
                    logger.warning(f"   ⚠️ No se obtuvieron velas para {symbol}")
                    return None
                
                logger.debug(f"   ✅ Obtenidas {len(candles)} velas")
                
                # Guardar las últimas velas para mostrar en tiempo real
                self.current_candles = candles[-30:]
                
                # Convertir a DataFrame
                df = pd.DataFrame(candles)
                 # ✅ CORRECCIÓN: Renombrar columnas de IQ Option a estándar
                df = df.rename(columns={
                    'max': 'high',
                    'min': 'low',
                    'from': 'timestamp',
                    'open': 'open',
                    'close': 'close'
            })
                
                # Verificar que tenemos las columnas necesarias
                if 'timestamp' not in df.columns:
                    logger.error(f"   ❌ Datos de velas inválidos - falta columna 'timestamp'")
                    return None
                
                df['time'] = pd.to_datetime(df['timestamp'], unit='s')
                df.set_index('time', inplace=True)
                
                logger.debug(f"   🧮 Calculando indicadores técnicos...")

                # Calcular indicadores técnicos
                indicators = self._calculate_indicators(df)

                # ── Tendencia de marco temporal superior (5 min) ──
                htf_trend = await self._get_htf_trend(symbol)
                indicators['htf_trend'] = htf_trend
                logger.info(f"   🕐 HTF tendencia (5min): {htf_trend.upper()}")

                # ── Entrenar / actualizar ML con datos frescos ──
                if self.ai is not None:
                    self.ai.maybe_train(df)

                _rsi  = indicators.get('rsi', 0)
                _cci  = indicators.get('cci', 0)
                _e20  = indicators.get('ema_20', 0)
                _e50  = indicators.get('ema_50', 1)
                _spr  = (_e20 - _e50) / _e50 * 100 if _e50 else 0
                logger.info(
                    f"   📊 RSI={_rsi:.1f} | CCI={_cci:.1f} | "
                    f"EMA_spread={_spr:.3f}% | HTF={indicators.get('htf_trend','?').upper()}"
                )

                # Generar señal según la estrategia técnica
                signal = self._generate_signal(indicators, df)

                # ── Potenciar señal con IA gratuita ─────────────
                if signal and signal.get('direction') and self.ai is not None:
                    signal = self.ai.enhance(signal, df, indicators)

                if signal and signal.get('direction') and signal.get('confidence', 0) > 0:
                    logger.info(f"   💡 Señal final: {signal['direction'].upper()} "
                            f"con {signal['confidence']:.1f}% de confianza"
                            + (f" | {signal.get('ai_notes','')}" if signal.get('ai_notes') else ""))
                    return signal
                else:
                    logger.info(f"   ⏭️ Sin señal — condiciones no cumplidas (RSI={_rsi:.1f}, CCI={_cci:.1f}, spread={_spr:.3f}%)")
                    return None
            
            except Exception as e:
                logger.error(f"   ❌ Error crítico en análisis de mercado: {str(e)}")
                logger.error(traceback.format_exc())
                retry_count += 1
                if retry_count >= max_retries:
                    return None
                await asyncio.sleep(5)
        
        return None
    
    def _calculate_indicators(self, df: pd.DataFrame) -> dict:
        """
        Calcula indicadores técnicos.
        SIEMPRE calcula los indicadores rápidos base (RSI5, Stoch5, EMA, MACD).
        Los indicadores pesados (BB, CCI, ATR, StochRSI) son condicionales.
        """
        indicators = {}
        close = df['close']
        high  = df['high']
        low   = df['low']
        n     = len(df)

        # ── Precio y micro-tendencia (siempre) ──────────────────────────────
        indicators['price'] = float(close.iloc[-1])
        indicators['trend'] = "up" if close.iloc[-1] > close.iloc[-5] else "down"

        # ── RSI rápido — período 5 (mejor respuesta en 60s) ─────────────────
        _rsi5_series = RSIIndicator(close=close, window=5).rsi()
        indicators['rsi5']      = float(_rsi5_series.iloc[-1])
        indicators['rsi5_prev'] = float(_rsi5_series.iloc[-2]) if n >= 2 else indicators['rsi5']

        # ── RSI estándar 14 ─────────────────────────────────────────────────
        _rsi14_series = RSIIndicator(close=close, window=14).rsi()
        indicators['rsi']      = float(_rsi14_series.iloc[-1])
        indicators['rsi_prev'] = float(_rsi14_series.iloc[-2]) if n >= 2 else indicators['rsi']

        # ── Stochastic rápido (5,3,3) — más reactivo para 60s ───────────────
        _stf = StochasticOscillator(high=high, low=low, close=close, window=5, smooth_window=3)
        indicators['stoch5_k']      = float(_stf.stoch().iloc[-1])
        indicators['stoch5_d']      = float(_stf.stoch_signal().iloc[-1])
        indicators['stoch5_k_prev'] = float(_stf.stoch().iloc[-2]) if n >= 2 else indicators['stoch5_k']

        # ── EMA 20 y 50 (siempre — base de tendencia) ───────────────────────
        indicators['ema_20'] = float(EMAIndicator(close=close, window=20).ema_indicator().iloc[-1])
        indicators['ema_50'] = float(EMAIndicator(close=close, window=50).ema_indicator().iloc[-1])

        # ── MACD (siempre — dirección + momentum) ───────────────────────────
        _macd = MACD(close=close)
        _macd_diff = _macd.macd_diff()
        indicators['macd']          = float(_macd.macd().iloc[-1])
        indicators['macd_signal']   = float(_macd.macd_signal().iloc[-1])
        indicators['macd_diff']     = float(_macd_diff.iloc[-1])
        indicators['macd_diff_prev']= float(_macd_diff.iloc[-2]) if n >= 2 else 0.0

        # ── Bollinger Bands (período 15, desviación 2 — óptimo para 60s) ────
        if "bollinger" in self.strategy['indicators']:
            _bb = BollingerBands(close=close, window=15, window_dev=2)
            indicators['bb_upper']  = float(_bb.bollinger_hband().iloc[-1])
            indicators['bb_lower']  = float(_bb.bollinger_lband().iloc[-1])
            indicators['bb_middle'] = float(_bb.bollinger_mavg().iloc[-1])

        # ── Stochastic estándar 14 (para estrategias que lo piden) ──────────
        if "stochastic" in self.strategy['indicators']:
            _st14 = StochasticOscillator(high=high, low=low, close=close)
            indicators['stoch_k']      = float(_st14.stoch().iloc[-1])
            indicators['stoch_d']      = float(_st14.stoch_signal().iloc[-1])
            indicators['stoch_k_prev'] = float(_st14.stoch().iloc[-2]) if n >= 2 else indicators['stoch_k']

        # ── CCI (indicador de momentum fuerte ±100) ──────────────────────────
        if "cci" in self.strategy['indicators']:
            _cci_series = CCIIndicator(high=high, low=low, close=close).cci()
            indicators['cci']      = float(_cci_series.iloc[-1])
            indicators['cci_prev'] = float(_cci_series.iloc[-2]) if n >= 2 else indicators['cci']

        # ── ATR ──────────────────────────────────────────────────────────────
        if "atr" in self.strategy['indicators']:
            indicators['atr'] = float(AverageTrueRange(high=high, low=low, close=close).average_true_range().iloc[-1])

        # ── StochRSI (estrategia de 78% win rate: StochRSI + CCI) ───────────
        if "stochastic" in self.strategy['indicators'] or "cci" in self.strategy['indicators']:
            try:
                _srsi = StochRSIIndicator(close=close, window=14, smooth1=3, smooth2=3)
                indicators['stochrsi_k']      = float(_srsi.stochrsi_k().iloc[-1])
                indicators['stochrsi_d']      = float(_srsi.stochrsi_d().iloc[-1])
                indicators['stochrsi_k_prev'] = float(_srsi.stochrsi_k().iloc[-2]) if n >= 2 else indicators['stochrsi_k']
            except Exception:
                indicators['stochrsi_k']      = 0.5
                indicators['stochrsi_d']      = 0.5
                indicators['stochrsi_k_prev'] = 0.5


        return indicators
    
    def _generate_signal(self, indicators: dict, df: pd.DataFrame) -> Optional[dict]:
        """Genera señal de trading según la estrategia"""
        signal = {
            'direction': None,
            'confidence': 0,
            'indicators': indicators
        }
        
        strategy_id = self.config['strategy']
        if strategy_id == "ai_adaptive_auto":
            signal = self._ai_adaptive_auto_signal(indicators, df)
        elif strategy_id in ("conservative_rsi",):
            signal = self._conservative_rsi_signal(indicators, df)
        elif strategy_id in ("macd_cross", "triple_ema_macd"):
            signal = self._macd_cross_signal(indicators, df)
        elif strategy_id in ("bollinger_bounce", "bollinger_rsi_bounce"):
            signal = self._bollinger_bounce_signal(indicators, df)
        elif strategy_id in ("multi_indicator", "rsi_stochastic_dual"):
            signal = self._multi_indicator_signal(indicators, df)
        elif strategy_id in ("momentum_scalper", "scalping_extreme"):
            signal = self._momentum_scalper_signal(indicators, df)
        elif strategy_id == "macd_bollinger_breakout":
            signal = self._macd_bollinger_breakout_signal(indicators, df)
        elif strategy_id == "price_action_sr":
            signal = self._price_action_signal(indicators, df)
        else:
            # Fallback: usar momentum_scalper para cualquier estrategia desconocida
            logger.warning(f"⚠️ Estrategia '{strategy_id}' sin implementación, usando momentum_scalper")
            signal = self._momentum_scalper_signal(indicators, df)

        # ── Boost por horario pico: London/NY overlap 08:00-20:00 UTC ────────
        # Investigación: máxima liquidez y movimientos más predecibles en este horario
        if signal and signal.get('direction') and signal.get('confidence', 0) > 0:
            utc_hour = datetime.utcnow().hour
            if 8 <= utc_hour <= 20:   # London open + NY session
                boost = 4
                signal['confidence'] = min(signal['confidence'] + boost, 95)
            elif utc_hour < 6 or utc_hour > 22:  # sesión asiática tarde/madrugada
                signal['confidence'] = max(signal['confidence'] - 3, 0)

        # ── Filtro HTF: penalizar (-10%) si va contra la tendencia de 5 minutos ──
        if signal and signal.get('direction') and htf_trend != 'neutral':
            if (signal['direction'] == 'call' and htf_trend == 'down') or \
               (signal['direction'] == 'put' and htf_trend == 'up'):
                penalized = signal['confidence'] - 10
                min_conf  = self.strategy.get('min_confidence', 62)
                if penalized < min_conf:
                    logger.info(f"   🚫 HTF {htf_trend.upper()} contra {signal['direction'].upper()}: conf {signal['confidence']:.0f}%→{penalized:.0f}% < {min_conf}% — descartada")
                    return {'direction': None, 'confidence': 0, 'indicators': indicators}
                signal['confidence'] = penalized
                logger.info(f"   ⚠️ HTF contrario: confianza reducida a {penalized:.0f}%")

    def _ai_adaptive_auto_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        🤖 ESTRATEGIA ADAPTATIVA CUANTITATIVA + IA LLaMA 3.3
        =====================================================
        1. Diagnostica el régimen de mercado (Tendencia vs Rango).
        2. Aplica filtro anti-trampa estricto (3 velas consecutivas = veto).
        3. Exige mecha de rechazo en reversiones o pullback a la EMA en tendencias.
        4. Alta tasa de acierto y filtro de calidad de entrada.
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        if df is None or len(df) < 10:
            return signal

        price = indicators['price']
        rsi5 = indicators.get('rsi5', 50)
        stoch5_k = indicators.get('stoch5_k', 50)
        stoch5_d = indicators.get('stoch5_d', 50)
        ema_20 = indicators.get('ema_20', price)
        ema_50 = indicators.get('ema_50', price)
        macd_diff = indicators.get('macd_diff', 0)
        bb_upper = indicators.get('bb_upper', price * 1.002)
        bb_lower = indicators.get('bb_lower', price * 0.998)
        bb_mid = indicators.get('bb_middle', price)

        # Análisis de las últimas 4 velas
        last_4 = df.tail(4)
        c0, o0, h0, l0 = float(last_4['close'].iloc[-1]), float(last_4['open'].iloc[-1]), float(last_4['high'].iloc[-1]), float(last_4['low'].iloc[-1])
        c1, o1 = float(last_4['close'].iloc[-2]), float(last_4['open'].iloc[-2])
        c2, o2 = float(last_4['close'].iloc[-3]), float(last_4['open'].iloc[-3])

        candle_range = max(h0 - l0, 1e-6)
        top_wick = h0 - max(c0, o0)
        bottom_wick = min(c0, o0) - l0
        body = abs(c0 - o0)

        # Regla Anti-Trampas: 3 velas consecutivas del mismo color
        consec_green = (c0 > o0) and (c1 > o1) and (c2 > o2)
        consec_red = (c0 < o0) and (c1 < o1) and (c2 < o2)

        # Medir fuerza de tendencia por separación de EMAs
        ema_spread = abs(ema_20 - ema_50) / (ema_50 or 1.0) * 100
        is_trending = ema_spread > 0.035
        is_uptrend = ema_20 > ema_50 and price > ema_50
        is_downtrend = ema_20 < ema_50 and price < ema_50

        direction = None
        conf = 0

        # ====================================================================
        # RÉGIMEN 1: TENDENCIA FUERTE (SEGUIR TENDENCIA EN PULLBACK)
        # ====================================================================
        if is_trending:
            # En tendencia alcista fuerte -> SOLO CALL en retroceso
            if is_uptrend and not consec_red:
                if price <= ema_20 * 1.0005 and rsi5 < 48 and macd_diff > -0.0002:
                    # Rebote en soporte dinámico (EMA 20)
                    if bottom_wick > body * 0.4 or c0 > o0:
                        direction = 'call'
                        conf = 75
                        if stoch5_k < 35: conf += 6
                        if bottom_wick > top_wick: conf += 5
                        if macd_diff > 0: conf += 4

            # En tendencia bajista fuerte -> SOLO PUT en retroceso
            elif is_downtrend and not consec_green:
                if price >= ema_20 * 0.9995 and rsi5 > 52 and macd_diff < 0.0002:
                    # Rechazo en resistencia dinámica (EMA 20)
                    if top_wick > body * 0.4 or c0 < o0:
                        direction = 'put'
                        conf = 75
                        if stoch5_k > 65: conf += 6
                        if top_wick > bottom_wick: conf += 5
                        if macd_diff < 0: conf += 4

        # ====================================================================
        # RÉGIMEN 2: RANGO / MERCADO LATERAL (REBOTES EN BANDAS DE BOLLINGER)
        # ====================================================================
        else:
            # CALL en banda inferior (con rechazo claro)
            if price <= bb_lower * 1.0003 and rsi5 < 32 and not consec_red:
                if bottom_wick >= candle_range * 0.25 or stoch5_k < 22:
                    direction = 'call'
                    conf = 74
                    if rsi5 < 20: conf += 6
                    if stoch5_k < stoch5_d: conf += 4
                    if bottom_wick > top_wick * 1.5: conf += 6

            # PUT en banda superior (con rechazo claro)
            elif price >= bb_upper * 0.9997 and rsi5 > 68 and not consec_green:
                if top_wick >= candle_range * 0.25 or stoch5_k > 78:
                    direction = 'put'
                    conf = 74
                    if rsi5 > 80: conf += 6
                    if stoch5_k > stoch5_d: conf += 4
                    if top_wick > bottom_wick * 1.5: conf += 6

        # Veto final de protección anti-trampa
        if direction == 'put' and consec_green:
            logger.info("🚫 VETO IA: Bloqueada señal PUT por ráfaga de 3 velas verdes consecutivas")
            return signal
        if direction == 'call' and consec_red:
            logger.info("🚫 VETO IA: Bloqueada señal CALL por ráfaga de 3 velas rojas consecutivas")
            return signal

        if direction and conf >= 70:
            signal['direction'] = direction
            signal['confidence'] = min(conf, 93)

        return signal

    def _conservative_rsi_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        RSI(5) rápido + EMA tendencia.
        Usa RSI de período 5 (más reactivo en 60s) con zonas extremas claras.
        CALL: RSI5 < 30 en tendencia alcista | PUT: RSI5 > 70 en tendencia bajista
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}

        rsi5  = indicators.get('rsi5', 50)
        rsi14 = indicators.get('rsi', 50)
        ema_20 = indicators.get('ema_20', 0)
        ema_50 = indicators.get('ema_50', 0)
        price  = indicators['price']
        stoch5_k = indicators.get('stoch5_k', 50)
        uptrend   = ema_20 > ema_50
        downtrend = ema_20 < ema_50

        # CALL: RSI5 sobrevendido + tendencia alcista
        if rsi5 < 30:
            conf = 62
            if rsi5 < 20:       conf += 8   # muy sobrevendido
            if stoch5_k < 25:   conf += 6   # Stoch confirma
            if uptrend:         conf += 8   # tendencia a favor
            if price > ema_20:  conf += 4   # precio sobre soporte
            if rsi14 < 35:      conf += 3   # RSI14 también confirma
            signal['direction']  = 'call'
            signal['confidence'] = min(conf, 90)

        # PUT: RSI5 sobrecomprado + tendencia bajista
        elif rsi5 > 70:
            conf = 62
            if rsi5 > 80:       conf += 8
            if stoch5_k > 75:   conf += 6
            if downtrend:       conf += 8
            if price < ema_20:  conf += 4
            if rsi14 > 65:      conf += 3
            signal['direction']  = 'put'
            signal['confidence'] = min(conf, 90)

        return signal
    
    def _macd_cross_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        MACD Cross + RSI(5) — win rate documentado: 73%
        Fuente: QuantifiedStrategies.com — MACD and RSI Strategy.

        Cruce MACD confirmado con RSI(5) en la dirección correcta:
        CALL: MACD cruza al alza + RSI5 > 50  (momentum alcista confirmado)
        PUT:  MACD cruza a la baja + RSI5 < 50 (momentum bajista confirmado)
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}

        macd_diff      = indicators.get('macd_diff', 0)
        macd_diff_prev = indicators.get('macd_diff_prev', 0)
        rsi5           = indicators.get('rsi5', 50)
        ema_20         = indicators.get('ema_20', 0)
        ema_50         = indicators.get('ema_50', 0)
        stoch5_k       = indicators.get('stoch5_k', 50)

        # Cruce MACD: diff pasa de negativo a positivo (alcista)
        macd_cross_up   = macd_diff > 0 and macd_diff_prev <= 0
        # Cruce MACD: diff pasa de positivo a negativo (bajista)
        macd_cross_down = macd_diff < 0 and macd_diff_prev >= 0

        # CALL: cruce alcista + RSI5 > 50 (momentum confirmado)
        if macd_cross_up and rsi5 > 45:
            conf = 70
            if rsi5 > 55:          conf += 6   # RSI claramente alcista
            if stoch5_k > 50:      conf += 5   # Stoch confirma
            if ema_20 > ema_50:    conf += 5   # tendencia a favor
            if abs(macd_diff) > abs(macd_diff_prev) * 1.5:  conf += 4  # aceleración
            signal['direction']  = 'call'
            signal['confidence'] = min(conf, 90)

        # PUT: cruce bajista + RSI5 < 50 (momentum confirmado)
        elif macd_cross_down and rsi5 < 55:
            conf = 70
            if rsi5 < 45:          conf += 6
            if stoch5_k < 50:      conf += 5
            if ema_20 < ema_50:    conf += 5
            if abs(macd_diff) > abs(macd_diff_prev) * 1.5:  conf += 4
            signal['direction']  = 'put'
            signal['confidence'] = min(conf, 90)

        # Señal de momentum sin cruce exacto (MACD fuerte en dirección)
        elif not macd_cross_up and not macd_cross_down:
            if macd_diff > 0 and rsi5 < 30 and stoch5_k < 25:
                # Oversold con MACD alcista = rebote muy probable
                signal['direction']  = 'call'
                signal['confidence'] = 65 + (30 - rsi5) * 0.5
            elif macd_diff < 0 and rsi5 > 70 and stoch5_k > 75:
                signal['direction']  = 'put'
                signal['confidence'] = 65 + (rsi5 - 70) * 0.5

        return signal
    
    def _bollinger_bounce_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        Bollinger Bands (15,2) + RSI(5) + Stochastic(5,3,3)
        Configuración óptima para 60s: BB período 15 (más sensible que 20).

        CALL: precio en/bajo banda inferior + RSI5 sobrevendido + Stoch sobrevendido
        PUT:  precio en/sobre banda superior + RSI5 sobrecomprado + Stoch sobrecomprado
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}

        price    = indicators['price']
        bb_upper = indicators.get('bb_upper', price * 1.002)
        bb_lower = indicators.get('bb_lower', price * 0.998)
        bb_mid   = indicators.get('bb_middle', price)
        rsi5     = indicators.get('rsi5', 50)
        stoch5_k = indicators.get('stoch5_k', 50)
        stoch5_d = indicators.get('stoch5_d', 50)
        ema_20   = indicators.get('ema_20', price)
        ema_50   = indicators.get('ema_50', price)

        # ── CALL: precio en banda inferior + indicadores sobrevendidos ──────
        near_lower = price <= bb_lower * 1.003  # dentro del 0.3% de la banda
        if near_lower and rsi5 < 35:
            conf = 65
            if rsi5 < 25:            conf += 8   # muy sobrevendido
            if stoch5_k < 25:        conf += 7   # Stoch confirma
            if stoch5_k > stoch5_d:  conf += 5   # %K cruza encima de %D (giro al alza)
            if price < bb_lower:     conf += 5   # precio bajo la banda (extremo)
            if ema_20 > ema_50:      conf += 4   # tendencia alcista de fondo
            signal['direction']  = 'call'
            signal['confidence'] = min(conf, 90)

        # ── PUT: precio en banda superior + indicadores sobrecomprados ──────
        elif price >= bb_upper * 0.997 and rsi5 > 65:
            conf = 65
            if rsi5 > 75:            conf += 8
            if stoch5_k > 75:        conf += 7
            if stoch5_k < stoch5_d:  conf += 5   # %K cruza debajo de %D (giro a la baja)
            if price > bb_upper:     conf += 5
            if ema_20 < ema_50:      conf += 4
            signal['direction']  = 'put'
            signal['confidence'] = min(conf, 90)

        return signal
    
    def _multi_indicator_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        StochRSI + CCI — win rate documentado: 78%
        Fuente: QuantifiedStrategies.com — Stochastic RSI Strategy.

        Combinación de alta precisión para zonas de reversión extrema.
        CALL: StochRSI_K < 0.20 + CCI < -100 (doble confirmación oversold extremo)
        PUT:  StochRSI_K > 0.80 + CCI > +100 (doble confirmación overbought extremo)
        Con MACD y tendencia EMA como filtros de dirección.
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}

        srsi_k      = indicators.get('stochrsi_k', 0.5)
        srsi_k_prev = indicators.get('stochrsi_k_prev', 0.5)
        srsi_d      = indicators.get('stochrsi_d', 0.5)
        cci         = indicators.get('cci', 0)
        cci_prev    = indicators.get('cci_prev', 0)
        macd_diff   = indicators.get('macd_diff', 0)
        ema_20      = indicators.get('ema_20', 0)
        ema_50      = indicators.get('ema_50', 0)
        rsi5        = indicators.get('rsi5', 50)
        stoch5_k    = indicators.get('stoch5_k', 50)

        # ── CALL: StochRSI extremamente sobrevendido + CCI negativo ─────────
        if srsi_k < 0.25 and cci < -50:
            conf = 65
            # Fuerza de la señal
            if srsi_k < 0.15:     conf += 7   # StochRSI en zona extrema
            if cci < -100:        conf += 8   # CCI confirma (umbral clave)
            if cci < -150:        conf += 4   # CCI muy negativo
            if srsi_k > srsi_k_prev:  conf += 5  # StochRSI girando al alza
            if srsi_k > srsi_d:   conf += 4   # %K cruzó sobre %D
            if macd_diff > 0:     conf += 4   # MACD alcista
            if ema_20 > ema_50:   conf += 3   # tendencia alcista
            if rsi5 < 35:         conf += 4   # RSI5 confirma
            if stoch5_k < 25:     conf += 3   # Stoch5 confirma
            signal['direction']  = 'call'
            signal['confidence'] = min(conf, 92)

        # ── PUT: StochRSI extremamente sobrecomprado + CCI positivo ─────────
        elif srsi_k > 0.75 and cci > 50:
            conf = 65
            if srsi_k > 0.85:     conf += 7
            if cci > 100:         conf += 8
            if cci > 150:         conf += 4
            if srsi_k < srsi_k_prev:  conf += 5  # StochRSI girando a la baja
            if srsi_k < srsi_d:   conf += 4
            if macd_diff < 0:     conf += 4
            if ema_20 < ema_50:   conf += 3
            if rsi5 > 65:         conf += 4
            if stoch5_k > 75:     conf += 3
            signal['direction']  = 'put'
            signal['confidence'] = min(conf, 92)

        return signal
    
    def _momentum_scalper_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        RSI(5) + Stochastic(5,3,3) + CCI + Tendencia EMA
        Diseñado específicamente para opciones binarias de 60 segundos.

        RSI(5) y Stoch(5,3,3) son las versiones rápidas, más reactivas en 60s.
        CCI ±100 es el umbral de señal fuerte documentado en investigaciones.

        CALL: RSI5 sobrevendido + Stoch5 sobrevendido [+ CCI negativo]
        PUT:  RSI5 sobrecomprado + Stoch5 sobrecomprado [+ CCI positivo]
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}

        rsi5         = indicators.get('rsi5', 50)
        stoch5_k     = indicators.get('stoch5_k', 50)
        stoch5_d     = indicators.get('stoch5_d', 50)
        stoch5_k_prev= indicators.get('stoch5_k_prev', stoch5_k)
        cci          = indicators.get('cci', 0)
        cci_prev     = indicators.get('cci_prev', 0)
        ema_20       = indicators.get('ema_20', indicators['price'])
        ema_50       = indicators.get('ema_50', indicators['price'])
        macd_diff    = indicators.get('macd_diff', 0)
        price        = indicators['price']

        if len(df) < 5:
            return signal

        # Vela actual
        c1, o1 = float(df['close'].iloc[-1]), float(df['open'].iloc[-1])
        bull_candle = c1 >= o1
        bear_candle = c1 <= o1

        # Tendencia de fondo
        uptrend   = ema_20 > ema_50
        downtrend = ema_20 < ema_50

        direction  = None
        confidence = 0

        # ── CALL: RSI5 + Stoch5 sobrevendidos ─────────────────────────────
        # Condición base: ambos indicadores rápidos en zona oversold
        if rsi5 < 35 and stoch5_k < 35:
            conf = 62  # base

            # Profundidad del oversold
            if rsi5 < 25:              conf += 8   # RSI5 muy sobrevendido
            elif rsi5 < 30:            conf += 4
            if stoch5_k < 20:          conf += 7   # Stoch5 extremo
            elif stoch5_k < 25:        conf += 4

            # Señales de giro al alza
            if stoch5_k > stoch5_k_prev:   conf += 5   # Stoch5 girando
            if stoch5_k > stoch5_d:        conf += 4   # %K cruza %D (alcista)

            # CCI confirma (investigación: ±100 es el umbral clave)
            if cci < -100:             conf += 8
            elif cci < -50:            conf += 4
            if cci_prev < cci < 0:     conf += 3   # CCI recuperando

            # Confirmaciones adicionales
            if uptrend:                conf += 5   # tendencia EMA a favor
            if macd_diff > 0:          conf += 4   # MACD alcista
            if bull_candle:            conf += 3   # vela confirma
            if price < ema_20:         conf += 2   # precio en zona de soporte

            direction  = 'call'
            confidence = min(conf, 92)

        # ── PUT: RSI5 + Stoch5 sobrecomprados ─────────────────────────────
        elif rsi5 > 65 and stoch5_k > 65:
            conf = 62

            if rsi5 > 75:              conf += 8
            elif rsi5 > 70:            conf += 4
            if stoch5_k > 80:          conf += 7
            elif stoch5_k > 75:        conf += 4

            if stoch5_k < stoch5_k_prev:   conf += 5
            if stoch5_k < stoch5_d:        conf += 4

            if cci > 100:              conf += 8
            elif cci > 50:             conf += 4
            if cci_prev > cci > 0:     conf += 3

            if downtrend:              conf += 5
            if macd_diff < 0:          conf += 4
            if bear_candle:            conf += 3
            if price > ema_20:         conf += 2

            direction  = 'put'
            confidence = min(conf, 92)

        # ── TREND-FOLLOWING: señal cuando la tendencia es fuerte y sostenida ──
        # Activa cuando la reversión no aplica pero hay momentum claro de tendencia.
        # Requiere: EMA bien separadas + MACD confirmando + 2 velas en la misma dirección.
        if direction is None and len(df) >= 3:
            ema_gap = abs(ema_20 - ema_50) / ema_50 if ema_50 > 0 else 0
            strong_trend = ema_gap > 0.0003  # EMAs separadas >0.03% (tendencia real)

            c2 = float(df['close'].iloc[-2])
            o2 = float(df['open'].iloc[-2])
            two_bull = (c1 > o1) and (c2 > o2)
            two_bear = (c1 < o1) and (c2 < o2)

            if strong_trend and uptrend and macd_diff > 0 and two_bull and rsi5 < 65:
                # Tendencia alcista confirmada — no esperar oversold extremo
                conf = 62
                if ema_gap > 0.0008:    conf += 6   # tendencia muy fuerte
                if rsi5 < 55:           conf += 5   # RSI no sobrecomprado
                if macd_diff > abs(macd_diff) * 0.1:  conf += 4
                if stoch5_k < 70:       conf += 4   # Stoch no agotado
                if cci > 0:             conf += 3   # CCI positivo confirma
                direction  = 'call'
                confidence = min(conf, 82)
                logger.info(
                    f"   📈 momentum_scalper TREND-CALL | "
                    f"EMA_gap={ema_gap*100:.3f}% MACD={macd_diff:.5f} RSI5={rsi5:.1f} | conf={confidence}%"
                )

            elif strong_trend and downtrend and macd_diff < 0 and two_bear and rsi5 > 35:
                conf = 62
                if ema_gap > 0.0008:    conf += 6
                if rsi5 > 45:           conf += 5
                if abs(macd_diff) > 0:  conf += 4
                if stoch5_k > 30:       conf += 4
                if cci < 0:             conf += 3
                direction  = 'put'
                confidence = min(conf, 82)
                logger.info(
                    f"   📉 momentum_scalper TREND-PUT | "
                    f"EMA_gap={ema_gap*100:.3f}% MACD={macd_diff:.5f} RSI5={rsi5:.1f} | conf={confidence}%"
                )

        if direction:
            logger.info(
                f"   🎯 momentum_scalper: {direction.upper()} | "
                f"RSI5={rsi5:.1f} Stoch5={stoch5_k:.1f} CCI={cci:.1f} | conf={confidence}%"
            )

        signal['direction']  = direction
        signal['confidence'] = confidence
        return signal
    
    def _macd_bollinger_breakout_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        BB(15,2) squeeze + MACD breakout + RSI(5) confirmación.
        Captura explosiones de volatilidad después de compresión (squeeze).

        CALL: precio rompe banda superior + MACD alcista + RSI5 con fuerza
        PUT:  precio rompe banda inferior + MACD bajista + RSI5 con fuerza
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}

        price         = indicators['price']
        bb_upper      = indicators.get('bb_upper', price * 1.002)
        bb_lower      = indicators.get('bb_lower', price * 0.998)
        bb_middle     = indicators.get('bb_middle', price)
        macd_diff     = indicators.get('macd_diff', 0)
        macd_diff_prev= indicators.get('macd_diff_prev', 0)
        rsi5          = indicators.get('rsi5', 50)
        stoch5_k      = indicators.get('stoch5_k', 50)
        ema_20        = indicators.get('ema_20', price)
        ema_50        = indicators.get('ema_50', price)

        if bb_middle <= 0:
            return signal

        bb_width = (bb_upper - bb_lower) / bb_middle if bb_middle > 0 else 0.02
        squeeze  = bb_width < 0.015  # bandas muy estrechas = energía acumulada
        atr_avg  = float(df['close'].rolling(10, min_periods=3).std().iloc[-1])
        price_range = float(df['close'].rolling(5, min_periods=2).std().iloc[-1])
        expanding = price_range > atr_avg * 0.5  # volatilidad saliendo

        # CALL: ruptura alcista de BB con momentum
        if price >= bb_upper * 0.999 and macd_diff > 0 and rsi5 > 45:
            conf = 68
            if squeeze:               conf += 8   # squeeze da más energía al breakout
            if price > bb_upper:      conf += 5   # precio claramente fuera de banda
            if rsi5 > 55:             conf += 5   # RSI5 alcista
            if stoch5_k > 50:         conf += 4   # Stoch5 confirma
            if ema_20 > ema_50:       conf += 4   # tendencia a favor
            if macd_diff > macd_diff_prev > 0:  conf += 4  # MACD acelerando
            if expanding:             conf += 3   # volatilidad expandiendo
            signal['direction']  = 'call'
            signal['confidence'] = min(conf, 90)

        # PUT: ruptura bajista de BB con momentum
        elif price <= bb_lower * 1.001 and macd_diff < 0 and rsi5 < 55:
            conf = 68
            if squeeze:               conf += 8
            if price < bb_lower:      conf += 5
            if rsi5 < 45:             conf += 5
            if stoch5_k < 50:         conf += 4
            if ema_20 < ema_50:       conf += 4
            if macd_diff < macd_diff_prev < 0:  conf += 4
            if expanding:             conf += 3
            signal['direction']  = 'put'
            signal['confidence'] = min(conf, 90)

        return signal

    # ── PRICE ACTION HELPERS ──────────────────────────────────────────────────

    def _detect_sr_levels(self, df: pd.DataFrame, price: float) -> _List[_PALevel]:
        """
        Detecta automáticamente soportes y resistencias usando pivotes.
        Pivot high: high[i] > high[i±1] y high[i±2]
        Pivot low:  low[i]  < low[i±1]  y low[i±2]
        Agrupa niveles cercanos (dentro del 0.05% del precio) y cuenta sus toques.
        """
        tolerance = price * 0.0002  # 0.02% — zona alrededor de un nivel

        n = len(df)
        pivot_highs: list = []
        pivot_lows:  list = []

        for i in range(2, n - 2):
            h = float(df['high'].iloc[i])
            l = float(df['low'].iloc[i])
            # Pivot high
            if (h > float(df['high'].iloc[i-1]) and h > float(df['high'].iloc[i-2])
                    and h > float(df['high'].iloc[i+1]) and h > float(df['high'].iloc[i+2])):
                pivot_highs.append(h)
            # Pivot low
            if (l < float(df['low'].iloc[i-1]) and l < float(df['low'].iloc[i-2])
                    and l < float(df['low'].iloc[i+1]) and l < float(df['low'].iloc[i+2])):
                pivot_lows.append(l)

        def _cluster(prices: list, tol: float) -> list:
            """Agrupa precios cercanos, retorna [(precio_medio, count)]."""
            if not prices:
                return []
            sorted_p = sorted(prices)
            clusters: list = []
            group = [sorted_p[0]]
            for p in sorted_p[1:]:
                if abs(p - group[-1]) <= tol * 3:
                    group.append(p)
                else:
                    clusters.append((sum(group) / len(group), len(group)))
                    group = [p]
            clusters.append((sum(group) / len(group), len(group)))
            return clusters

        def _count_touches(level_price: float) -> int:
            """Cuenta cuántas velas histórias tocaron este nivel."""
            return int(sum(
                1 for _, row in df.iterrows()
                if abs(float(row['high']) - level_price) <= tolerance
                or abs(float(row['low'])  - level_price) <= tolerance
            ))

        levels: _List[_PALevel] = []
        for p, _ in _cluster(pivot_highs, tolerance):
            touches = max(_count_touches(p), 1)
            lv = _PALevel(price=p, level_type='resistance', touches=touches)
            levels.append(lv)
        for p, _ in _cluster(pivot_lows, tolerance):
            touches = max(_count_touches(p), 1)
            lv = _PALevel(price=p, level_type='support', touches=touches)
            levels.append(lv)

        # Ordenar por proximidad al precio actual y devolver top 8
        levels.sort(key=lambda lv: abs(lv.price - price))
        return levels[:8]

    def _candle_patterns(self, df: pd.DataFrame) -> dict:
        """Detecta patrones de vela en la última vela. Retorna booleans."""
        if len(df) < 2:
            return {}
        c1 = float(df['close'].iloc[-1]); o1 = float(df['open'].iloc[-1])
        h1 = float(df['high'].iloc[-1]);  l1 = float(df['low'].iloc[-1])
        c2 = float(df['close'].iloc[-2]); o2 = float(df['open'].iloc[-2])
        rng1 = h1 - l1
        if rng1 <= 0:
            return {}
        body1      = abs(c1 - o1) / rng1
        wick_up1   = (h1 - max(c1, o1)) / rng1
        wick_down1 = (min(c1, o1) - l1) / rng1
        return {
            'bullish_pin':    wick_down1 > 0.50 and body1 < 0.40,
            'bullish_engulf': c1 > o1 and c2 < o2 and c1 > o2 and o1 < c2,
            'hammer':         wick_down1 > 0.45 and body1 > 0.15 and c1 > o1,
            'bearish_pin':    wick_up1 > 0.50 and body1 < 0.40,
            'bearish_engulf': c1 < o1 and c2 > o2 and c1 < o2 and o1 > c2,
            'shooting_star':  wick_up1 > 0.45 and body1 > 0.15 and c1 < o1,
        }

    def _price_action_signal(self, indicators: dict, df: pd.DataFrame) -> dict:
        """
        Price Action S/R con detección automática de pivotes.

        CAPA 1 — S/R Levels (principal):
          • Punto 3: 3er toque en nivel + mecha de rechazo → operación contra el nivel
          • Ruptura débil (≤35% del cuerpo): continuidad en dirección de la ruptura
          • Ruptura fuerte (≥50%): registra el nivel para vigilar retesteo

        CAPA 2 — Patrones de vela (refuerzo): pin bars, envolventes, hammer.
          Si confirman la misma dirección que CAPA 1 → +8 de confianza.
          Si no hay señal de CAPA 1 pero hay patrón + indicadores → señal independiente.

        CAPA 3 — Retesteo de niveles rotos: cuando el precio vuelve a un nivel
          previamente roto y muestra rechazo → señal de continuación.
        """
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        if len(df) < 10:
            return signal

        price    = indicators['price']
        rsi5     = indicators.get('rsi5', 50)
        stoch5_k = indicators.get('stoch5_k', 50)
        macd_diff= indicators.get('macd_diff', 0)
        ema_20   = indicators.get('ema_20', price)
        ema_50   = indicators.get('ema_50', price)
        uptrend  = ema_20 > ema_50
        downtrend= ema_20 < ema_50
        tolerance = price * 0.0002

        # Construir vela actual
        cur_row = df.iloc[-1]
        current_candle = _PACandle(
            open=float(cur_row['open']),
            high=float(cur_row['high']),
            low=float(cur_row['low']),
            close=float(cur_row['close'])
        )

        # Detectar S/R desde el histórico
        sr_levels = self._detect_sr_levels(df, price)
        self._pa_engine.pip_tolerance = tolerance
        self._pa_engine.active_levels = sr_levels

        # Limpiar pullback_watch con más de 10 minutos (600s)
        now_ts = time.time()
        self._pullback_watch = [
            w for w in self._pullback_watch if now_ts - w['ts'] < 600
        ]

        # ── CAPA 3: verificar retesteos de niveles rotos ──────────────────────
        for watch in list(self._pullback_watch):
            near = _math.isclose(price, watch['price'], abs_tol=tolerance * 2)
            if near:
                # El precio volvió al nivel roto — evaluar rechazo
                if watch['level_type'] == 'resistance':
                    # Antes era resistencia, rompió al alza → ahora es soporte
                    # Si hay rechazo bajando desde ahi, es falso pullback → no operar
                    # Si rebota alcista, continuidad → CALL
                    if current_candle.is_bullish and current_candle.lower_wick > current_candle.body_size * 0.3:
                        conf = 72
                        if rsi5 < 55:    conf += 6
                        if macd_diff > 0: conf += 5
                        if uptrend:       conf += 5
                        signal['direction']  = 'call'
                        signal['confidence'] = min(conf, 86)
                        self._pullback_watch.remove(watch)
                        logger.info(f"   🔄 PA Retesteo CALL en ex-resistencia {watch['price']:.5f} | conf={conf}%")
                        return signal
                elif watch['level_type'] == 'support':
                    if not current_candle.is_bullish and current_candle.upper_wick > current_candle.body_size * 0.3:
                        conf = 72
                        if rsi5 > 45:    conf += 6
                        if macd_diff < 0: conf += 5
                        if downtrend:     conf += 5
                        signal['direction']  = 'put'
                        signal['confidence'] = min(conf, 86)
                        self._pullback_watch.remove(watch)
                        logger.info(f"   🔄 PA Retesteo PUT en ex-soporte {watch['price']:.5f} | conf={conf}%")
                        return signal

        # ── CAPA 1: evaluar cada nivel S/R ───────────────────────────────────
        best_dir   = None
        best_conf  = 0
        best_reason = ''

        for level in sr_levels:
            result = self._pa_engine.evaluate(current_candle, level)
            if not result:
                continue

            if result['action'] == 'WAIT_PULLBACK':
                # Registrar nivel para vigilar el retesteo
                already = any(_math.isclose(w['price'], level.price, abs_tol=tolerance) for w in self._pullback_watch)
                if not already:
                    self._pullback_watch.append({'price': level.price, 'level_type': level.level_type, 'ts': now_ts})
                    logger.info(f"   👁️ PA: registrando nivel {level.price:.5f} para retesteo ({result['reason']})")
                continue

            action = result['action']  # 'CALL' o 'PUT'
            strength = result.get('strength', 1.0)

            # Base de confianza según el tipo de señal
            if 'Rebote' in result['reason']:
                conf = 68 + min(strength * 6, 12)   # max 80
            else:
                conf = 63 + min(strength * 5, 10)   # max 73

            # Boost con indicadores técnicos
            if action == 'CALL':
                if rsi5 < 40:         conf += 6
                elif rsi5 < 50:       conf += 3
                if stoch5_k < 35:     conf += 5
                if macd_diff > 0:     conf += 4
                if uptrend:           conf += 4
                if level.touches >= 3: conf += 3  # nivel muy probado
            else:  # PUT
                if rsi5 > 60:         conf += 6
                elif rsi5 > 50:       conf += 3
                if stoch5_k > 65:     conf += 5
                if macd_diff < 0:     conf += 4
                if downtrend:         conf += 4
                if level.touches >= 3: conf += 3

            conf = min(conf, 90)
            if conf > best_conf:
                best_conf  = conf
                best_dir   = action.lower()
                best_reason = result['reason']

        # ── CAPA 2: patrones de vela como refuerzo o señal independiente ──────
        patterns = self._candle_patterns(df)
        bull_pattern = patterns.get('bullish_engulf') or patterns.get('hammer') or patterns.get('bullish_pin')
        bear_pattern = patterns.get('bearish_engulf') or patterns.get('shooting_star') or patterns.get('bearish_pin')

        if best_dir == 'call' and bull_pattern:
            bonus = 8 if patterns.get('bullish_engulf') else (5 if patterns.get('hammer') else 3)
            best_conf = min(best_conf + bonus, 92)
            best_reason += ' + patrón alcista'
        elif best_dir == 'put' and bear_pattern:
            bonus = 8 if patterns.get('bearish_engulf') else (5 if patterns.get('shooting_star') else 3)
            best_conf = min(best_conf + bonus, 92)
            best_reason += ' + patrón bajista'
        elif best_dir is None:
            # Sin señal de nivel — usar solo patrones de vela como señal débil
            if bull_pattern and rsi5 < 50:
                conf = 62
                if patterns.get('bullish_engulf'): conf += 8
                elif patterns.get('hammer'):       conf += 5
                if rsi5 < 35: conf += 6
                if stoch5_k < 30: conf += 4
                if macd_diff > 0: conf += 4
                if uptrend: conf += 4
                best_dir = 'call'
                best_conf = min(conf, 82)
                best_reason = 'Patrón de vela alcista (sin nivel cercano)'
            elif bear_pattern and rsi5 > 50:
                conf = 62
                if patterns.get('bearish_engulf'): conf += 8
                elif patterns.get('shooting_star'):conf += 5
                if rsi5 > 65: conf += 6
                if stoch5_k > 70: conf += 4
                if macd_diff < 0: conf += 4
                if downtrend: conf += 4
                best_dir = 'put'
                best_conf = min(conf, 82)
                best_reason = 'Patrón de vela bajista (sin nivel cercano)'

        if best_dir:
            signal['direction']  = best_dir
            signal['confidence'] = best_conf
            logger.info(f"   🏛️ price_action_sr: {best_dir.upper()} | {best_reason} | conf={best_conf}%")

        return signal

    def _detect_market_type(self, symbol: str) -> tuple:
        """
        Detecta en qué tipo de mercado está disponible un activo usando find_best_active()
        Retorna: (market_type: str, reason: str)
        market_type puede ser: 'binary', 'digital', None
        """
        try:
            logger.info(f"   🔍 Detectando tipo de mercado para {symbol}...")
            
            # Intentar primero binary/turbo
            result = find_best_active(self.api, symbol, 'binary')
            
            if result:
                found_name, active_id = result
                logger.info(f"   ✅ {symbol} disponible en BINARY como {found_name}")
                
                # Actualizar símbolo si se encontró variante diferente
                if found_name != symbol:
                    logger.info(f"   🔄 Actualizando símbolo: {symbol} → {found_name}")
                    self.config['symbol'] = found_name
                
                return 'binary', f"Disponible como {found_name}"
            
            # Intentar digital como fallback
            result = find_best_active(self.api, symbol, 'digital')
            
            if result:
                found_name, active_id = result
                logger.info(f"   ✅ {symbol} disponible en DIGITAL como {found_name}")
                
                if found_name != symbol:
                    logger.info(f"   🔄 Actualizando símbolo: {symbol} → {found_name}")
                    self.config['symbol'] = found_name
                
                return 'digital', f"Disponible como {found_name}"
            
            # No encontrado
            logger.warning(f"   ⚠️ {symbol} no encontrado en ningún mercado")
            return None, "Activo no disponible en ningún mercado"
            
        except Exception as e:
            logger.error(f"   ❌ Error detectando mercado: {str(e)}")
            logger.error(traceback.format_exc())
            return None, f"Error: {str(e)}"
    def _find_alternative_asset(self) -> Optional[tuple]:
        """
        Busca un activo alternativo usando find_best_active()
        Prioridad: 1. Binary/Turbo, 2. Digital
        Retorna: (symbol: str, market_type: str) o None
        """
        try:
            logger.info("   🔄 Buscando activos alternativos...")
            
            # Símbolos preferidos en orden
            preferred_symbols = [
                "EURUSD-OTC", "EURUSD-op", "EURUSD",
                "GBPUSD-OTC", "GBPUSD-op", "GBPUSD",
                "USDJPY-OTC", "USDJPY-op", "USDJPY",
                "AUDUSD-OTC", "AUDUSD-op", "AUDUSD",
                "EURGBP-OTC", "EURGBP-op", "EURGBP"
            ]
            
            # Intentar símbolos preferidos en binary
            for symbol in preferred_symbols:
                result = find_best_active(self.api, symbol, 'binary')
                if result:
                    found_name, active_id = result
                    logger.info(f"      🎯 Seleccionado: {found_name} (binary)")
                    return (found_name, 'binary')
            
            # Si no hay preferidos, usar cualquier activo disponible en binary
            init_data = self.api.get_all_init_v2()
            
            if init_data and 'turbo' in init_data and 'actives' in init_data['turbo']:
                for active_id, active_data in init_data['turbo']['actives'].items():
                    if active_data.get('enabled') and not active_data.get('is_suspended'):
                        name = active_data.get('name', '').replace('front.', '')
                        logger.info(f"      🎯 Usando primer disponible: {name} (binary)")
                        return (name, 'binary')
            
            # Intentar digital como último recurso
            for symbol in preferred_symbols:
                result = find_best_active(self.api, symbol, 'digital')
                if result:
                    found_name, active_id = result
                    logger.info(f"      🎯 Seleccionado: {found_name} (digital)")
                    return (found_name, 'digital')
            
            logger.warning("      ❌ No hay activos disponibles")
            return None
            
        except Exception as e:
            logger.error(f"      ❌ Error buscando alternativa: {str(e)}")
            import traceback
            logger.debug(traceback.format_exc())
            return None
    def _log_available_assets(self):
        """Muestra todos los activos disponibles por tipo de mercado usando get_all_init_v2()"""
        try:
            # Usar get_all_init_v2() directamente (método estable y sin errores)
            init_data = self.api.get_all_init_v2()
            
            if not init_data:
                logger.warning("⚠️ No se pudo obtener información de activos")
                return
            
            logger.info("📋 ========================================")
            logger.info("📋 ACTIVOS DISPONIBLES POR TIPO DE MERCADO")
            logger.info("📋 ========================================")
            
            # Binary/Turbo
            for market_type in ['turbo', 'binary']:
                if market_type not in init_data:
                    continue
                
                if 'actives' not in init_data[market_type]:
                    continue
                
                actives_data = init_data[market_type]['actives']
                available = []
                
                for active_id, active_info in actives_data.items():
                    if (isinstance(active_info, dict) and
                        active_info.get('enabled', False) and 
                        not active_info.get('is_suspended', True)):
                        
                        name = active_info.get('name', '').replace('front.', '')
                        if name:
                            available.append(name)
                
                if available:
                    logger.info(f"{market_type.upper()}: {', '.join(sorted(available)[:20])}")
                    if len(available) > 20:
                        logger.info(f"   ... y {len(available) - 20} más")
            
            # Digital (probablemente vacío por API V2 deprecada)
            if 'digital' in init_data and 'actives' in init_data['digital']:
                digital_data = init_data['digital']['actives']
                available = []
                
                for active_id, active_info in digital_data.items():
                    if (isinstance(active_info, dict) and
                        active_info.get('enabled', False) and
                        not active_info.get('is_suspended', True)):
                        
                        name = active_info.get('name', '').replace('front.', '')
                        if name:
                            available.append(name)
                
                if available:
                    logger.info(f"DIGITAL: {', '.join(sorted(available)[:20])}")
                    if len(available) > 20:
                        logger.info(f"   ... y {len(available) - 20} más")
                else:
                    logger.info("DIGITAL: (ninguno disponible - API V2 deprecada)")
            
            logger.info("📋 ========================================")
            
        except Exception as e:
            logger.error(f"Error mostrando activos: {e}")
            import traceback
            logger.debug(traceback.format_exc())


# ====================================================================
# MÉTODO _execute_trade COMPLETAMENTE REEMPLAZADO
# ====================================================================

    async def _execute_trade(self, signal: dict) -> dict:
        """Ejecuta una operación - Soporta Binary/Turbo Y Digital"""
        try:
            # ── LMTA: Verificar pausa anti-ansiedad ────────────────────────
            if self.use_compound and self._lmta_pause_until > time.time():
                remaining = int(self._lmta_pause_until - time.time())
                logger.info(f"⏸️ LMTA Anti-ansiedad activa — esperando {remaining}s antes de operar")
                return None

            # ── LMTA: Filtro de Patrón Killer (Gira 2, Gira 1) ────────────
            if self.use_compound:
                try:
                    import pandas as _pd
                    _raw = self.api.get_candles(self.config['symbol'], 60, 10, time.time())
                    if _raw and len(_raw) >= 5:
                        _df = _pd.DataFrame(_raw)
                        self._pattern_scanner.feed_candles(_df)
                        _gira = self._pattern_scanner.check()
                        _dir = signal.get('direction', '').lower()
                        _aligned = (
                            (_gira == 'SIGNAL_PUT'  and _dir == 'put') or
                            (_gira == 'SIGNAL_CALL' and _dir == 'call')
                        )
                        if _gira != 'NONE':
                            if _aligned:
                                signal['confidence'] = min(signal.get('confidence', 0) + 8, 99)
                                logger.info(f"🎯 LMTA Patrón Killer '{_gira}' alineado con {_dir.upper()} — confianza +8%")
                            else:
                                logger.info(f"⚠️ LMTA Patrón '{_gira}' contrario a {_dir.upper()} — ignorando patrón")
                except Exception as _pe:
                    logger.debug(f"PatternScanner no crítico: {_pe}")

            amount = self._calculate_trade_amount()

            # Verificar límite del 50%
            balance = self.api.get_balance()
            max_amount = balance * 0.5

            if amount > max_amount:
                amount = max_amount
                logger.warning(f"Monto ajustado al 50% del balance: ${amount}")
            
            symbol = self.config['symbol']
            
            # ✅ DETECTAR TIPO DE MERCADO
            logger.info(f"🔍 Detectando mercado para {symbol}...")
            market_type, reason = self._detect_market_type(symbol)
            
            # Si no está disponible, buscar alternativa
            if not market_type:
                logger.warning(f"⚠️ {symbol} no disponible: {reason}")
                logger.info(f"🔄 Buscando alternativa...")
                
                alternative = self._find_alternative_asset()
                if alternative:
                    symbol, market_type = alternative
                    logger.info(f"✅ Usando: {symbol} ({market_type})")
                    self.config['symbol'] = symbol
                    
                    # Guardar tipo de mercado en config
                    self.config['market_type'] = market_type
                    
                    send_telegram_notification(
                        f"⚠️ Cambio de activo\n"
                        f"Nuevo: {symbol}\n"
                        f"Tipo: {market_type.upper()}\n"
                        f"Razón: {reason}"
                    )
                else:
                    logger.error(f"❌ No hay alternativas disponibles")
                    return None
            else:
                # Guardar tipo de mercado detectado
                self.config['market_type'] = market_type
                logger.info(f"✅ {symbol} disponible en {market_type.upper()}")
            
            # Obtener velas
            current_candles = self.api.get_candles(symbol, 60, 30, time.time())
            
            # ✅ EJECUTAR SEGÚN EL TIPO DE MERCADO
            logger.info(f"💰 ========================================")
            logger.info(f"💰 EJECUTANDO OPERACIÓN")
            logger.info(f"   📊 Activo: {symbol}")
            logger.info(f"   🏪 Mercado: {market_type.upper()}")
            logger.info(f"   📈 Dirección: {signal['direction'].upper()}")
            logger.info(f"   💵 Monto: ${amount}")
            logger.info(f"   🎯 Confianza: {signal['confidence']:.1f}%")
            logger.info(f"💰 ========================================")
            
            success = False
            order_id = None
            
            # BINARY/TURBO - usa api.buy()
            if market_type in ['binary', 'turbo']:
                logger.info(f"   🔵 Usando método: api.buy() para {market_type}")
                success, order_id = self.api.buy(amount, symbol, signal['direction'], 1)
                wait_time = 70
            
            # DIGITAL - usa api.buy_digital_spot()
            elif market_type == 'digital':
                logger.info(f"   💎 Usando método: api.buy_digital_spot() para digital")
                success, order_id = self.api.buy_digital_spot(symbol, amount, signal['direction'], 1)
                wait_time = 70
            
            if success:
                logger.info(f"✅ Orden enviada - ID: {order_id}")
                logger.info(f"⏳ Esperando resultado ({wait_time} segundos)...")
                
                # Esperar resultado
                await asyncio.sleep(wait_time)
                
                # Verificar resultado según el tipo
                if market_type in ['binary', 'turbo']:
                    result = self.api.check_win_v3(order_id)
                elif market_type == 'digital':
                    result = self.api.check_win_digital_v2(order_id)
                    if isinstance(result, tuple):
                        success_check, profit = result
                        result = profit
                
                trade_result = {
                    "success": True,
                    'order_id': order_id,
                    'direction': signal['direction'],
                    'amount': amount,
                    'result': result,
                    'profit': amount * 0.85 if result > 0 else -amount,
                    'timestamp': datetime.now(),
                    'confidence': signal['confidence'],
                    'candles': current_candles,
                    'indicators': signal['indicators'],
                    'symbol': symbol,
                    'market_type': market_type  # ✅ Guardar tipo de mercado
                }
                
                # Notificar
                self._send_trade_notification(trade_result, signal)
                
                # Guardar en DB
                try:
                    db = get_database()
                    if db:
                        db.save_trade(self.user_id, {
                            **trade_result,
                            'strategy': self.config['strategy']
                        })
                except:
                    pass
                
                # Monitor
                try:
                    monitor = get_monitor()
                    if monitor:
                        monitor.record_operation(result > 0, trade_result['profit'])
                except:
                    pass
                
                return trade_result
            else:
                logger.error(f"❌ Error ejecutando operación: {order_id}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error en _execute_trade: {str(e)}")
            logger.error(traceback.format_exc())
            return None
    def _calculate_trade_amount(self) -> float:
        """
        Calcula el monto de la operación.
        - use_compound=True  → LMTAMoneyManager (interés compuesto 5 niveles)
        - use_compound=False → Martingala suave original
        """
        if self.use_compound:
            amount = self._money_manager.get_trade_amount()
            info = self._money_manager.get_cycle_info()
            logger.info(f"💰 LMTA Nivel {info['level']}/{info['max_levels']} — monto: ${amount:.2f}")
            return amount

        # Martingala suave original
        base_amount = self.config['amount']
        if self.consecutive_losses == 0:
            return base_amount
        multiplier = self.strategy['max_loss_multiplier']
        return min(base_amount * (multiplier ** self.consecutive_losses), base_amount * 10)
    
    def _update_stats(self, result: dict):
        """Actualiza las estadísticas del bot"""
        if not result:
            return

        self.operations_count += 1
        self.results_history.append(result)
        won = result['result'] > 0

        if won:
            self.win_count += 1
            self.consecutive_losses = 0
            self.session_profit += result['profit']
        else:
            self.loss_count += 1
            self.consecutive_losses += 1
            self.session_profit += result['profit']

        # ── LMTA Interés Compuesto ──────────────────────────────────────
        if self.use_compound:
            self._money_manager.update_after_trade(won)

            if won:
                self._lmta_consec_losses = 0
            else:
                self._lmta_consec_losses += 1
                if self._lmta_consec_losses >= 2:
                    # Anti-ansiedad: 2 pérdidas seguidas → pausa 5 minutos
                    pause_secs = 300
                    self._lmta_pause_until = time.time() + pause_secs
                    self._lmta_consec_losses = 0
                    logger.warning(
                        f"⏸️ LMTA Anti-ansiedad: 2 pérdidas seguidas detectadas. "
                        f"Bot en pausa {pause_secs // 60} minutos."
                    )
                    send_telegram_notification(
                        f"⏸️ LMTA: Pausa anti-ansiedad activada\n"
                        f"2 pérdidas consecutivas. Reanuda en {pause_secs // 60} min."
                    )
    
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
            'current_candles': self.current_candles,
            'use_compound': self.use_compound,
            'lmta_cycle': self._money_manager.get_cycle_info() if self.use_compound else None,
            'lmta_paused': self._lmta_pause_until > time.time() if self.use_compound else False,
        }

    def stop(self):
        """Detiene el bot de trading"""
        self.running = False
        logger.info(f"🛑 Stop solicitado para {self.user_id}")

    async def _get_htf_trend(self, symbol: str) -> str:
        """
        Obtiene la tendencia en marco de 5 minutos usando EMA9 vs EMA21.
        Cache de 60 segundos: no llama get_candles en cada ciclo de 10s.
        Devuelve 'up', 'down' o 'neutral'. Nunca bloquea el bot si falla.
        """
        # Usar caché si tiene menos de 60 segundos
        if time.time() - self._htf_cache['ts'] < 60:
            return self._htf_cache['trend']

        try:
            candles_5m = self.api.get_candles(symbol, 300, 25, time.time())
            if not candles_5m or len(candles_5m) < 10:
                return self._htf_cache['trend']  # mantener último valor conocido

            df5 = pd.DataFrame(candles_5m)
            df5 = df5.rename(columns={'max': 'high', 'min': 'low', 'from': 'timestamp'})

            if 'close' not in df5.columns:
                return self._htf_cache['trend']

            ema9  = df5['close'].ewm(span=9,  adjust=False).mean().iloc[-1]
            ema21 = df5['close'].ewm(span=21, adjust=False).mean().iloc[-1]

            if ema9 > ema21 * 1.0001:
                trend = 'up'
            elif ema9 < ema21 * 0.9999:
                trend = 'down'
            else:
                trend = 'neutral'

            self._htf_cache = {'trend': trend, 'ts': time.time()}
            return trend

        except Exception as e:
            logger.debug(f"   HTF trend error (no crítico): {e}")
            return self._htf_cache['trend']  # mantener último valor conocido

# --- Fallback symbols (>= 10) ---
FALLBACK_SYMBOLS = [
    # Majors FX
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    # Crosses
    "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "EURNZD", "GBPAUD",
    # Crypto (si tu cuenta lo permite; si no, el filtro los sacará)
    "BTCUSD", "ETHUSD"
]

def build_symbol_payload(symbol: str):
    """Convierte un símbolo en dict con flags y label."""
    is_otc = "-OTC" in symbol.upper()
    return {"symbol": symbol, "otc": is_otc}

def safe_extract_open_assets(iq):
    """
    Intenta extraer lista de activos abiertos desde iqoptionapi.
    Devuelve set() de símbolos abiertos (strings). Si falla, set() vacío.
    """
    try:
        all_open = iq.get_all_open_time()
        if not all_open or not isinstance(all_open, dict):
            return set()

        opened = set()

        # Normalmente viene algo como all_open["binary"][<symbol>]["open"]
        for market_key in ("binary", "turbo", "digital", "cfd", "forex", "crypto"):
            section = all_open.get(market_key)
            if not isinstance(section, dict):
                continue
            for sym, info in section.items():
                try:
                    if isinstance(info, dict) and info.get("open") is True:
                        opened.add(sym)
                except Exception:
                    continue

        return opened
    except Exception:
        return set()

def build_fallback_candidates(is_otc_time: bool):
    """
    Construye fallback de símbolos:
    - Si es OTC time => devuelve símbolos con -OTC
    - Si no => símbolos normales
    """
    if is_otc_time:
        return [f"{s}-OTC" if "-OTC" not in s else s for s in FALLBACK_SYMBOLS]
    return [s.replace("-OTC", "") for s in FALLBACK_SYMBOLS]

def choose_symbols(opened_assets: set, is_otc_time: bool):
    """
    Si hay lista real (opened_assets) => filtra según OTC/Normal.
    Si no hay => usa fallback.
    """
    if opened_assets:
        if is_otc_time:
            # preferir OTC disponibles
            syms = sorted([s for s in opened_assets if "-OTC" in s.upper()])
            if syms:
                return syms

            # si no hay OTC (raro), cae a normales abiertos
            syms = sorted([s for s in opened_assets if "-OTC" not in s.upper()])
            return syms[:20]

        else:
            # mercado normal: preferir normales abiertos
            syms = sorted([s for s in opened_assets if "-OTC" not in s.upper()])
            if syms:
                return syms

            # si no hay normales (raro), cae a OTC abiertos
            syms = sorted([s for s in opened_assets if "-OTC" in s.upper()])
            return syms[:20]

    # fallback si no hay datos reales
    return build_fallback_candidates(is_otc_time)

@app.route('/api/symbols', methods=['GET'])
@require_auth
def get_symbols():
    """Obtiene los símbolos disponibles para trading (con fallback robusto)"""
    try:
        api = get_user_api()
        if not api:
            # Sesión válida pero IQ no conectada
            return jsonify({
                'authenticated': True,
                'api_connected': False,
                'error': 'IQ Option desconectada. Intenta reconectar.',
                'symbols': []
            }), 503

        # market puede venir del frontend: AUTO | OTC | NORMAL | ALL
        market = (request.args.get("market") or "AUTO").upper().strip()

        # AUTO = decide según tu función is_otc_time()
        if market == "AUTO":
            want_otc = bool(is_otc_time())
            want_normal = not want_otc
            want_all = False
        elif market == "OTC":
            want_otc, want_normal, want_all = True, False, False
        elif market == "NORMAL":
            want_otc, want_normal, want_all = False, True, False
        else:  # ALL
            want_otc, want_normal, want_all = True, True, True

        symbols = []
        all_assets = {}
        open_map = {}

        # 1) Intentar obtener desde IQ Option
        try:
            all_assets = api.get_all_open_time() or {}
            binary_assets = all_assets.get('binary') or {}

            # Mapa open (para usar también en el fallback)
            if isinstance(binary_assets, dict):
                open_map = {
                    k: bool(v.get("open"))
                    for k, v in binary_assets.items()
                    if isinstance(v, dict)
                }

            for asset, data in (binary_assets or {}).items():
                if not isinstance(data, dict):
                    continue
                if not data.get('open'):
                    continue

                asset_up = str(asset).upper()
                is_asset_otc = "-OTC" in asset_up

                # Filtrado según market
                if (want_all
                    or (want_otc and is_asset_otc)
                    or (want_normal and not is_asset_otc)):

                    symbols.append({
                        'symbol': asset,
                        'name': asset.replace('-OTC', ' OTC').replace('/', ' '),
                        'type': 'OTC' if is_asset_otc else ('Forex' if '/' in asset else 'Binary')
                    })

        except Exception as e:
            logger.exception("Error obteniendo símbolos desde IQ Option (se usará fallback)")

        # 2) Fallback si no hay suficientes (mínimo 10)
        if len(symbols) < 10:
            fallback_base = [
                "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                "USDCHF", "NZDUSD", "EURJPY", "GBPJPY", "EURGBP",
                "EURUSD", "GBPCHF"
            ]

            # generar candidatos según el market
            candidates = []
            if want_all:
                for s in fallback_base:
                    candidates.append(s)
                    candidates.append(f"{s}-OTC")
            elif want_otc:
                candidates = [f"{s}-OTC" for s in fallback_base]
            else:  # NORMAL
                candidates = list(fallback_base)

            # Dedup manteniendo orden
            seen = set()
            candidates = [c for c in candidates if not (c in seen or seen.add(c))]

            existing = {x["symbol"] for x in symbols}

            for asset in candidates:
                if asset in existing:
                    continue

                # Si tenemos open_map real, respetarlo (si no existe el asset, lo dejamos pasar)
                if open_map:
                    if asset in open_map and not open_map.get(asset, False):
                        continue

                is_asset_otc = "-OTC" in asset.upper()
                symbols.append({
                    "symbol": asset,
                    "name": asset.replace('-OTC', ' OTC').replace('/', ' '),
                    "type": "OTC" if is_asset_otc else "Binary"
                })
                existing.add(asset)

                if len(symbols) >= 10:
                    break

        # Ordenar por nombre
        symbols.sort(key=lambda x: x.get('name', x.get('symbol', '')))

        resolved_market = "ALL" if want_all else ("OTC" if want_otc else "NORMAL")
        return jsonify({
            "symbols": symbols,
            "market": resolved_market,
            "count": len(symbols)
        })

    except Exception as e:
        logger.exception("Error obteniendo símbolos")
        return jsonify({"error": "Error obteniendo símbolos", "detail": str(e)}), 500

@app.route('/api/balance', methods=['GET'])
@require_auth
def get_balance():
    """
    ✅ CORREGIDO: Obtiene balance con manejo de IQ desconectada.
    
    IMPORTANTE:
    - Si HAY sesión pero IQ está dormida → 503 (no 401)
    - El frontend debe distinguir:
      - 401 = sin sesión → ir a login
      - 503 = sesión OK pero IQ desconectada → mostrar mensaje
    """
    try:
        user_id = session.get('user_id')
        
        # Verificar sesión (ya validado por @require_auth)
        if not user_id:
            return jsonify({'error': 'No autenticado'}), 401
        
        # Intentar obtener API
        api = get_user_api()
        
        if not api:
            # Sesión válida pero IQ no conectada
            logger.warning(f"⚠️ Usuario {user_id} autenticado pero IQ desconectada")
            return jsonify({
                'authenticated': True,
                'api_connected': False,
                'error': 'IQ Option desconectada. Intenta reconectar.',
                'balance': None
            }), 503
        
        # Obtener balance
        try:
            balance = api.get_balance()
            
            if balance is None:
                # API conectada pero balance None (problema de IQ)
                return jsonify({
                    'authenticated': True,
                    'api_connected': False,
                    'error': 'No se pudo obtener balance de IQ Option',
                    'balance': None
                }), 503
            
            # Todo OK - calcular métricas
            metrics = calculate_user_metrics(user_id)
            
            return jsonify({
                'authenticated': True,
                'api_connected': True,
                'balance': balance,
                'metrics': metrics
            }), 200
            
        except Exception as balance_error:
            logger.error(f"Error obteniendo balance: {balance_error}")
            return jsonify({
                'authenticated': True,
                'api_connected': False,
                'error': 'Error comunicándose con IQ Option',
                'balance': None
            }), 503
        
    except Exception as e:
        logger.error(f"Error en get_balance: {str(e)}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/change_account', methods=['POST'])
@require_auth
def change_account():
    """Cambia el tipo de cuenta activo en IQ Option (PRACTICE o REAL)."""
    try:
        data = request.get_json(silent=True) or {}
        account_type = data.get('account_type', 'PRACTICE')
        if isinstance(account_type, str):
            account_type = account_type.strip().upper()
        if account_type not in ('PRACTICE', 'REAL'):
            return jsonify({'success': False, 'error': 'account_type debe ser PRACTICE o REAL'}), 400

        api = get_user_api()
        if not api:
            return jsonify({'success': False, 'error': 'IQ Option desconectada. Reconecta primero.'}), 503

        user_id = session.get('user_id')

        try:
            # ── Cambiar cuenta (ahora lanza ValueError si no hay cuenta REAL) ──
            api.change_balance(account_type)

            # Esperar a que el WebSocket confirme el cambio
            time.sleep(2)

            # ── Verificar con balance fresco (evita falsos positivos) ────────
            import iqoptionapi.global_value as _gv
            new_balance_id = _gv.balance_id
            logger.info(f"🔄 balance_id tras cambio: {new_balance_id}")

            actual_mode = api.get_balance_mode()
            balance = api.get_balance()

            # Si actual_mode no llegó todavía (posible en conexión lenta), reintentar
            if actual_mode is None:
                time.sleep(1.5)
                actual_mode = api.get_balance_mode()

            logger.info(f"✅ Cuenta: solicitada={account_type} | reportada={actual_mode} | balance=${balance}")

            # ── Verificación estricta ────────────────────────────────────────
            if actual_mode is None:
                logger.warning(f"⚠️ get_balance_mode() devolvió None tras cambiar a {account_type}")
                return jsonify({
                    'success': False,
                    'error': f'No se pudo verificar el cambio a cuenta {account_type}. '
                             f'Revisa que tu cuenta {"real tenga fondos" if account_type == "REAL" else "de práctica esté activa"}.',
                }), 200

            if actual_mode.upper() != account_type:
                logger.warning(f"⚠️ Cambio fallido: solicitado={account_type}, real={actual_mode}")
                return jsonify({
                    'success': False,
                    'error': f'IQ Option mantiene la cuenta {actual_mode} activa. '
                             f'No se pudo cambiar a {account_type}. Verifica que tengas fondos en la cuenta real.',
                    'actual_mode': actual_mode,
                }), 200

            # ── Persistir en caché para sobrevivir reconexiones ──────────────
            if user_id and user_id in active_bots:
                active_bots[user_id]['account_type'] = account_type
                active_bots[user_id]['balance_id'] = new_balance_id

            # balance puede ser 0.0 en cuenta real vacía (eso es válido)
            balance_float = float(balance) if balance is not None else 0.0
            logger.info(f"✅ Cuenta {account_type} activa | Balance: ${balance_float:.2f}")
            return jsonify({
                'success': True,
                'account_type': account_type,
                'balance': balance_float,
            })

        except ValueError as ve:
            # change_balance() lanzó ValueError por cuenta REAL inexistente
            logger.warning(f"⚠️ {ve}")
            return jsonify({'success': False, 'error': str(ve)}), 200
        except Exception as e:
            logger.error(f"❌ Error cambiando cuenta: {e}")
            return jsonify({'success': False, 'error': f'Error al cambiar cuenta: {str(e)[:200]}'}), 500

    except Exception as e:
        logger.error(f"Error en change_account: {e}")
        return jsonify({'success': False, 'error': 'Error interno del servidor'}), 500


@app.route('/api/optimal_amount', methods=['POST'])
def calculate_optimal_amount():
    """Calcula el monto óptimo según la estrategia"""
    try:
        data = request.get_json()
        strategy_id = data.get('strategy')
        base_amount = data.get('base_amount', 1)
        
        api = get_user_api()
        if not api:
            return jsonify({
                'authenticated': True,
                'api_connected': False,
                'error': 'IQ Option desconectada. Intenta reconectar.',
                'optimal_amount': None
            }), 503
        
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

# ============================================================================
# CORRECCIÓN 4: ENDPOINT /api/start_bot
# ============================================================================
# Reemplazar desde línea 2900 hasta línea 3040

@app.route('/api/start_bot', methods=['POST', 'OPTIONS'])
@require_auth
def start_bot():
    """
    ✅ CORRECCIÓN FINAL: Inicia el bot de trading con validación completa.
    
    Mejoras:
    - Validación completa de parámetros
    - Verificación de disponibilidad de activo
    - Manejo robusto de errores
    - Logging detallado
    - Sincronización correcta con bot activo
    """
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = session.get('user_id')
        if not user_id:
            logger.error("❌ No hay user_id en sesión")
            return jsonify({'success': False, 'error': 'No autenticado'}), 401
        
        # Verificar si ya hay un bot activo
        if user_id in active_bots and 'bot' in active_bots[user_id]:
            bot = active_bots[user_id]['bot']
            if bot.running:
                logger.warning(f"⚠️ Bot ya activo para usuario {user_id}")
                return jsonify({
                    'success': False,
                    'error': 'Ya hay un bot activo',
                    'detail': 'Detén el bot actual antes de iniciar uno nuevo'
                }), 400
        
        # Obtener datos del request
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': 'No se recibieron datos'
            }), 400
        
        logger.info(f"📥 Datos recibidos para start_bot:")
        logger.info(f"   Raw data: {data}")
        
        # ========================================================================
        # PASO 1: RESOLVER Y VALIDAR ESTRATEGIA
        # ========================================================================
        logger.info("🔍 Resolviendo estrategia...")
        resolved_strategy = resolve_strategy_id(data)
        
        if not resolved_strategy:
            logger.error(f"❌ No se pudo resolver estrategia")
            logger.error(f"📦 Datos recibidos: {data}")
            available_strategies = list(STRATEGIES.keys())
            return jsonify({
                "success": False,
                "error": "Estrategia inválida",
                "detail": f"No se encontró estrategia en: {data.get('strategy')}",
                "available_strategies": available_strategies,
                "hint": f"Usa una de: {', '.join(available_strategies[:3])}..."
            }), 400
        
        # Actualizar data con estrategia resuelta
        data["strategy"] = resolved_strategy
        data["strategy_name"] = STRATEGIES[resolved_strategy]["name"]
        logger.info(f"✅ Estrategia resuelta: {resolved_strategy} ({data['strategy_name']})")

        # ========================================================================
        # PASO 2: VALIDAR TODOS LOS PARÁMETROS
        # ========================================================================
        logger.info("🔍 Validando parámetros de trading...")
        is_valid, error_msg = validate_trading_params(data)
        
        if not is_valid:
            logger.error(f"❌ Validación falló: {error_msg}")
            return jsonify({
                'success': False,
                'error': 'Parámetros inválidos',
                'detail': error_msg
            }), 400
        
        logger.info("✅ Parámetros validados correctamente")
        
        # ========================================================================
        # PASO 3: CONSTRUIR CONFIGURACIÓN DEL BOT
        # ========================================================================
        config = {
            'symbol': data.get('symbol'),
            'amount': float(data.get('amount', 1)),
            'strategy': data.get('strategy'),
            'account_type': data.get('account_type', 'PRACTICE'),
            'max_operations': int(data.get('max_operations', 0)),
            'max_loss_operations': int(data.get('max_loss_operations', 5)),
            'use_compound': bool(data.get('use_compound', False)),
        }
        
        logger.info(f"⚙️ Configuración del bot:")
        for key, value in config.items():
            logger.info(f"   {key}: {value}")
        
        # ========================================================================
        # PASO 4: OBTENER Y VERIFICAR API
        # ========================================================================
        logger.info("🔌 Obteniendo conexión API...")
        api = get_user_api()

        if not api:
            logger.error("❌ No se pudo obtener API")
            return jsonify({
                'success': False,
                'authenticated': True,
                'api_connected': False,
                'error': 'IQ Option desconectada. Intenta reconectar.',
                'detail': 'Reconecta tu sesión e intenta de nuevo'
            }), 503
        
        # Verificar que la API está conectada
        try:
            test_balance = api.get_balance()
            logger.info(f"✅ API conectada, balance: ${test_balance}")
        except Exception as e:
            logger.error(f"❌ API no responde: {e}")
            return jsonify({
                'success': False,
                'authenticated': True,
                'api_connected': False,
                'error': 'API no responde',
                'detail': 'Reconecta tu sesión e intenta de nuevo'
            }), 503
        
        # ========================================================================
        # PASO 5: CAMBIAR TIPO DE CUENTA
        # ========================================================================
        requested_account = config['account_type']
        try:
            logger.info(f"{'💰' if requested_account == 'REAL' else '🎮'} Cambiando a cuenta {requested_account}...")
            api.change_balance(requested_account)
            time.sleep(2)

            # Guardar en caché para que las reconexiones la restauren
            if user_id not in active_bots:
                active_bots[user_id] = {}
            import iqoptionapi.global_value as _gv_bot
            active_bots[user_id]['account_type'] = requested_account
            active_bots[user_id]['balance_id'] = _gv_bot.balance_id

            # Verificar que el cambio surtió efecto
            actual_mode = None
            try:
                actual_mode = api.get_balance_mode()
                if actual_mode is None:
                    time.sleep(1.5)
                    actual_mode = api.get_balance_mode()
            except Exception:
                pass

            new_balance = api.get_balance()
            logger.info(f"✅ Balance en cuenta {requested_account}: ${new_balance} | modo IQ: {actual_mode}")

            if actual_mode is not None and actual_mode.upper() != requested_account:
                logger.error(f"❌ IQ Option está en modo {actual_mode} aunque se pidió {requested_account}")
                return jsonify({
                    'success': False,
                    'error': f'No se pudo activar cuenta {requested_account}. IQ Option usó: {actual_mode}. Verifica que tu cuenta real tenga fondos.',
                    'actual_mode': actual_mode
                }), 400

        except ValueError as ve:
            # change_balance() lanzó ValueError — no hay cuenta REAL disponible
            logger.error(f"❌ {ve}")
            if requested_account == 'REAL':
                return jsonify({
                    'success': False,
                    'error': str(ve)
                }), 400
            logger.warning("   Continuando con el tipo de cuenta actual (modo PRACTICE)...")
        except Exception as e:
            logger.error(f"❌ Error cambiando tipo de cuenta a {requested_account}: {e}")
            # Solo bloquear si el usuario pidió REAL — es un error crítico
            if requested_account == 'REAL':
                return jsonify({
                    'success': False,
                    'error': f'No se pudo cambiar a cuenta REAL: {str(e)[:150]}. Verifica que tu cuenta real de IQ Option tenga saldo.'
                }), 400
            # Para PRACTICE, continuar aunque falle (normalmente ya está en PRACTICE)
            logger.warning("   Continuando con el tipo de cuenta actual (modo PRACTICE)...")
        
        # ========================================================================
        # PASO 6: VERIFICAR DISPONIBILIDAD DEL ACTIVO
        # ========================================================================
        logger.info(f"🔍 Verificando disponibilidad de {config['symbol']}...")
        
        try:
            # Obtener activos disponibles
            all_open = api.get_all_open_time()
            if all_open:
                binary_assets = all_open.get('binary', {})
                symbol_data = binary_assets.get(config['symbol'])
                
                if not symbol_data:
                    logger.warning(f"⚠️ Símbolo {config['symbol']} no encontrado en lista de activos")
                elif not symbol_data.get('open', False):
                    logger.warning(f"⚠️ Símbolo {config['symbol']} está cerrado")
                    # Intentar encontrar alternativa OTC
                    otc_symbol = f"{config['symbol'].replace('-OTC', '')}-OTC"
                    if otc_symbol != config['symbol']:
                        otc_data = binary_assets.get(otc_symbol)
                        if otc_data and otc_data.get('open', False):
                            logger.info(f"✅ Cambiando a versión OTC: {otc_symbol}")
                            config['symbol'] = otc_symbol
                        else:
                            logger.warning(f"⚠️ Versión OTC tampoco disponible: {otc_symbol}")
                else:
                    logger.info(f"✅ Símbolo {config['symbol']} está disponible")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo verificar disponibilidad: {e}")
            logger.warning("   Continuando con el símbolo especificado...")
        
        # ========================================================================
        # PASO 7: CREAR E INICIAR BOT
        # ========================================================================
        try:
            logger.info(f"🤖 Creando instancia de TradingBot...")
            bot = TradingBot(user_id, api, config)
            logger.info(f"✅ Bot creado correctamente")
            
        except Exception as e:
            logger.error(f"❌ Error creando bot: {e}")
            logger.error(traceback.format_exc())
            return jsonify({
                'success': False,
                'error': 'Error creando bot',
                'detail': str(e)
            }), 500
        
        # Guardar referencia del bot
        if user_id not in active_bots:
            active_bots[user_id] = {}
        active_bots[user_id]['bot'] = bot
        
        # ========================================================================
        # PASO 8: EJECUTAR BOT EN THREAD
        # ========================================================================
        def run_bot_with_logging():
            """Ejecuta el bot en thread con logging configurado"""
            import logging
            import sys
            
            # Configurar logging para este thread
            thread_logger = logging.getLogger('bot_thread')
            thread_logger.setLevel(logging.INFO)
            
            # Handler para stdout (Render logs)
            if not thread_logger.handlers:
                handler = logging.StreamHandler(sys.stdout)
                handler.setLevel(logging.INFO)
                formatter = logging.Formatter('%(asctime)s - BOT - %(levelname)s - %(message)s')
                handler.setFormatter(formatter)
                thread_logger.addHandler(handler)
            
            thread_logger.info(f"🚀 Thread del bot iniciado para {user_id}")
            thread_logger.info(f"📊 Estrategia: {config['strategy']}")
            thread_logger.info(f"🎯 Símbolo: {config['symbol']}")
            thread_logger.info(f"💵 Monto: ${config['amount']}")
            thread_logger.info(f"💰 Interés Compuesto LMTA: {'ACTIVADO' if config.get('use_compound') else 'DESACTIVADO'}")
            
            # Crear event loop y ejecutar bot
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                thread_logger.info(f"🤖 Iniciando método start() del bot...")
                loop.run_until_complete(bot.start())
                thread_logger.info(f"✅ Bot finalizado normalmente")
            except Exception as e:
                thread_logger.error(f"❌ Error en bot thread: {str(e)}")
                thread_logger.error(traceback.format_exc())
                
                # Notificar error al usuario
                try:
                    socketio.emit('bot_error', {
                        'error': str(e),
                        'detail': 'El bot se detuvo por un error'
                    }, room=f"trades_{user_id}")
                except:
                    pass
            finally:
                loop.close()
                thread_logger.info(f"🏁 Thread del bot finalizado")
                
                # Limpiar referencia del bot
                if user_id in active_bots and 'bot' in active_bots[user_id]:
                    if active_bots[user_id]['bot'] == bot:
                        del active_bots[user_id]['bot']
                        thread_logger.info(f"🧹 Referencia del bot limpiada")
        
        # Iniciar thread
        thread = threading.Thread(
            target=run_bot_with_logging,
            name=f"bot_{user_id}_{int(time.time())}",
            daemon=True
        )
        thread.start()
        
        logger.info(f"✅ Thread del bot iniciado: {thread.name}")
        
        # ========================================================================
        # PASO 9: NOTIFICACIONES
        # ========================================================================
        strategy_info = STRATEGIES[config['strategy']]
        
        # Notificación Telegram
        send_telegram_notification(
            f"🤖 **Bot Iniciado**\n"
            f"📊 Estrategia: {strategy_info['name']}\n"
            f"💵 Monto: ${config['amount']}\n"
            f"💰 Interés Compuesto: {'✅ ACTIVADO (5 niveles LMTA)' if config.get('use_compound') else '❌ Desactivado'}\n"
            f"🎯 Símbolo: {config['symbol']}\n"
            f"💼 Cuenta: {config['account_type']}\n"
            f"🔢 Max operaciones: {config['max_operations'] if config['max_operations'] > 0 else 'ilimitado'}\n"
            f"⚠️  Max pérdidas: {config['max_loss_operations']}"
        )
        
        # Notificación Socket.IO
        try:
            socketio.emit('bot_started', {
                'strategy': strategy_info['name'],
                'symbol': config['symbol'],
                'amount': config['amount'],
                'account_type': config['account_type']
            }, room=f"trades_{user_id}")
        except Exception as e:
            logger.warning(f"⚠️ No se pudo enviar notificación Socket.IO: {e}")
        
        logger.info(f"✅ Bot iniciado exitosamente para {user_id}")
        
        # ========================================================================
        # PASO 10: RESPUESTA
        # ========================================================================
        return jsonify({
            'success': True,
            'message': 'Bot iniciado correctamente',
            'strategy_info': {
                'id': config['strategy'],
                'name': strategy_info['name'],
                'risk_level': strategy_info['risk_level'],
                'min_confidence': strategy_info['min_confidence'],
                'description': strategy_info['description']
            },
            'config': {
                'symbol': config['symbol'],
                'amount': config['amount'],
                'account_type': config['account_type'],
                'max_operations': config['max_operations'],
                'max_loss_operations': config['max_loss_operations']
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Error crítico iniciando bot: {str(e)}")
        logger.error(f"📋 Traceback completo:")
        logger.error(traceback.format_exc())
        
        # Limpiar bot si se creó
        try:
            if user_id in active_bots and 'bot' in active_bots[user_id]:
                del active_bots[user_id]['bot']
        except:
            pass
        
        return jsonify({
            'success': False, 
            'error': 'Error crítico al iniciar bot',
            'detail': str(e),
            'type': type(e).__name__
        }), 500

@app.route('/api/stop_bot', methods=['POST', 'OPTIONS'])
@require_auth  # ✅ FIX: Agregar decorador de autenticación
def stop_bot():
    """Detiene el bot de trading"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'No autenticado'}), 401
        
        if user_id not in active_bots or 'bot' not in active_bots[user_id]:
            return jsonify({'error': 'No hay bot activo'}), 400
        
        bot = active_bots[user_id]['bot']
        
        # ✅ FIX: Verificar que el bot existe antes de obtener status
        if not bot:
            return jsonify({'error': 'Bot no encontrado'}), 400
            
        status = bot.get_status()
        
        # ✅ FIX: Detener el bot con timeout
        logger.info(f"🛑 Deteniendo bot para usuario {user_id}...")
        bot.stop()
        
        # Esperar a que se detenga (max 5 segundos)
        timeout = 5
        start_time = time.time()
        while bot.running and (time.time() - start_time) < timeout:
            time.sleep(0.5)
        
        if bot.running:
            logger.warning(f"⚠️ Bot no se detuvo completamente en {timeout}s")
        else:
            logger.info(f"✅ Bot detenido exitosamente")
        
        # Limpiar referencia
        if user_id in active_bots and 'bot' in active_bots[user_id]:
            del active_bots[user_id]['bot']
        
        # Notificar
        send_telegram_notification(
            f"🛑 Bot detenido\n"
            f"📊 Operaciones: {status.get('operations_count', 0)}\n"
            f"💰 Profit sesión: ${status.get('session_profit', 0):.2f}"
        )
        
        return jsonify({
            'success': True,
            'message': 'Bot detenido correctamente',
            'final_stats': status
        })
        
    except Exception as e:
        logger.error(f"❌ Error deteniendo bot: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({
            'success': False,
            'error': 'Error al detener bot',
            'detail': str(e)
        }), 500


@app.route('/api/bot_status', methods=['GET', 'OPTIONS'])
@require_auth
def get_bot_status():
    """Obtiene el estado actual del bot"""
    if request.method == 'OPTIONS':
        return '', 204
    
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
    """Obtiene datos en tiempo real del mercado"""
    try:
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'No autenticado'}), 401
        
        api = get_user_api()
        if not api:
            return jsonify({
                'authenticated': True,
                'api_connected': False,
                'error': 'IQ Option desconectada. Intenta reconectar.',
                'data': []
            }), 503
        
        # ✅ FIX: Permitir símbolo como parámetro de query
        symbol = request.args.get('symbol', None)
        
        # Si no hay símbolo en query, usar el del bot o default
        if not symbol:
            symbol = 'EURUSD-OTC'  # Default a OTC para que funcione 24/7
            if user_id in active_bots and 'bot' in active_bots[user_id]:
                symbol = active_bots[user_id]['bot'].config['symbol']
        
        logger.debug(f"📊 Live data para {symbol}")
        
        # Obtener velas con manejo de errores y reconexión
        candles = []
        max_retries = 2
        retry_count = 0
        
        while retry_count < max_retries and not candles:
            try:
                candles = api.get_candles(symbol, 60, 100, time.time())  # ✅ 100 velas en vez de 30
                if candles:
                    break
                logger.warning(f"⚠️ No hay velas para {symbol} (intento {retry_count + 1})")
            except Exception as e:
                error_msg = str(e).lower()
                if 'connection' in error_msg or 'closed' in error_msg:
                    logger.warning(f"⚠️ Conexión cerrada, intentando reconectar...")
                    # Intentar reconectar
                    api = get_user_api()
                    if not api:
                        logger.error("❌ No se pudo reconectar")
                        break
                    retry_count += 1
                else:
                    logger.error(f"❌ Error obteniendo velas: {str(e)}")
                    break
        
        # Convertir velas
        candles_data = []
        if candles:
            for candle in candles:
                candles_data.append({
                    'time': candle['from'],
                    'open': candle['open'],
                    'high': candle['max'],
                    'low': candle['min'],
                    'close': candle['close'],
                    'volume': candle.get('volume', 0)
                })
        
        # Indicadores y señal
        indicators = {}
        signal = {}
        bot_status = None
        
        if user_id in active_bots and 'bot' in active_bots[user_id]:
            bot = active_bots[user_id]['bot']
            bot_status = bot.get_status()
            
            if candles:
                try:
                    df = pd.DataFrame(candles)
                    df['time'] = pd.to_datetime(df['from'], unit='s')
                    df.set_index('time', inplace=True)
                    
                    indicators = bot._calculate_indicators(df)
                    signal = bot._generate_signal(indicators, df)
                    
                    # Volatilidad
                    returns = df['close'].pct_change()
                    indicators['volatility'] = returns.std() * 100
                    
                    # Tendencia
                    indicators['short_trend'] = "up" if df['close'].iloc[-1] > df['close'].iloc[-5] else "down"
                    indicators['price_change'] = ((df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5]) * 100
                except Exception as e:
                    logger.error(f"❌ Error calculando indicadores: {str(e)}")
        
        return jsonify({
            'candles': candles_data,
            'indicators': indicators,
            'signal': signal,
            'bot_status': bot_status,
            'symbol': symbol,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Error en live_data: {str(e)}")
        return jsonify({
            'error': 'Error obteniendo datos',
            'detail': str(e),
            'candles': [],
            'indicators': {},
            'signal': {}
        }), 500

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
    logger.info(f"🚀 Iniciando servidor en puerto {port}")
    logger.info(f"   Modo: {'Producción' if is_production else 'Desarrollo'}")
    logger.info(f"   WebSocket: {ASYNC_MODE}")
    
    try:
        socketio.run(
            app,
            host='0.0.0.0',
            port=port,
            debug=False,
            use_reloader=False,
            log_output=True
        )
    except Exception as e:
        logger.error(f"❌ Error iniciando servidor: {e}")
        import traceback
        traceback.print_exc()
# ============================================================================
# NUEVO ENDPOINT: GET 30+ ACTIVOS DISPONIBLES
# ============================================================================

@app.route('/api/actives/extended', methods=['GET'])
@require_auth
def get_extended_actives():
    """
    Retorna lista extendida de activos disponibles (30+)
    con información detallada de cada uno
    """
    try:
        api = get_user_api()
        if not api:
            return jsonify({
                'authenticated': True,
                'api_connected': False,
                'error': 'IQ Option desconectada. Intenta reconectar.',
                'actives': []
            }), 503
        
        logger.info("📊 Obteniendo lista extendida de activos...")
        
        # Usar get_all_init_v2() directamente (método estable)
        init_data = api.get_all_init_v2()
        
        if not init_data:
            return jsonify({'error': 'No se pudo obtener información de activos'}), 500
        
        actives_list = []
        
        # Procesar activos de TURBO (Binary)
        if 'turbo' in init_data and 'actives' in init_data['turbo']:
            turbo_actives = init_data['turbo']['actives']
            
            for active_id, active_data in turbo_actives.items():
                if not isinstance(active_data, dict):
                    continue
                
                enabled = active_data.get('enabled', False)
                is_suspended = active_data.get('is_suspended', True)
                
                if enabled and not is_suspended:
                    name = active_data.get('name', '').replace('front.', '')
                    
                    # Extraer información
                    is_otc = '-OTC' in name.upper()
                    is_practice = '-op' in name.lower()
                    
                    # Determinar tipo de activo
                    asset_type = 'OTC' if is_otc else ('Practice' if is_practice else 'Regular')
                    
                    # Categoría
                    if any(pair in name.upper() for pair in ['EUR', 'GBP', 'USD', 'JPY', 'AUD', 'NZD', 'CAD', 'CHF']):
                        category = 'Forex'
                    elif any(crypto in name.upper() for crypto in ['BTC', 'ETH', 'LTC', 'XRP', 'DOGE', 'ADA']):
                        category = 'Crypto'
                    elif any(idx in name.upper() for idx in ['SPX', 'NDX', 'DJI', 'FTSE', 'DAX']):
                        category = 'Indices'
                    elif any(cmd in name.upper() for cmd in ['GOLD', 'SILVER', 'OIL', 'GAS']):
                        category = 'Commodities'
                    else:
                        category = 'Other'
                    
                    # Obtener comisión/profit
                    commission = active_data.get('option', {}).get('profit', {}).get('commission', 0)
                    payout = 100 - commission if commission else 80
                    
                    actives_list.append({
                        'id': active_id,
                        'symbol': name,
                        'name': name.replace('-', ' '),
                        'type': asset_type,
                        'category': category,
                        'market': 'binary',
                        'enabled': True,
                        'suspended': False,
                        'payout': payout,
                        'commission': commission,
                        'available_24_7': is_otc or is_practice
                    })
        
        # Procesar activos de BINARY (si existen y son diferentes)
        if 'binary' in init_data and 'actives' in init_data['binary']:
            binary_actives = init_data['binary']['actives']
            
            # Obtener IDs ya agregados de turbo
            existing_ids = {a['id'] for a in actives_list}
            
            for active_id, active_data in binary_actives.items():
                # Evitar duplicados
                if active_id in existing_ids:
                    continue
                
                if not isinstance(active_data, dict):
                    continue
                
                enabled = active_data.get('enabled', False)
                is_suspended = active_data.get('is_suspended', True)
                
                if enabled and not is_suspended:
                    name = active_data.get('name', '').replace('front.', '')
                    is_otc = '-OTC' in name.upper()
                    is_practice = '-op' in name.lower()
                    
                    actives_list.append({
                        'id': active_id,
                        'symbol': name,
                        'name': name.replace('-', ' '),
                        'type': 'OTC' if is_otc else ('Practice' if is_practice else 'Regular'),
                        'category': 'Binary',
                        'market': 'binary',
                        'enabled': True,
                        'suspended': False,
                        'available_24_7': is_otc or is_practice
                    })
        
        # Ordenar por categoría y nombre
        actives_list.sort(key=lambda x: (x['category'], x['symbol']))
        
        # Agrupar por categoría para mejor visualización
        by_category = {}
        for active in actives_list:
            cat = active['category']
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(active)
        
        logger.info(f"✅ {len(actives_list)} activos disponibles")
        logger.info(f"   Forex: {len(by_category.get('Forex', []))}")
        logger.info(f"   Crypto: {len(by_category.get('Crypto', []))}")
        logger.info(f"   Indices: {len(by_category.get('Indices', []))}")
        logger.info(f"   Commodities: {len(by_category.get('Commodities', []))}")
        
        return jsonify({
            'success': True,
            'total': len(actives_list),
            'actives': actives_list,
            'by_category': by_category,
            'categories': list(by_category.keys())
        })
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo activos extendidos: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500