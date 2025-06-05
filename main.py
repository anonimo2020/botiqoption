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
CORS(app, origins=["https://iqoptionbot.ct.ws"])

# Configuración de SECRET_KEY desde variables de entorno
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    # Esto solo debería ocurrir en desarrollo si no se establece la variable
    # En producción, Render la forzará a estar presente si la configuras
    app.secret_key = 'super_secret_key_dev_fallback_please_change'
    logging.warning("⚠️ FLASK_SECRET_KEY no está configurada como variable de entorno. ¡CÁMBIALA EN PRODUCCIÓN!")

# Configuración de sesión
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_FILE_DIR'] = '/tmp/session_data'
app.config['SESSION_COOKIE_NAME'] = 'trading_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
Session(app)

# Crear directorio de sesiones si no existe
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'https://iqoptionbot.ct.ws'])

# Inicialización de SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', logger=True, engineio_logger=True)

# --- Configuración de Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Variables Globales ---
user_sessions = {}
active_bots = {}

# --- Configuración de Telegram (desde variables de entorno) ---
TELEGRAM_BOT_TOKEN = ("7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = ("7009100334")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ ERROR: TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no están configuradas como variables de entorno.")

def send_telegram_message(message):
    """Envía mensaje a Telegram con manejo de errores mejorado"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ No se puede enviar mensaje a Telegram: Token o Chat ID no configurados.")
        return

    url = f"https://www.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    logger.info(f"🌐 Preparing Telegram API request to URL: '{url}'")
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }

    try:
        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()
        logger.info(f"✅ Mensaje enviado a Telegram: {message[:50]}...")
    except requests.exceptions.Timeout:
        logger.error("❌ Error de conexión con Telegram: Tiempo de espera agotado.")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de conexión o HTTP con Telegram: {e} - Respuesta: {response.text if 'response' in locals() else 'N/A'}")
    except Exception as e:
        logger.error(f"❌ Error inesperado al enviar a Telegram: {e}")

# --- Endpoints HTTP REST ---

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud para verificar que el servidor funciona"""
    return jsonify({"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}), 200

@app.route('/login', methods=['POST'])
def login():
    """Endpoint de login mejorado con mejor manejo de errores y validación."""
    email = "NotSet" # Default para logging en caso de error temprano
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
                logger.info(f"Attempting to close previous IQ Option session for {email}.")
                user_sessions[email].close_websocket()
                logger.info(f"Sesión IQ Option previa cerrada para {email}.")
            except Exception as e_close:
                logger.warning(f"Error al intentar cerrar websocket previo para {email}: {e_close}")
            if email in user_sessions: # Verifica si la eliminación es necesaria
                 del user_sessions[email]

        # Crear nueva conexión a IQ Option
        iq = IQ_Option(email, password)

        logger.info(f"Attempting to connect to IQ Option for {email}...")
        connect_result = None
        try:
            connect_result = iq.connect()
            logger.info(f"IQ Option connect() call finished for {email}. Result: {connect_result}")
        except Exception as e_connect:
            logger.error(f"❌ Exception during IQ Option connect() for {email}: {e_connect}", exc_info=True)
            return jsonify({"success": False, "message": f"Error during IQ Option connection attempt: {str(e_connect)}"}), 500

        if not connect_result:
            logger.warning(f"❌ Falló la conexión inicial a IQ Option para {email}.")
            return jsonify({"success": False, "message": "Error de conexión inicial con IQ Option. Verifica tu conexión a internet o el estado del servicio."}), 401

        # Verificar credenciales
        logger.info(f"Verificando estado de conexión a IQ Option para {email}...")
        if not iq.check_connect():
            logger.warning(f"❌ Credenciales incorrectas o fallo en check_connect para {email}.")
            return jsonify({"success": False, "message": "Credenciales incorrectas de IQ Option o fallo al verificar conexión."}), 401

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
        session.permanent = True

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
    email = session.get('user_email', 'Unknown user') # Para logging si no hay user_email en session
    try:
        if 'user_email' not in session:
            return jsonify({"success": False, "message": "No hay sesión activa para cerrar"}), 400

        email = session['user_email']

        if email in active_bots:
            active_bots[email] = False
            logger.info(f"Señal de detención enviada al bot de {email}.")

        if email in user_sessions:
            try:
                user_sessions[email].close_websocket()
                logger.info(f"Conexión IQ Option cerrada para {email}.")
            except Exception as e:
                logger.warning(f"Error al cerrar websocket IQ Option para {email}: {e}")
            del user_sessions[email]

        session.clear()
        send_telegram_message(f"👋 *LOGOUT*\n📧 Usuario: `{email}`\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
        logger.info(f"👋 Logout exitoso para: {email}")
        return jsonify({"success": True, "message": "Sesión cerrada correctamente"}), 200

    except Exception as e:
        logger.error(f"❌ Error en logout para {email}: {str(e)}", exc_info=True)
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

@app.route('/symbols', methods=['GET'])
def get_symbols():
    """Obtener símbolos disponibles (hardcodeados por simplicidad)."""
    symbols = [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
        "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC"
    ]
    return jsonify({"symbols": symbols}), 200

@app.route('/balance', methods=['GET'])
def get_balance_route(): # Renamed to avoid conflict with get_balance from iqoptionapi
    """Obtener balance actual del usuario autenticado."""
    email = session.get('user_email', 'Unknown user')
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']
        iq = user_sessions.get(email)

        if not iq or not iq.check_connect():
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
    email = session.get('user_email', 'Unknown user')
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']
        iq = user_sessions.get(email)

        if not iq or not iq.check_connect():
            logger.warning(f"Conexión IQ Option perdida para {email} al iniciar bot. Intentando reconectar...")
            if iq and iq.connect():
                logger.info(f"Reconectado exitosamente a IQ Option para {email}.")
            else:
                return jsonify({"error": "Sesión IQ Option expirada o inválida. Por favor, inicia sesión nuevamente."}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Datos JSON inválidos"}), 400

        symbol = data.get('symbol', 'EURUSD').upper()
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE').upper()

        if amount <= 0:
            return jsonify({"error": "El monto debe ser un número positivo."}), 400
        if amount > 10000:
            return jsonify({"error": "Monto máximo de operación permitido es $10,000."}), 400
        if martingalas < 0:
            return jsonify({"error": "El número de martingalas no puede ser negativo."}), 400

        if active_bots.get(email, False):
            return jsonify({"error": "Ya hay un bot activo para esta sesión. Deténgalo primero."}), 400

        iq.change_balance(account_type)
        current_iq_balance_mode = iq.get_balance_mode()
        if current_iq_balance_mode != account_type:
            logger.warning(f"⚠️ No se pudo cambiar el balance a {account_type} para {email}. Actual: {current_iq_balance_mode}")
            return jsonify({"error": f"No se pudo cambiar el tipo de cuenta a {account_type}. Intenta de nuevo."}), 400

        balance = iq.get_balance()
        if amount > balance:
            return jsonify({"error": f"Fondos insuficientes en cuenta {account_type}. Balance: ${balance:.2f}."}), 400

        active_bots[email] = True
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
        socketio.start_background_task(run_bot, iq, symbol, amount, martingalas, email, session.sid)
        return jsonify({"message": "Bot iniciado correctamente. Consulta el estado en Telegram o en la consola."}), 200

    except ValueError as e:
        logger.error(f"❌ Error de validación al iniciar bot: {str(e)}")
        return jsonify({"error": f"Valor inválido proporcionado: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"❌ Error inesperado al iniciar bot para {email}: {str(e)}", exc_info=True)
        return jsonify({"error": "Error interno del servidor al iniciar el bot."}), 500

@app.route('/stop_bot', methods=['POST'])
def stop_bot_route(): # Renamed to avoid potential conflicts if 'stop_bot' is used elsewhere
    """Detener bot activo."""
    email = session.get('user_email', 'Unknown user')
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']
        if email in active_bots and active_bots[email]:
            active_bots[email] = False
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
        if len(candles) < 30:
            logger.warning("⚠️ Insuficientes velas para cálculos precisos de indicadores.")
            return None

        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])

        if len(closes) < 15:
            logger.warning("⚠️ Insuficientes velas para calcular RSI (requiere al menos 15).")
            return None

        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)

        avg_gain = np.mean(gain[-14:])
        avg_loss = np.mean(loss[-14:])
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi = 100 - (100 / (1 + rs))

        if len(closes) < 27:
            logger.warning("⚠️ Insuficientes velas para calcular MACD (requiere al menos 27).")
            return None

        def calculate_ema(data, period):
            ema = [sum(data[:period]) / period]
            k = 2 / (period + 1)
            for i in range(period, len(data)):
                ema.append((data[i] - ema[-1]) * k + ema[-1])
            return ema[-1]

        ema12 = calculate_ema(closes, 12)
        ema26 = calculate_ema(closes, 26)
        macd = ema12 - ema26
        signal = calculate_ema(closes, 9) # Simplification: EMA of price, not MACD line

        period_stoch = min(14, len(highs))
        if period_stoch < 1:
            logger.warning("⚠️ Insuficientes velas para calcular Stochastic.")
            return None

        lowest_low = np.min(lows[-period_stoch:])
        highest_high = np.max(highs[-period_stoch:])
        stoch_k = 50
        if highest_high != lowest_low:
            stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
        
        stoch_d = stoch_k # Simplification

        return {
            "rsi": round(rsi, 2), "macd": round(macd, 4), "signal": round(signal, 4),
            "stoch_k": round(stoch_k, 2), "stoch_d": round(stoch_d, 2),
            "price": round(closes[-1], 5)
        }
    except Exception as e:
        logger.error(f"❌ Error calculando indicadores: {e}", exc_info=True)
        return None

def get_signal(indicators):
    """Generar señal de trading basada en indicadores."""
    if not indicators: return None
    rsi = indicators.get('rsi')
    macd = indicators.get('macd')
    signal_line = indicators.get('signal')
    stoch_k = indicators.get('stoch_k')

    if any(x is None for x in [rsi, macd, signal_line, stoch_k]):
        logger.warning("No se pudo generar señal debido a indicadores faltantes.")
        return None

    call_conditions = [rsi < 30, macd > signal_line, macd > 0, stoch_k < 20]
    put_conditions = [rsi > 70, macd < signal_line, macd < 0, stoch_k > 80]
    call_score = sum(call_conditions)
    put_score = sum(put_conditions)

    if call_score >= 3: return 'call'
    if put_score >= 3: return 'put'
    return None

def run_bot(iq_api_instance, symbol, initial_amount, martingalas_limit, email, sid):
    """Función principal del bot de trading que se ejecuta en un hilo separado."""
    current_amount = initial_amount
    consecutive_losses = 0
    total_trades = 0
    logger.info(f"🤖 Bot iniciado para {email} - {symbol} (SID: {sid})")
    socketio.emit('bot_status', {'message': f"Bot iniciado para {symbol}.", 'status': 'running'}, room=sid)

    while active_bots.get(email, False):
        try:
            if not iq_api_instance.check_connect():
                logger.warning(f"Conexión IQ Option perdida para {email}. Intentando reconectar...")
                send_telegram_message(f"❌ *CONEXIÓN IQOPTION PERDIDA*\n👤 Usuario: `{email}`\n🔄 Intentando reconectar...")
                socketio.emit('bot_status', {'message': "Conexión IQ Option perdida, intentando reconectar...", 'status': 'reconnecting'}, room=sid)
                if not iq_api_instance.connect():
                    logger.error(f"Fallo al reconectar a IQ Option para {email}. Deteniendo bot.")
                    send_telegram_message(f"💀 *FALLO CRÍTICO: RECONEXIÓN IQOPTION FALLIDA*\n👤 Usuario: `{email}`\n🚫 Bot detenido.")
                    socketio.emit('bot_status', {'message': "Fallo al reconectar con IQ Option. Bot detenido.", 'status': 'error'}, room=sid)
                    active_bots[email] = False
                    break
                logger.info(f"IQ Option reconectado para {email}.")
                socketio.emit('bot_status', {'message': "Reconexión exitosa con IQ Option.", 'status': 'running'}, room=sid)

            end_time = time.time()
            candles = iq_api_instance.get_candles(symbol, 60, 100, end_time)
            if not candles or len(candles) < 30:
                logger.warning(f"⚠️ Datos de velas insuficientes para {symbol}. Reintentando en 30s.")
                socketio.emit('bot_status', {'message': f"Datos de velas insuficientes para {symbol}. Esperando...", 'status': 'waiting'}, room=sid)
                time.sleep(30)
                continue

            indicators = calculate_indicators(candles)
            if not indicators:
                logger.warning(f"⚠️ No se pudieron calcular indicadores para {symbol}. Reintentando en 30s.")
                socketio.emit('bot_status', {'message': f"Error al calcular indicadores para {symbol}. Esperando...", 'status': 'waiting'}, room=sid)
                time.sleep(30)
                continue

            direction = get_signal(indicators)
            analysis_message_telegram = f"""📊 *ANÁLISIS TÉCNICO - {symbol}*
💹 *Precio actual:* {indicators['price']:.5f}
📈 *RSI:* {indicators['rsi']:.1f}
📊 *MACD:* {indicators['macd']:.4f}
📉 *Signal:* {indicators['signal']:.4f}
🎯 *Stoch K:* {indicators['stoch_k']:.1f}
{"🟢 *SEÑAL: " + direction.upper() + "*" if direction else "🟡 *Sin señal clara*"}"""
            socketio.emit('bot_analysis', {
                'symbol': symbol, 'price': indicators['price'], 'rsi': indicators['rsi'],
                'macd': indicators['macd'], 'stoch_k': indicators['stoch_k'], 'signal': direction
            }, room=sid)
            send_telegram_message(analysis_message_telegram)

            if direction and active_bots.get(email, False):
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
                    break

                logger.info(f"Iniciando operación: {direction.upper()} en {symbol} con ${current_amount:.2f}")
                socketio.emit('bot_status', {'message': f"Ejecutando operación {direction.upper()} por ${current_amount:.2f}...", 'status': 'trading'}, room=sid)
                trade_result = execute_trade(iq_api_instance, symbol, current_amount, direction, email, sid)
                total_trades += 1

                if trade_result['result'] == 'WIN':
                    current_amount = initial_amount
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
                        current_amount *= 2
                        loss_message += f"\n\n🎲 *MARTINGALA ACTIVADA*\n💰 *Nuevo monto:* ${current_amount:.2f}\n🎯 *Martingalas restantes:* {martingalas_limit - consecutive_losses}"
                        socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'LOSS', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': 'Operación perdida. Aplicando Martingala.', 'martingalas_left': martingalas_limit - consecutive_losses, 'next_amount': current_amount}, room=sid)
                    else:
                        loss_message += "\n\n🚫 *MARTINGALAS AGOTADAS*"
                        socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'LOSS', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': 'Operación perdida. Martingalas agotadas. Bot detenido.', 'martingalas_left': 0}, room=sid)
                        active_bots[email] = False
                        break
                    send_telegram_message(loss_message)
                elif trade_result['result'] == 'DRAW':
                    logger.info(f"⚪ Operación EMPATE en {symbol}.")
                    send_telegram_message(f"⚪ *OPERACIÓN EMPATE*\n📈 *Símbolo:* {symbol}\n💰 *Monto:* ${trade_result['amount']:.2f}\n👤 *Usuario:* `{email}`\n📊 *Total operaciones:* {total_trades}")
                    socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'DRAW', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': 'Operación fue un empate.'}, room=sid)
                    current_amount = initial_amount
                else: # ERROR
                    logger.error(f"🔴 Error al ejecutar operación para {email}.")
                    send_telegram_message(f"🔴 *ERROR EN OPERACIÓN*\n👤 Usuario: `{email}`\n📈 Símbolo: {symbol}\n❌ Detalles: {trade_result.get('message', 'Desconocido')}")
                    socketio.emit('trade_result', {'symbol': symbol, 'amount': trade_result['amount'], 'result': 'ERROR', 'profit': trade_result['profit'], 'total_trades': total_trades, 'message': trade_result.get('message', 'Error desconocido en operación.')}, room=sid)

                logger.info(f"Pausando {90} segundos antes de la próxima operación...")
                socketio.emit('bot_status', {'message': "Esperando la próxima señal...", 'status': 'waiting_signal'}, room=sid)
                time.sleep(90)
            else:
                if not active_bots.get(email, False): break
                logger.info(f"Sin señal clara para {symbol}. Esperando {60} segundos.")
                socketio.emit('bot_status', {'message': f"Sin señal clara para {symbol}. Esperando...", 'status': 'waiting_signal'}, room=sid)
                time.sleep(60)
        except Exception as e:
            logger.error(f"❌ Error en el ciclo principal del bot para {email}: {str(e)}", exc_info=True)
            send_telegram_message(f"⚠️ *ERROR EN BOT*\n👤 Usuario: `{email}`\n❌ Error: {str(e)}")
            socketio.emit('bot_status', {'message': f"Un error inesperado ocurrió: {str(e)}. El bot podría detenerse.", 'status': 'error'}, room=sid)
            time.sleep(30)

    active_bots[email] = False
    final_message = f"""🏁 *BOT FINALIZADO*
👤 *Usuario:* `{email}`
📈 *Símbolo:* {symbol}
📊 *Total operaciones:* {total_trades}
⏰ *Finalizado:* {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🤖 *Gracias por usar el bot*"""
    send_telegram_message(final_message)
    socketio.emit('bot_status', {'message': "Bot detenido.", 'status': 'stopped', 'total_trades': total_trades}, room=sid)
    logger.info(f"🏁 Bot finalizado para {email}.")

def execute_trade(iq_api_instance, symbol, amount, direction, email, sid):
    """Ejecuta una operación en IQ Option y espera el resultado."""
    try:
        logger.info(f"🎯 Ejecutando {direction.upper()} en {symbol} por ${amount:.2f}")
        status, order_id = iq_api_instance.buy(amount, symbol, direction, 1)

        if not status or not order_id:
            error_msg = f"❌ *ERROR AL ABRIR POSICIÓN*\n👤 Usuario: `{email}`\n📈 Símbolo: {symbol}\n💰 Monto: ${amount:.2f}\n⚠️ Detalles: {status}"
            send_telegram_message(error_msg)
            socketio.emit('trade_result', {'symbol': symbol, 'amount': amount, 'result': 'ERROR', 'profit': 0, 'message': 'Error al abrir posición.'}, room=sid)
            return {"symbol": symbol, "amount": amount, "result": "ERROR", "profit": 0, "message": str(status)}

        open_message = f"""🎯 *POSICIÓN ABIERTA*
📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto:* ${amount:.2f}
🆔 *ID:* {order_id}
⏰ *Hora:* {datetime.datetime.now().strftime('%H:%M:%S')}
⏳ *Esperando resultado...*"""
        send_telegram_message(open_message)
        socketio.emit('bot_status', {'message': f"Posición abierta: {direction.upper()} {symbol} ${amount:.2f}", 'status': 'open_position', 'order_id': order_id}, room=sid)
        time.sleep(65)

        profit = iq_api_instance.check_win(order_id)
        result = 'PENDING'
        if profit is None:
            result = 'UNKNOWN'
            logger.warning(f"No se pudo verificar el resultado de la operación {order_id}.")
            close_message = f"""❓ *RESULTADO DESCONOCIDO*
📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto:* ${amount:.2f}
🆔 *ID:* {order_id}
⏰ *Cierre (aprox):* {datetime.datetime.now().strftime('%H:%M:%S')}
⚠️ *No se pudo obtener el resultado. Verifica IQ Option.*"""
            send_telegram_message(close_message)
            socketio.emit('bot_status', {'message': f"Resultado de operación {order_id} desconocido.", 'status': 'unknown_result'}, room=sid)
            return {"symbol": symbol, "amount": amount, "result": result, "profit": 0}
        elif profit > 0: result = 'WIN'
        elif profit < 0: result = 'LOSS'
        else: result = 'DRAW'

        close_message = f"""🏁 *POSICIÓN CERRADA*
📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto invertido:* ${amount:.2f}
🆔 *ID:* {order_id}
{"✅ *Resultado:* GANADA" if result == 'WIN' else ("❌ *Resultado:* PERDIDA" if result == 'LOSS' else "⚪ *Resultado:* EMPATE")}
💵 *P&L:* {"+" if profit > 0 else ""}${profit:.2f}
⏰ *Cierre:* {datetime.datetime.now().strftime('%H:%M:%S')}"""
        send_telegram_message(close_message)
        return {"symbol": symbol, "amount": amount, "result": result, "profit": profit, "order_id": order_id}

    except Exception as e:
        logger.error(f"❌ Error en execute_trade para {email}: {str(e)}", exc_info=True)
        error_msg_telegram = f"❌ *ERROR EN EJECUCIÓN*\n👤 Usuario: `{email}`\n📈 Símbolo: {symbol}\n💰 Monto: ${amount:.2f}\n❌ Error: {str(e)}"
        send_telegram_message(error_msg_telegram)
        socketio.emit('bot_status', {'message': f"Error crítico al ejecutar operación: {str(e)}. Bot podría detenerse.", 'status': 'trade_error'}, room=sid)
        return {"symbol": symbol, "amount": amount, "result": "ERROR", "profit": 0, "message": str(e)}

# --- Manejo de Eventos WebSocket (SocketIO) ---
@socketio.on('connect')
def handle_connect():
    """Manejar conexión WebSocket"""
    logger.info(f"🔌 Cliente SocketIO conectado: {request.sid}")
    emit('status', {'message': 'Conectado al servidor de trading bot.', 'sid': request.sid})

@socketio.on('disconnect')
def handle_disconnect():
    """Manejar desconexión WebSocket"""
    logger.info(f"🔌 Cliente SocketIO desconectado: {request.sid}")

# --- Ruta de prueba general ---
@app.route('/test', methods=['GET'])
def test():
    """Endpoint de prueba para verificar el estado general del servidor."""
    return jsonify({
        "status": "OK",
        "message": "Servidor funcionando correctamente",
        "timestamp": datetime.datetime.now().isoformat(),
        "active_iq_sessions": len(user_sessions),
        "active_running_bots": len([k for k, v in active_bots.items() if v]),
        "telegram_configured": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    }), 200

# --- Inicio de la aplicación Flask y SocketIO ---
if __name__ == '__main__':
    logger.info("🚀 Iniciando servidor de trading bot...")
    send_telegram_message("🚀 *SERVIDOR DE TRADING INICIADO*\n⏰ " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    port = int(os.environ.get('PORT', 5000))
    is_production = os.environ.get('FLASK_ENV') == 'production' or 'RENDER' in os.environ

    if is_production:
        # En producción, usualmente se usa un servidor WSGI como Gunicorn.
        # El comando de ejecución se configuraría en el Procfile de Render.
        # socketio.run(app, host='0.0.0.0', port=port) # No es típico llamar a socketio.run directamente con Gunicorn
        # Gunicorn ejecutaría: gunicorn --worker-class eventlet -w 1 backend:app
        # Para desarrollo local simulando producción con eventlet directamente (sin gunicorn):
        logger.info(f"Iniciando servidor en modo producción (eventlet) en el puerto {port}")
        socketio.run(app, host='0.0.0.0', port=port, use_reloader=False) # use_reloader=False es importante para producción
    else:
        logger.info(f"Iniciando servidor en modo desarrollo (Flask dev server) en el puerto {port}")
        socketio.run(app, debug=True, host='0.0.0.0', port=port)
