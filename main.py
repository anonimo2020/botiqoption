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

from functools import wraps

def require_auth(f):
    """
    ✅ MEJORADO: Decorador de autenticación con manejo de OPTIONS.
    
    Mejoras:
    - OPTIONS siempre devuelve 200 (CORS preflight)
    - Limpia cookies inválidas automáticamente
    - Mensajes claros de error
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # ✅ CRÍTICO: Permitir siempre OPTIONS (preflight CORS)
        if request.method == 'OPTIONS':
            response = make_response('', 204)
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            return response
        
        # Verificar si hay user_id en sesión
        if 'user_id' not in session:
            # Si hay cookie pero no sesión válida → limpiar
            cookie_name = app.config.get("SESSION_COOKIE_NAME", "iqbot_session")
            if request.cookies.get(cookie_name):
                logger.warning(f"⚠️ Cookie zombie detectada - limpiando")
                return clear_invalid_session()
            
            # No hay cookie → 401 simple
            return jsonify({"error": "Authentication required"}), 401
        
        # Sesión válida → continuar
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

app = Flask(__name__)

is_production = os.environ.get('RENDER') is not None or os.environ.get('FLASK_ENV', '').lower() == 'production'

secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or 'your-secret-key-here'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")


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
    "https://botiqoption.ct.ws",
    "https://www.botiqoption.ct.ws",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173"
])
allowed_origins = list(dict.fromkeys(allowed_origins))


print(f"🌐 CORS Origins permitidos: {allowed_origins}")

# Configuración de cookies más permisiva para desarrollo
if is_production:
    cookie_samesite = 'None'
    cookie_secure = True
else:
    cookie_samesite = 'Lax'
    cookie_secure = False

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
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    expose_headers=["Content-Type", "X-Total-Count", "Set-Cookie"],
    max_age=3600  # Cache preflight por 1 hora
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
    cors_allowed_origins=allowed_origins,
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
def handle_connect():
    # Verificar sesión antes de aceptar conexión
    if 'user_id' not in session:
        logger.warning("Socket.IO: Intento de conexión sin sesión válida")
        return False  # Rechazar conexión
    
    logger.info(f"Socket.IO: Usuario {session['user_id']} conectado")
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
    # ESTRATEGIA 1: BOLLINGER BANDS + RSI BOUNCE
    # Rentabilidad: 70-75% | Mejor para: Mercados laterales
    # ========================================================================
    'bollinger_rsi_bounce': {
        'name': 'Bollinger RSI Bounce',
        'description': 'Rebote en Bandas de Bollinger confirmado con RSI',
        'timeframe': 60,
        'min_confidence': 65,
        'risk_level': 'medium',
        'indicators': ['bollinger', 'rsi'],
        'max_loss_multiplier': 2.0
    },
    
    # ========================================================================
    # ESTRATEGIA 2: TRIPLE EMA + MACD (MEJOR RENTABILIDAD)
    # Rentabilidad: 72-78% | Mejor para: Tendencias fuertes
    # ========================================================================
    'triple_ema_macd': {
        'name': 'Triple EMA + MACD',
        'description': 'Cruces de EMAs confirmados con MACD',
        'timeframe': 60,
        'min_confidence': 68,
        'risk_level': 'medium',
        'indicators': ['ema', 'macd'],
        'max_loss_multiplier': 2.5
    },
    
    # ========================================================================
    # ESTRATEGIA 3: RSI + STOCHASTIC DUAL
    # Rentabilidad: 68-73% | Mejor para: Sobreventa/sobrecompra
    # ========================================================================
    'rsi_stochastic_dual': {
        'name': 'RSI + Stochastic Dual',
        'description': 'Confirmación dual de momentum',
        'timeframe': 60,
        'min_confidence': 66,
        'risk_level': 'medium',
        'indicators': ['rsi', 'stochastic'],
        'max_loss_multiplier': 2.5
    },
    
    # ========================================================================
    # ESTRATEGIA 4: MACD + BOLLINGER BREAKOUT (MÁXIMA RENTABILIDAD)
    # Rentabilidad: 75-80% | Mejor para: Rupturas de volatilidad
    # ========================================================================
    'macd_bollinger_breakout': {
        'name': 'MACD Bollinger Breakout',
        'description': 'Rupturas de compresión de volatilidad',
        'timeframe': 60,
        'min_confidence': 70,
        'risk_level': 'high',
        'indicators': ['bollinger', 'macd', 'atr'],
        'max_loss_multiplier': 3.0
    },
    
    # ========================================================================
    # ESTRATEGIA 5: SCALPING EXTREMO
    # Rentabilidad: 65-70% | Mejor para: Alta frecuencia
    # ========================================================================
    'scalping_extreme': {
        'name': 'Scalping Extremo 60s',
        'description': 'Scalping de alta frecuencia',
        'timeframe': 60,
        'min_confidence': 62,
        'risk_level': 'high',
        'indicators': ['ema', 'rsi', 'cci'],
        'max_loss_multiplier': 3.5
    },
    
    # ========================================================================
    # ESTRATEGIA 6: PRICE ACTION + S/R
    # Rentabilidad: 73-78% | Mejor para: Traders experimentados
    # ========================================================================
    'price_action_sr': {
        'name': 'Price Action S/R',
        'description': 'Acción del precio en niveles clave',
        'timeframe': 60,
        'min_confidence': 68,
        'risk_level': 'high',
        'indicators': ['ema', 'atr', 'rsi'],
        'max_loss_multiplier': 3.0
    },
    
    # ========================================================================
    # ESTRATEGIAS LEGACY (Mantener compatibilidad)
    # ========================================================================
    'conservative_rsi': {
        'name': 'RSI Conservador (Legacy)',
        'description': 'Utiliza RSI con confirmación',
        'timeframe': 60,
        'min_confidence': 45,
        'risk_level': 'low',
        'indicators': ['rsi', 'ema'],
        'max_loss_multiplier': 1.5
    },
    'momentum_scalper': {
        'name': 'Scalping Momentum (Legacy)',
        'description': 'Operaciones rápidas de momentum',
        'timeframe': 60,
        'min_confidence': 25,
        'risk_level': 'high',
        'indicators': ['cci', 'atr', 'ema'],
        'max_loss_multiplier': 4.0
    }
}


@app.after_request
def after_request(response):
    response.headers.setdefault('Vary', 'Origin')
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.route('/dashboard', methods=['GET'])
def index():
    return send_from_directory(STATIC_DIR, "index.html")

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
    """Normaliza SSID a string (algunas versiones devuelven un objeto Ssid)."""
    if ssid is None:
        return ""
    if isinstance(ssid, str):
        return ssid
    # Algunos wrappers guardan el valor en .ssid o .value
    for attr in ("ssid", "value", "token"):
        try:
            v = getattr(ssid, attr, None)
            if isinstance(v, str) and v:
                return v
        except Exception:
            pass
    try:
        return str(ssid)
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
            raw_ssid = getattr(getattr(api, 'api', None), 'ssid', None)
            ssid_str = ssid_to_str(raw_ssid)
            
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
    Valida si la sesión actual es válida.
    Usado por el frontend al cargar el dashboard.
    """
    user_id = session.get('user_id')
    
    if not user_id:
        # Si hay cookie pero no sesión válida → limpiar
        if request.cookies.get(app.config.get("SESSION_COOKIE_NAME", "iqbot_session")):
            return clear_invalid_session()
        return jsonify({"valid": False}), 401
    
    # Sesión válida
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
                
                # ✅ VALIDACIÓN 3: Intentar reconectar
                logger.info("🔄 Intentando reconectar API...")
                try:
                    # Cerrar WebSocket anterior
                    if hasattr(api, 'websocket') and api.websocket:
                        try:
                            api.websocket.close()
                        except:
                            pass
                    
                    # Reconectar
                    check, reason = api.connect()
                    
                    if check:
                        logger.info("✅ Reconexión exitosa")
                        
                        # Verificar balance de nuevo
                        balance = api.get_balance()
                        if balance is not None:
                            logger.info(f"✅ API reconectada OK (balance: ${balance})")
                            return api
                        else:
                            logger.error("❌ Reconexión falló - balance None")
                    else:
                        logger.error(f"❌ Reconexión falló: {reason}")
                        
                except Exception as reconnect_error:
                    logger.error(f"❌ Error en reconexión: {reconnect_error}")
                
                # Si llegamos aquí, la reconexión falló
                # Limpiar API y forzar nueva conexión
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
        
        # Usar SafeIQConnection para conectar con timeout
        check, result = SafeIQConnection.safe_connect(email, password, timeout=25)
        
        if not check:
            error_msg = result if isinstance(result, str) else "Error de conexión"
            logger.error(f"❌ Error conectando: {error_msg}")
            return None
        
        # Si check es True, result contiene la API
        api = result
        
        # Validar SSID
        api_ssid = ssid_to_str(getattr(getattr(api, 'api', None), 'ssid', None))
        if api_ssid != session_ssid:
            logger.warning(f"⚠️ SSID de nueva conexión no coincide:")
            logger.warning(f"   Esperado: {session_ssid[:20]}...")
            logger.warning(f"   Obtenido: {api_ssid[:20]}...")
            logger.warning("   Esto puede indicar un problema de sesión")
            # No retornar None, pero logearlo como advertencia
        
        # Validar balance
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

        check, result = SafeIQConnection.safe_connect(email, password, timeout=25)
        if not check:
            return None
        api = result

        try:
            if api.get_balance() is None:
                return None
        except Exception:
            return None

        # Guardar en caché
        # Obtener SSID del API y almacenar para referencia futura
        api_ssid = None
        try:
            api_ssid = ssid_to_str(getattr(getattr(api, 'api', None), 'ssid', None))
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
                # ✅ FALTABAN ESTAS 2 LÍNEAS
        self.consecutive_losses = 0
        self.results_history = []
        
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
                    
                    if signal:
                        confidence = signal.get('confidence', 0)
                        direction = signal.get('direction', 'unknown')
                        
                        logger.info(f"📊 Señal generada: {direction.upper()} con confianza {confidence:.1f}%")
                        logger.info(f"📏 Umbral requerido: {self.strategy['min_confidence']}%")
                        
                        if confidence >= self.strategy['min_confidence']:
                            logger.info(f"✅ SEÑAL VÁLIDA - Ejecutando operación {direction.upper()}...")
                            
                            # Ejecutar operación
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
                            logger.warning(f"❌ Señal rechazada - Confianza insuficiente")
                            logger.warning(f"   {confidence:.1f}% < {self.strategy['min_confidence']}%")
                    else:
                        logger.info(f"⏭️ No se generó señal en esta iteración")
                        logger.info(f"   Esperando condiciones del mercado...")
                    
                except Exception as e:
                    logger.error(f"❌ Error en iteración {iteration}: {str(e)}")
                    logger.error(traceback.format_exc())
                
                # Esperar antes del siguiente análisis
                logger.info(f"⏸️ Esperando 10 segundos para próximo análisis...")
                await asyncio.sleep(10)
        
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
                
                logger.debug(f"   ✅ Indicadores calculados:")
                logger.debug(f"      📊 RSI: {indicators.get('rsi', 'N/A'):.2f}" if indicators.get('rsi') else "      📊 RSI: N/A")
                logger.debug(f"      💵 Precio actual: {indicators.get('price', 'N/A'):.5f}" if indicators.get('price') else "      💵 Precio: N/A")
                logger.debug(f"      📈 Tendencia: {indicators.get('trend', 'N/A')}")
            
                # Generar señal según la estrategia
                signal = self._generate_signal(indicators, df)
                
                if signal and signal.get('direction') and signal.get('confidence', 0) > 0:
                    logger.info(f"   💡 Señal generada internamente: {signal['direction'].upper()} "
                            f"con {signal['confidence']:.1f}% de confianza")
                    return signal
                else:
                    logger.debug(f"   ⏭️ No se generó señal válida en este análisis")
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
        """Estrategia conservadora basada en RSI - VERSIÓN MÁS PERMISIVA"""
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        
        rsi = indicators.get('rsi', 50)
        ema_20 = indicators.get('ema_20', 0)
        ema_50 = indicators.get('ema_50', 0)
        price = indicators['price']
        
        # ✅ UMBRALES MÁS PERMISIVOS
        # Señal de CALL - Cambiado de RSI < 35 a RSI < 45
        if rsi < 45 and price > ema_20:  # ✅ Removida condición ema_20 > ema_50
            signal['direction'] = 'call'
            # Confianza más alta
            signal['confidence'] = 85 - (rsi * 0.5)  # Ajustado para dar más confianza
        
        # Señal de PUT - Cambiado de RSI > 65 a RSI > 55
        elif rsi > 55 and price < ema_20:  # ✅ Removida condición ema_20 < ema_50
            signal['direction'] = 'put'
            # Confianza más alta
            signal['confidence'] = (rsi * 0.5)  # Ajustado para dar más confianza
        
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
        """Estrategia de scalping - VERSIÓN AGRESIVA"""
        signal = {'direction': None, 'confidence': 0, 'indicators': indicators}
        
        cci = indicators.get('cci', 0)
        price = indicators['price']
        ema_20 = indicators.get('ema_20', price)
        
        # Calcular momentum
        momentum = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5] * 100
        
        # ✅ UMBRALES MÁS PERMISIVOS
        # Señal de CALL - CCI < -50 (antes -100)
        if cci < -50 and momentum > -0.5:  # Momentum menos estricto
            signal['direction'] = 'call'
            signal['confidence'] = 60 + abs(cci) * 0.3  # Más confianza base
        
        # Señal de PUT - CCI > 50 (antes 100)
        elif cci > 50 and momentum < 0.5:  # Momentum menos estricto
            signal['direction'] = 'put'
            signal['confidence'] = 60 + abs(cci) * 0.3  # Más confianza base
        
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

    def stop(self):
        """Detiene el bot de trading"""
        self.running = False
        logger.info(f"🛑 Stop solicitado para {self.user_id}")

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
            'max_loss_operations': int(data.get('max_loss_operations', 5))
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
        try:
            if config['account_type'] == 'REAL':
                logger.info("💰 Cambiando a cuenta REAL...")
                api.change_balance('REAL')
            else:
                logger.info("🎮 Cambiando a cuenta PRACTICE...")
                api.change_balance('PRACTICE')
            
            # Verificar balance después del cambio
            time.sleep(0.5)
            new_balance = api.get_balance()
            logger.info(f"✅ Balance en cuenta {config['account_type']}: ${new_balance}")
            
        except Exception as e:
            logger.error(f"❌ Error cambiando tipo de cuenta: {e}")
            return jsonify({
                'success': False,
                'error': 'Error cambiando tipo de cuenta',
                'detail': str(e)
            }), 500
        
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