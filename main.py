import os
from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import logging
import datetime
import time
import requests
import numpy as np
from iqoptionapi.stable_api import IQ_Option
from flask_session import Session
import json

import eventlet
eventlet.monkey_patch()

# --- Configuración de la aplicación Flask ---
app = Flask(__name__)

# Configuración de SECRET_KEY desde variables de entorno
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    # Esto solo debería ocurrir en desarrollo si no se establece la variable
    # En producción, Render la forzará a estar presente si la configuras
    app.secret_key = 'super_secret_key_dev_fallback_please_change'
    logging.warning("⚠️ FLASK_SECRET_KEY no está configurada como variable de entorno. ¡CÁMBIALA EN PRODUCCIÓN!")

# Configuración de sesión
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False  # Sesión no permanente por defecto
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_FILE_DIR'] = '/tmp/session_data' # Render usa /tmp para datos efímeros
app.config['SESSION_COOKIE_NAME'] = 'trading_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True # Requiere HTTPS, que Render provee
app.config['SESSION_COOKIE_HTTPONLY'] = True # Evita acceso JS
Session(app)

# Crear directorio de sesiones si no existe
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# Configuración de CORS para el frontend (asegúrate de que origins sean correctos)
CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'https://iqoptionbot.ct.ws']) # Ajustado para tu dominio

# Inicialización de SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', logger=True, engineio_logger=True)

# --- Configuración de Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Variables Globales ---
user_sessions = {}   # Para rastrear conexiones de IQ Option por email
active_bots = {}     # Para rastrear el estado activo/inactivo de bots por usuario

# --- Configuración de Telegram (desde variables de entorno) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# IMPORTANT: Ensure tokens are stripped of any leading/trailing whitespace
if TELEGRAM_BOT_TOKEN:
    TELEGRAM_BOT_TOKEN = TELEGRAM_BOT_TOKEN.strip()
if TELEGRAM_CHAT_ID:
    TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID.strip()

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ ERROR: TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no están configuradas como variables de entorno.")
    # Considera si quieres que el bot no inicie si Telegram no está configurado.
    # Por ahora, continuará, pero los mensajes de Telegram fallarán.

def send_telegram_message(message):
    """Envía mensaje a Telegram con manejo de errores mejorado"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ No se puede enviar mensaje a Telegram: Token o Chat ID no configurados.")
        return

    # CORRECCIÓN IMPORTANTE AQUÍ: api.telegram.org
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    logger.info(f"🌐 Preparing Telegram API request to URL: '{url}'")
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown", # Permite formato como **bold**, *italic*, `code`
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
        logger.info(f"✅ Mensaje enviado a Telegram: {message[:50]}...")
    except requests.exceptions.Timeout:
        logger.error("❌ Error de conexión con Telegram: Tiempo de espera agotado.")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de conexión o HTTP con Telegram: {e} - Respuesta: {response.text if 'response' in locals() else 'N/A'}")
    except Exception as e:
        logger.error(f"❌ Error inesperado al enviar a Telegram: {e}")

# --- Network Diagnostic Function ---
def diagnose_network():
    logger.info("⚡ Ejecutando diagnóstico de red...")

    # Test Google
    try:
        logger.info("🌐 Intentando GET a: https://www.google.com")
        response = requests.get("https://www.google.com", timeout=10)
        if response.status_code == 200:
            logger.info("✅ Conectividad a Google.com: EXITOSA")
        else:
            logger.warning(f"⚠️ Conectividad a Google.com: FALLÓ con status {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de red al intentar conectar a Google.com: {e}")

    # Test Telegram API
    try:
        logger.info("🌐 Intentando GET a: https://api.telegram.org")
        response = requests.get("https://api.telegram.org", timeout=10)
        if response.status_code == 200:
            logger.info("✅ Conectividad a api.telegram.org: EXITOSA")
        else:
            logger.warning(f"⚠️ Conectividad a api.telegram.org: FALLÓ con status {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de red al intentar conectar a api.telegram.org: {e}")
        
    # Test IQ Option (simplified, just the domain)
    try:
        logger.info("🌐 Intentando GET a: https://iqoption.com")
        response = requests.get("https://iqoption.com", timeout=10)
        if response.status_code == 200:
            logger.info("✅ Conectividad a iqoption.com: EXITOSA")
        else:
            logger.warning(f"⚠️ Conectividad a iqoption.com: FALLÓ con status {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de red al intentar conectar a iqoption.com: {e}")

    logger.info("✅ Diagnóstico de red completado.")
# --- Fin de la función de diagnóstico ---


# --- Endpoints HTTP REST ---

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud para verificar que el servidor funciona"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.datetime.now().isoformat(),
        "active_iq_sessions": len(user_sessions),
        "active_running_bots": len([k for k, v in active_bots.items() if v]),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    }), 200

@app.route('/login', methods=['POST'])
def login():
    """Endpoint de login mejorado con mejor manejo de errores y validación."""
    try:
        data = request.get_json()
        if not data:
            logger.warning("Intento de login con JSON inválido o vacío.")
            return jsonify({"success": False, "message": "Datos JSON inválidos"}), 400

        email = data.get('email', '').strip()
        password = data.get('password', '')

        if not email or not password:
            logger.warning("Intento de login sin email o contraseña.")
            return jsonify({"success": False, "message": "Email y contraseña son requeridos"}), 400

        logger.info(f"🔐 Iniciando sesión para: {email}")

        # Cerrar sesión anterior si existe para este email
        if email in user_sessions:
            try:
                user_sessions[email].close_websocket()
                logger.info(f"Sesión IQ Option previa cerrada para {email}.")
            except Exception as e:
                logger.warning(f"Error al intentar cerrar websocket previo para {email}: {e}")
            del user_sessions[email]

        # Crear nueva conexión a IQ Option
        iq = IQ_Option(email, password)

        logger.info(f"Conectando a IQ Option para {email}...")
        
        # --- NUEVO: Manejo de errores para iq.connect() ---
        try:
            connect_result = iq.connect()
        except Exception as e:
            logger.error(f"❌ Excepción al intentar conectar a IQ Option para {email}: {e}")
            return jsonify({"success": False, "message": f"Error de conexión con IQ Option: {e}"}), 500

        if not connect_result:
            logger.warning(f"❌ Falló la conexión inicial a IQ Option para {email}.")
            return jsonify({"success": False, "message": "Error de conexión inicial con IQ Option. Verifica tu conexión a internet o el estado del servicio."}), 401

        # Verificar credenciales
        if not iq.check_connect():
            logger.warning(f"❌ Credenciales incorrectas para {email}.")
            return jsonify({"success": False, "message": "Credenciales incorrectas de IQ Option."}), 401

        logger.info(f"✅ Conectado exitosamente a IQ Option: {email}")

        # Obtener información del perfil
        profile = iq.get_profile()
        if not profile:
            logger.warning(f"⚠️ No se pudo obtener el perfil para {email}. Usando datos básicos.")
            profile = {"name": "Usuario", "email": email}

        # Obtener balance y tipo de cuenta
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()

        # Guardar la instancia de IQ_Option en la sesión de usuario
        user_sessions[email] = iq
        # Establecer la sesión de Flask
        session['user_email'] = email
        session.permanent = True # La sesión durará más (definido por PERMANENT_SESSION_LIFETIME)

        # Enviar notificación a Telegram
        telegram_message = f"""🎯 *NUEVO LOGIN EXITOSO*

👤 *Usuario:* {profile.get('name', 'Desconocido')}
📧 *Email:* `{email}`
💰 *Balance:* ${balance:.2f}
🏦 *Cuenta:* {account_type}
⏰ *Hora:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

✅ *Sistema listo para operar*"""

        send_telegram_message(telegram_message)

        response_data = {
            "success": True,
            "message": "Conectado exitosamente a IQ Option",
            "user": {
                "name": profile.get('name', 'Usuario'),
                "email": email,
                "balance": balance,
                "account_type": account_type
            }
        }

        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"❌ Error inesperado en login para {email}: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": f"Error interno del servidor al iniciar sesión: {str(e)}"}), 500

@app.route('/logout', methods=['POST'])
def logout():
    """Endpoint para cerrar sesión."""
    try:
        if 'user_email' not in session:
            return jsonify({"success": False, "message": "No hay sesión activa para cerrar"}), 400

        email = session['user_email']

        # Detener bot si está activo para este usuario
        if email in active_bots:
            active_bots[email] = False # Señal para detener el hilo del bot
            logger.info(f"Señal de detención enviada al bot de {email}.")

        # Cerrar conexión IQ Option
        if email in user_sessions:
            try:
                user_sessions[email].close_websocket()
                logger.info(f"Conexión IQ Option cerrada para {email}.")
            except Exception as e:
                logger.warning(f"Error al cerrar websocket IQ Option para {email}: {e}")
            del user_sessions[email]

        # Limpiar sesión de Flask
        session.clear()

        send_telegram_message(f"👋 *LOGOUT*\n📧 Usuario: `{email}`\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
        logger.info(f"👋 Logout exitoso para: {email}")

        return jsonify({"success": True, "message": "Sesión cerrada correctamente"}), 200

    except Exception as e:
        logger.error(f"❌ Error en logout para {email}: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

@app.route('/symbols', methods=['GET'])
def get_symbols():
    """Obtener símbolos disponibles (hardcodeados por simplicidad, pero podrían obtenerse de IQ Option)."""
    # Los símbolos que IQ Option ofrece pueden variar. Es mejor obtenerlos dinámicamente si es posible.
    # Por ahora, se mantiene la lista que proporcionaste.
    symbols = [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
        "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC"
    ]
    return jsonify({"symbols": symbols}), 200

@app.route('/balance', methods=['GET'])
def get_balance():
    """Obtener balance actual del usuario autenticado."""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']
        iq = user_sessions.get(email)

        if not iq or not iq.check_connect():
            # Si la conexión se perdió, intenta reconectar antes de fallar
            logger.warning(f"Conexión IQ Option perdida para {email} al solicitar balance. Intentando reconectar...")
            if iq and iq.connect():
                logger.info(f"Reconectado exitosamente a IQ Option para {email}.")
            else:
                return jsonify({"error": "Sesión expirada o conexión perdida. Por favor, inicia sesión nuevamente."}), 403

        balance = iq.get_balance()
        account_type = iq.get_balance_mode()

        return jsonify({
            "balance": balance,
            "account_type": account_type
        }), 200

    except Exception as e:
        logger.error(f"❌ Error obteniendo balance para {email}: {str(e)}", exc_info=True)
        return jsonify({"error": "Error interno al obtener balance"}), 500

@app.route('/start_bot', methods=['POST'])
def start_bot():
    """Iniciar bot de trading."""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']
        iq = user_sessions.get(email)

        if not iq or not iq.check_connect():
            # Si la conexión se perdió, intenta reconectar antes de fallar
            logger.warning(f"Conexión IQ Option perdida para {email} al iniciar bot. Intentando reconectar...")
            if iq and iq.connect():
                logger.info(f"Reconectado exitosamente a IQ Option para {email}.")
            else:
                return jsonify({"error": "Sesión IQ Option expirada o inválida. Por favor, inicia sesión nuevamente."}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Datos JSON inválidos"}), 400

        symbol = data.get('symbol', 'EURUSD').upper() # Asegurar mayúsculas para el símbolo
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE').upper() # Asegurar mayúsculas

        # Validaciones de entrada
        if amount <= 0:
            return jsonify({"error": "El monto debe ser un número positivo."}), 400
        if amount > 10000: # Límite arbitrario para evitar errores de montos excesivos
             return jsonify({"error": "Monto máximo de operación permitido es $10,000."}), 400
        if martingalas < 0:
            return jsonify({"error": "El número de martingalas no puede ser negativo."}), 400

        # Verificar si ya hay un bot activo para este usuario
        if active_bots.get(email, False):
            return jsonify({"error": "Ya hay un bot activo para esta sesión. Deténgalo primero."}), 400

        # Cambiar tipo de cuenta en IQ Option
        iq.change_balance(account_type)
        current_iq_balance_mode = iq.get_balance_mode() # Verificar el modo actual
        if current_iq_balance_mode != account_type:
            logger.warning(f"⚠️ No se pudo cambiar el balance a {account_type} para {email}. Actual: {current_iq_balance_mode}")
            return jsonify({"error": f"No se pudo cambiar el tipo de cuenta a {account_type}. Intenta de nuevo."}), 400

        # Verificar balance antes de iniciar el bot
        balance = iq.get_balance()
        if amount > balance:
            return jsonify({"error": f"Fondos insuficientes en cuenta {account_type}. Balance: ${balance:.2f}."}), 400

        # Marcar bot como activo para el usuario
        active_bots[email] = True

        # Enviar notificación de inicio a Telegram
        start_message = f"""🚀 *BOT INICIADO*

👤 *Usuario:* `{email}`
📈 *Símbolo:* {symbol}
💰 *Monto inicial:* ${amount:.2f}
🎯 *Martingalas:* {martingalas}
🏦 *Cuenta:* {account_type}
⏰ *Inicio:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🤖 *Bot ejecutándose...*"""

        send_telegram_message(start_message)
        socketio.emit('bot_status', {'message': f"Bot iniciado para {symbol} con ${amount:.2f} en cuenta {account_type}.", 'status': 'running'}, room=session.sid)

        # Iniciar la lógica del bot en un hilo separado
        socketio.start_background_task(run_bot, iq, symbol, amount, martingalas, email, session.sid)

        return jsonify({"message": "Bot iniciado correctamente. Consulta el estado en Telegram o en la consola."}), 200

    except ValueError as e:
        logger.error(f"❌ Error de validación al iniciar bot: {str(e)}")
        return jsonify({"error": f"Valor inválido proporcionado: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"❌ Error inesperado al iniciar bot para {email}: {str(e)}", exc_info=True)
        return jsonify({"error": "Error interno del servidor al iniciar el bot."}), 500

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    """Detener bot activo."""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']

        if email in active_bots and active_bots[email]:
            active_bots[email] = False # Establecer la bandera para que el hilo del bot se detenga
            send_telegram_message(f"🛑 *SOLICITUD DE DETENCIÓN RECIBIDA*\n👤 Usuario: `{email}`\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
            socketio.emit('bot_status', {'message': "Solicitud de detención enviada al bot.", 'status': 'stopping'}, room=session.sid)
            logger.info(f"Señal de detención enviada al bot de {email}.")
            return jsonify({"message": "Señal para detener el bot enviada. Puede tardar unos segundos en detenerse completamente."}), 200
        else:
            return jsonify({"error": "No hay un bot activo para esta sesión."}), 400

    except Exception as e:
        logger.error(f"❌ Error deteniendo bot para {email}: {str(e)}", exc_info=True)
        return jsonify({"error": "Error interno al detener el bot."}), 500

# --- Lógica del Bot y Funciones Auxiliares ---

def calculate_indicators(candles):
    """Calcular indicadores técnicos (RSI, MACD, Stochastic) a partir de velas."""
    try:
        if len(candles) < 30: # Se necesitan al menos 30 velas para RSI/MACD de 14/26 periodos
            logger.warning("⚠️ Insuficientes velas para cálculos precisos de indicadores.")
            return None

        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])

        # RSI
        # Asegurarse de tener suficientes datos para el período de 14
        if len(closes) < 15: # Need at least 15 candles for 14-period RSI calculation
            logger.warning("⚠️ Insuficientes velas para calcular RSI (requiere al menos 15).")
            return None

        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        # Simple Moving Average for initial calculation for 14 periods
        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])

        rs = avg_gain / avg_loss if avg_loss != 0 else 100 # Evitar división por cero
        rsi = 100 - (100 / (1 + rs))

        # MACD (EMA 12, 26, Signal 9)
        # Necesitamos suficientes datos para EMA de 26 periodos
        if len(closes) < 27:
            logger.warning("⚠️ Insuficientes velas para calcular MACD (requiere al menos 27).")
            return None

        # Función de EMA (aproximada para fines de ejemplo, bibliotecas como `ta` son mejores)
        def calculate_ema(data, period):
            ema = [sum(data[:period]) / period]
            k = 2 / (period + 1)
            for i in range(period, len(data)):
                ema.append((data[i] - ema[-1]) * k + ema[-1])
            return ema[-1] # Última EMA

        ema12 = calculate_ema(closes, 12)
        ema26 = calculate_ema(closes, 26)
        macd = ema12 - ema26

        # Calcular línea de señal (EMA de 9 periodos del MACD)
        # Esto es una simplificación, normalmente necesitarías una serie de valores MACD
        # para calcular la EMA de la línea de señal. Para un cálculo en tiempo real
        # basado en la última vela, se simplifica el "signal" con la última EMA.
        # Para mayor precisión, usar una biblioteca de TA real.
        signal = calculate_ema(closes, 9) # Esto no es una EMA del MACD, sino una EMA del precio

        # Stochastic (14, 3, 3)
        period_stoch = min(14, len(highs)) # Usar el menor entre 14 y el número de velas disponibles
        if period_stoch < 1: # Asegurar que hay al menos 1 vela para cálculo
            logger.warning("⚠️ Insuficientes velas para calcular Stochastic.")
            return None

        lowest_low = np.min(lows[-period_stoch:])
        highest_high = np.max(highs[-period_stoch:])

        if highest_high != lowest_low:
            stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
        else:
            stoch_k = 50 # Si el rango es cero, el valor medio es 50

        # stoch_d es el promedio móvil de 3 periodos de stoch_k.
        # Aquí se simula con el último stoch_k. Para un cálculo real, necesitarías
        # una serie de valores de stoch_k.
        stoch_d = stoch_k # Simplificación

        return {
            "rsi": round(rsi, 2),
            "macd": round(macd, 4),
            "signal": round(signal, 4), # Nota: esta es una simplificación, no la señal real de MACD
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2), # Nota: esta es una simplificación
            "price": round(closes[-1], 5)
        }

    except Exception as e:
        logger.error(f"❌ Error calculando indicadores: {e}", exc_info=True)
        return None

def get_signal(indicators):
    """Generar señal de trading basada en indicadores."""
    if not indicators:
        return None

    rsi = indicators.get('rsi')
    macd = indicators.get('macd')
    signal_line = indicators.get('signal') # Usando el nombre para evitar confusión
    stoch_k = indicators.get('stoch_k')

    # Asegurarse de que todos los indicadores necesarios estén presentes
    if any(x is None for x in [rsi, macd, signal_line, stoch_k]):
        logger.warning("No se pudo generar señal debido a indicadores faltantes.")
        return None

    # Condiciones para CALL (compra)
    call_conditions = [
        rsi < 30,  # RSI sobrevendido
        macd > signal_line,  # MACD alcista (cruza por encima de la línea de señal)
        macd > 0, # MACD positivo, confirma tendencia alcista
        stoch_k < 20 # Stochastic sobrevendido
    ]

    # Condiciones para PUT (venta)
    put_conditions = [
        rsi > 70,  # RSI sobrecomprado
        macd < signal_line,  # MACD bajista (cruza por debajo de la línea de señal)
        macd < 0, # MACD negativo, confirma tendencia bajista
        stoch_k > 80 # Stochastic sobrecomprado
    ]

    # Contar condiciones que se cumplen
    call_score = sum(call_conditions)
    put_score = sum(put_conditions)

    # Lógica de decisión: requiere al menos 3 condiciones fuertes
    if call_score >= 3:
        return 'call'
    elif put_score >= 3:
        return 'put'
    else:
        return None # No hay señal clara

def run_bot(iq_api_instance, symbol, initial_amount, martingalas_limit, email, sid):
    """Función principal del bot de trading que se ejecuta en un hilo separado."""
    current_amount = initial_amount
    consecutive_losses = 0
    total_trades = 0
    # Calcular el monto máximo que se gastaría si todas las martingalas fallan
    # Esto es initial_amount * (2^0 + 2^1 + ... + 2^martingalas_limit)
    # Suma de una serie geométrica: initial_amount * (2^(martingalas_limit + 1) - 1)
    max_risk_per_series = initial_amount * ((2**(martingalas_limit + 1)) - 1)


    logger.info(f"🤖 Bot iniciado para {email} - {symbol} (SID: {sid})")
    socketio.emit('bot_status', {'message': f"Bot iniciado para {symbol}.", 'status': 'running'}, room=sid)

    while active_bots.get(email, False): # El bot se ejecuta mientras la bandera sea True
        try:
            # 1. Verificar conexión IQ Option
            if not iq_api_instance.check_connect():
                logger.warning(f"Conexión IQ Option perdida para {email}. Intentando reconectar...")
                send_telegram_message(f"❌ *CONEXIÓN IQOPTION PERDIDA*\n👤 Usuario: `{email}`\n🔄 Intentando reconectar...")
                socketio.emit('bot_status', {'message': "Conexión IQ Option perdida, intentando reconectar...", 'status': 'reconnecting'}, room=sid)
                if not iq_api_instance.connect():
                    logger.error(f"Fallo al reconectar a IQ Option para {email}. Deteniendo bot.")
                    send_telegram_message(f"💀 *FALLO CRÍTICO: RECONEXIÓN IQOPTION FALLIDA*\n👤 Usuario: `{email}`\n🚫 Bot detenido.")
                    socketio.emit('bot_status', {'message': "Fallo al reconectar con IQ Option. Bot detenido.", 'status': 'error'}, room=sid)
                    active_bots[email] = False # Detener el bot
                    break
                logger.info(f"IQ Option reconectado para {email}.")
                socketio.emit('bot_status', {'message': "Reconexión exitosa con IQ Option.", 'status': 'running'}, room=sid)


            # 2. Obtener velas
            # Se usa el tiempo actual y se pide 100 velas de 1 minuto (60 segundos)
            end_time = time.time()
            candles = iq_api_instance.get_candles(symbol, 60, 100, end_time)

            if not candles or len(candles) < 30:
                logger.warning(f"⚠️ Datos de velas insuficientes para {symbol}. Reintentando en 30s.")
                socketio.emit('bot_status', {'message': f"Datos de velas insuficientes para {symbol}. Esperando...", 'status': 'waiting'}, room=sid)
                time.sleep(30)
                continue

            # 3. Calcular indicadores
            indicators = calculate_indicators(candles)
            if not indicators:
                logger.warning(f"⚠️ No se pudieron calcular indicadores para {symbol}. Reintentando en 30s.")
                socketio.emit('bot_status', {'message': f"Error al calcular indicadores para {symbol}. Esperando...", 'status': 'waiting'}, room=sid)
                time.sleep(30)
                continue

            # 4. Generar señal
            direction = get_signal(indicators)

            # 5. Emitir análisis y potencial señal
            analysis_message_telegram = f"""📊 *ANÁLISIS TÉCNICO - {symbol}*

💹 *Precio actual:* {indicators['price']:.5f}
📈 *RSI:* {indicators['rsi']:.1f}
📊 *MACD:* {indicators['macd']:.4f}
📉 *Signal:* {indicators['signal']:.4f}
🎯 *Stoch K:* {indicators['stoch_k']:.1f}

{"🟢 *SEÑAL: " + direction.upper() + "*" if direction else "🟡 *Sin señal clara*"}"""

            # Puedes emitir este análisis al frontend si lo deseas
            socketio.emit('bot_analysis', {
                'symbol': symbol,
                'price': indicators['price'],
                'rsi': indicators['rsi'],
                'macd': indicators['macd'],
                'stoch_k': indicators['stoch_k'],
                'signal': direction
            }, room=sid)

            send_telegram_message(analysis_message_telegram)

            if direction and active_bots.get(email, False): # Doble chequeo de la bandera
                # 6. Verificar balance antes de operar
                balance = iq_api_instance.get_balance()
                if current_amount > balance:
                    stop_message = f"""🚫 *BOT DETENIDO - FONDOS INSUFICIENTES*

💰 *Monto requerido:* ${current_amount:.2f}
💳 *Balance actual:* ${balance:.2f}
📊 *Total operaciones:* {total_trades}
👤 *Usuario:* `{email}`

🛡️ *Bot detenido por seguridad*"""
                    send_telegram_message(stop_message)
                    socketio.emit('bot_status', {'message': f"Bot detenido: Fondos insuficientes. Balance: ${balance:.2f}", 'status': 'stopped', 'reason': 'insufficient_funds'}, room=sid)
                    active_bots[email] = False
                    break # Salir del bucle del bot

                # 7. Ejecutar operación
                logger.info(f"Iniciando operación: {direction.upper()} en {symbol} con ${current_amount:.2f}")
                socketio.emit('bot_status', {'message': f"Ejecutando operación {direction.upper()} por ${current_amount:.2f}...", 'status': 'trading'}, room=sid)
                trade_result = execute_trade(iq_api_instance, symbol, current_amount, direction, email, sid)
                total_trades += 1

                if trade_result['result'] == 'WIN':
                    current_amount = initial_amount # Resetear monto al ganar
                    consecutive_losses = 0
                    logger.info(f"✅ Operación GANADA en {symbol}. Ganancia: ${trade_result['profit']:.2f}")
                    win_message = f"""✅ *OPERACIÓN GANADA*

📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto invertido:* ${trade_result['amount']:.2f}
💵 *Ganancia neta:* ${trade_result['profit']:.2f}
📊 *Total operaciones:* {total_trades}
👤 *Usuario:* `{email}`

🎉 *¡Excelente trabajo!*"""
                    send_telegram_message(win_message)
                    socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'WIN', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': 'Operación ganada!'}, room=sid)

                elif trade_result['result'] == 'LOSS':
                    consecutive_losses += 1
                    logger.info(f"❌ Operación PERDIDA en {symbol}. Pérdida: ${abs(trade_result['profit']):.2f}")
                    loss_message = f"""❌ *OPERACIÓN PERDIDA*

📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto invertido:* ${trade_result['amount']:.2f}
💸 *Pérdida:* ${abs(trade_result['profit']):.2f}
🔄 *Pérdidas consecutivas:* {consecutive_losses}
📊 *Total operaciones:* {total_trades}
👤 *Usuario:* `{email}`"""

                    if consecutive_losses <= martingalas_limit:
                        current_amount *= 2 # Aplicar Martingala
                        loss_message += f"\n\n🎲 *MARTINGALA ACTIVADA*\n💰 *Nuevo monto:* ${current_amount:.2f}\n🎯 *Martingalas restantes:* {martingalas_limit - consecutive_losses}"
                        send_telegram_message(loss_message)
                        socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'LOSS', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': 'Operación perdida. Aplicando Martingala.', 'martingalas_left': martingalas_limit - consecutive_losses, 'next_amount': current_amount}, room=sid)
                    else:
                        loss_message += "\n\n🚫 *MARTINGALAS AGOTADAS*"
                        send_telegram_message(loss_message)
                        socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'LOSS', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': 'Operación perdida. Martingalas agotadas. Bot detenido.', 'martingalas_left': 0}, room=sid)
                        active_bots[email] = False # Detener el bot si se agotan las martingalas
                        break # Salir del bucle del bot

                elif trade_result['result'] == 'DRAW':
                    # Si la operación es un empate, no se pierde ni se gana dinero.
                    # Se puede decidir si reiniciar el monto o mantenerlo.
                    # Para el martingala, generalmente se considera un empate como no pérdida,
                    # por lo que no incrementamos consecutive_losses y mantenemos el monto.
                    logger.info(f"⚪ Operación EMPATE en {symbol}.")
                    send_telegram_message(f"⚪ *OPERACIÓN EMPATE*\n📈 *Símbolo:* {symbol}\n💰 *Monto:* ${trade_result['amount']:.2f}\n👤 *Usuario:* `{email}`\n📊 *Total operaciones:* {total_trades}")
                    socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'DRAW', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': 'Operación fue un empate.'}, room=sid)
                    current_amount = initial_amount # Reiniciar monto después de empate

                else: # ERROR en la operación
                    logger.error(f"🔴 Error al ejecutar operación para {email}.")
                    send_telegram_message(f"🔴 *ERROR EN OPERACIÓN*\n👤 Usuario: `{email}`\n📈 Símbolo: {symbol}\n❌ Detalles: {trade_result.get('message', 'Desconocido')}")
                    socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'ERROR', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': trade_result.get('message', 'Error desconocido en operación.')}, room=sid)
                    # Decide si quieres detener el bot por un error de operación
                    # active_bots[email] = False
                    # break

                # Pausa entre operaciones para evitar sobrecargar la API de IQ Option
                # Y dar tiempo para que la siguiente vela se forme y se pueda re-analizar.
                logger.info(f"Pausando {90} segundos antes de la próxima operación...")
                socketio.emit('bot_status', {'message': "Esperando la próxima señal...", 'status': 'waiting_signal'}, room=sid)
                time.sleep(90) # Espera 90 segundos antes de la próxima iteración

            else: # Sin señal clara o bot detenido externamente
                logger.info(f"🟡 Sin señal clara para {symbol}. Reintentando análisis en 30s.")
                socketio.emit('bot_status', {'message': f"Sin señal clara para {symbol}. Esperando...", 'status': 'waiting_signal'}, room=sid)
                time.sleep(30) # Espera un tiempo más corto si no hay señal

        except Exception as e:
            logger.error(f"❌ Error en el bucle principal del bot para {email}: {e}", exc_info=True)
            send_telegram_message(f"⚠️ *ERROR CRÍTICO EN BOT*\n👤 Usuario: `{email}`\n❌ Error: {e}\n🚫 *Bot detenido*")
            socketio.emit('bot_status', {'message': f"Error crítico en el bot: {e}. Bot detenido.", 'status': 'error'}, room=sid)
            active_bots[email] = False # Detener el bot en caso de error crítico
            break # Salir del bucle del bot

    logger.info(f"🛑 Bot detenido para {email} - {symbol} (SID: {sid}).")
    socketio.emit('bot_status', {'message': "Bot detenido.", 'status': 'stopped'}, room=sid)
    send_telegram_message(f"✅ *BOT DETENIDO*\n👤 Usuario: `{email}`\n📊 *Total operaciones:* {total_trades}\n⏰ *Fin:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# --- Funciones Auxiliares de Trading (PLACEHOLDERS, necesitas implementarlas) ---
def execute_trade(iq_api_instance, symbol, amount, direction, email, sid):
    """
    Simula o ejecuta una operación real.
    Devuelve un diccionario con el resultado: {'result': 'WIN'|'LOSS'|'DRAW'|'ERROR', 'amount': X, 'profit': Y, 'message': '...'}.
    """
    logger.info(f"Ejecutando operación simulada: {direction.upper()} {symbol} ${amount}")
    # --- IMPLEMENTACIÓN REAL AQUÍ ---
    # Esto es solo un ejemplo de cómo manejar el resultado.
    # Necesitas usar iq_api_instance.buy() o similar.

    # Ejemplo de operación binaria
    # Se recomienda usar opciones binarias en la API de IQ Option
    # Ejemplo de compra de opciones binarias:
    # check, order_id = iq_api_instance.buy(amount, symbol, direction, 1) # 1 minuto de expiración
    # if check:
    #     logger.info(f"Operación {order_id} iniciada. Esperando resultado...")
    #     # Esperar el resultado de la operación
    #     for _ in range(60): # Esperar hasta 60 segundos por el resultado
    #         if iq_api_instance.check_win_v3(order_id): # O iq_api_instance.check_win()
    #             result_data = iq_api_instance.check_win_v3(order_id)
    #             if result_data == "win":
    #                 profit = amount * iq_api_instance.get_all_profit()[symbol] # Aproximado
    #                 return {'result': 'WIN', 'amount': amount, 'profit': profit, 'message': 'Ganada'}
    #             elif result_data == "lose":
    #                 return {'result': 'LOSS', 'amount': amount, 'profit': -amount, 'message': 'Perdida'}
    #             elif result_data == "equal":
    #                 return {'result': 'DRAW', 'amount': amount, 'profit': 0, 'message': 'Empate'}
    #             break # Salir del bucle una vez que el resultado está disponible
    #         time.sleep(1)
    #     logger.warning(f"Timeout esperando resultado de operación {order_id}. Considerado ERROR.")
    #     return {'result': 'ERROR', 'amount': amount, 'profit': 0, 'message': 'Tiempo de espera agotado para el resultado.'}
    # else:
    #     logger.error(f"Error al iniciar operación: {iq_api_instance.buy(amount, symbol, direction, 1)}")
    #     return {'result': 'ERROR', 'amount': amount, 'profit': 0, 'message': 'Fallo al iniciar la operación de compra.'}

    # *** MOCKUP DE RESULTADO PARA PRUEBAS (DESCOMENTA PARA PROBAR SIN CONEXIÓN REAL) ***
    # from random import choice
    # results = ['WIN', 'LOSS', 'DRAW']
    # random_result = choice(results)
    # if random_result == 'WIN':
    #     profit = amount * 0.82 # Ejemplo de 82% de ganancia
    # elif random_result == 'LOSS':
    #     profit = -amount
    # else:
    #     profit = 0
    # time.sleep(5) # Simula el tiempo de la operación
    # return {'result': random_result, 'amount': amount, 'profit': profit, 'message': f'Resultado simulado: {random_result}'}
    # *** FIN MOCKUP ***

    # Placeholder si el mockup está comentado y no hay implementación real
    logger.error("La función execute_trade necesita una implementación real para comprar en IQ Option.")
    return {'result': 'ERROR', 'amount': amount, 'profit': 0, 'message': 'Función execute_trade no implementada.'}


# --- Eventos de SocketIO (si usas SocketIO en tu frontend) ---
@socketio.on('connect')
def test_connect():
    logger.info(f"✨ Cliente conectado a SocketIO: {request.sid}")
    emit('my response', {'data': 'Conectado'}, room=request.sid)

@socketio.on('disconnect')
def test_disconnect():
    logger.info(f"🔌 Cliente desconectado de SocketIO: {request.sid}")
    # Puedes limpiar sesiones si lo deseas aquí, aunque el logout ya lo hace.


# --- Inicio de la aplicación Flask y SocketIO ---
if __name__ == '__main__':
    logger.info("🚀 Iniciando servidor de trading bot...")
    
    # --- LLAMADA AL DIAGNÓSTICO DE RED ---
    diagnose_network()
    # ------------------------------------

    send_telegram_message("🚀 *SERVIDOR DE TRADING INICIADO*\n⏰ " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # Determinar si estamos en producción (Render)
    # Render establece la variable de entorno PORT automáticamente
    port = int(os.environ.get('PORT', 5000))
    is_production = os.environ.get('FLASK_ENV') == 'production' or 'RENDER' in os.environ

    if is_production:
        # En producción, usa gunicorn (configurado vía Procfile)
        # y no actives debug mode.
        # socketio.run() con gunicorn se ejecuta a través del Procfile,
        # pero para desarrollo directo sin Procfile, puedes usar esto:
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
    else:
        # En desarrollo, puedes usar el servidor de desarrollo de Flask
        socketio.run(app, host='0.0.0.0', port=port, debug=True, allow_unsafe_werkzeug=True)
