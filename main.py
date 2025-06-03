from flask import Flask, request, jsonify, session
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import logging, datetime, time, threading, os, requests, numpy as np
from iqoptionapi.stable_api import IQ_Option
from flask_session import Session
import json

import eventlet
eventlet.monkey_patch()

app = Flask(__name__)
app.secret_key = 'super_secret_key_change_in_production'

# Configuración de sesión mejorada
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
os.makedirs('/tmp/session_data', exist_ok=True)

CORS(app, supports_credentials=True, origins=['http://localhost:3000', 'https://yourdomain.com'])
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', logger=True, engineio_logger=True)

# Configuración de logging mejorada
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variables globales
user_sessions = {}
active_bots = {}  # Para rastrear bots activos por usuario

# Configuración de Telegram
TELEGRAM_TOKEN = "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM"
TELEGRAM_CHAT_ID = "7009100334"

def send_telegram_message(message):
    """Envía mensaje a Telegram con manejo de errores mejorado"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"✅ Mensaje enviado a Telegram: {message[:50]}...")
        else:
            logger.error(f"❌ Error Telegram: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error de conexión con Telegram: {e}")
    except Exception as e:
        logger.error(f"❌ Error inesperado en Telegram: {e}")

@app.route('/health', methods=['GET'])
def health_check():
    """Endpoint de salud para verificar que el servidor funciona"""
    return jsonify({"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}), 200

@app.route('/login', methods=['POST'])
def login():
    """Endpoint de login mejorado con mejor manejo de errores"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "Datos JSON inválidos"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña son requeridos"}), 400
        
        logger.info(f"🔐 Iniciando sesión para: {email}")
        
        # Cerrar sesión anterior si existe
        if email in user_sessions:
            try:
                user_sessions[email].close_websocket()
            except:
                pass
            del user_sessions[email]
        
        # Crear nueva conexión
        iq = IQ_Option(email, password)
        iq.set_max_reconnect(5)
        
        # Intentar conectar
        connect_result = iq.connect()
        
        if not connect_result:
            logger.warning(f"❌ Falló la conexión inicial para {email}")
            return jsonify({"success": False, "message": "Error de conexión inicial"}), 401
        
        # Verificar conexión
        if not iq.check_connect():
            logger.warning(f"❌ Credenciales incorrectas para {email}")
            return jsonify({"success": False, "message": "Credenciales incorrectas"}), 401
        
        logger.info(f"✅ Conectado exitosamente: {email}")
        
        # Obtener información del perfil
        profile = iq.get_profile()
        if not profile:
            logger.warning(f"⚠️ No se pudo obtener el perfil para {email}")
            profile = {"name": "Usuario", "email": email}
        
        # Obtener balance
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        # Guardar sesión
        user_sessions[email] = iq
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
        logger.error(f"❌ Error en login: {str(e)}")
        return jsonify({"success": False, "message": f"Error interno: {str(e)}"}), 500

@app.route('/logout', methods=['POST'])
def logout():
    """Endpoint para cerrar sesión"""
    try:
        if 'user_email' in session:
            email = session['user_email']
            
            # Detener bot si está activo
            if email in active_bots:
                active_bots[email] = False
            
            # Cerrar conexión IQ Option
            if email in user_sessions:
                try:
                    user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
            
            # Limpiar sesión
            session.clear()
            
            send_telegram_message(f"👋 *LOGOUT*\n📧 Usuario: `{email}`\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
            logger.info(f"👋 Logout exitoso para: {email}")
            
        return jsonify({"success": True, "message": "Sesión cerrada correctamente"}), 200
        
    except Exception as e:
        logger.error(f"❌ Error en logout: {str(e)}")
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

@app.route('/symbols', methods=['GET'])
def get_symbols():
    """Obtener símbolos disponibles"""
    symbols = [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF",
        "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC"
    ]
    return jsonify({"symbols": symbols}), 200

@app.route('/balance', methods=['GET'])
def get_balance():
    """Obtener balance actual del usuario"""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403
        
        email = session['user_email']
        iq = user_sessions.get(email)
        
        if not iq or not iq.check_connect():
            return jsonify({"error": "Sesión expirada"}), 403
        
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        return jsonify({
            "balance": balance,
            "account_type": account_type
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo balance: {str(e)}")
        return jsonify({"error": "Error interno"}), 500

def calculate_indicators(candles):
    """Calcular indicadores técnicos mejorados"""
    try:
        if len(candles) < 30:
            logger.warning("⚠️ Insuficientes velas para cálculos precisos")
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        
        # RSI mejorado
        delta = np.diff(closes)
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        
        # Promedio exponencial para RSI
        avg_gain = np.mean(gain[-14:]) if len(gain) >= 14 else np.mean(gain)
        avg_loss = np.mean(loss[-14:]) if len(loss) >= 14 else np.mean(loss)
        
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        rsi = 100 - (100 / (1 + rs))
        
        # MACD mejorado
        ema12 = np.mean(closes[-12:]) if len(closes) >= 12 else closes[-1]
        ema26 = np.mean(closes[-26:]) if len(closes) >= 26 else closes[-1]
        macd = ema12 - ema26
        signal = np.mean(closes[-9:]) if len(closes) >= 9 else closes[-1]
        
        # Stochastic mejorado
        period = min(14, len(highs))
        lowest_low = np.min(lows[-period:])
        highest_high = np.max(highs[-period:])
        
        if highest_high != lowest_low:
            stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
        else:
            stoch_k = 50
            
        stoch_d = np.mean([stoch_k] * 3)
        
        return {
            "rsi": round(rsi, 2),
            "macd": round(macd, 4),
            "signal": round(signal, 4),
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "price": round(closes[-1], 5)
        }
        
    except Exception as e:
        logger.error(f"❌ Error calculando indicadores: {e}")
        return None

def get_signal(indicators):
    """Generar señal de trading mejorada"""
    if not indicators:
        return None
    
    rsi = indicators['rsi']
    macd = indicators['macd']
    signal = indicators['signal']
    stoch_k = indicators['stoch_k']
    
    # Condiciones para CALL (compra)
    call_conditions = [
        rsi < 30,  # RSI sobrevendido
        macd > signal and macd > 0,  # MACD alcista
        stoch_k < 20  # Stochastic sobrevendido
    ]
    
    # Condiciones para PUT (venta)
    put_conditions = [
        rsi > 70,  # RSI sobrecomprado
        macd < signal and macd < 0,  # MACD bajista
        stoch_k > 80  # Stochastic sobrecomprado
    ]
    
    call_score = sum(call_conditions)
    put_score = sum(put_conditions)
    
    if call_score >= 2:
        return 'call'
    elif put_score >= 2:
        return 'put'
    else:
        return None

@app.route('/start_bot', methods=['POST'])
def start_bot():
    """Iniciar bot de trading mejorado"""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']
        iq = user_sessions.get(email)

        if not iq or not iq.check_connect():
            return jsonify({"error": "Sesión expirada o inválida"}), 403

        data = request.get_json()
        if not data:
            return jsonify({"error": "Datos JSON inválidos"}), 400

        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account_type = data.get('account_type', 'PRACTICE')

        # Validaciones
        if amount <= 0:
            return jsonify({"error": "El monto debe ser mayor que 0"}), 400

        if amount > 10000:
            return jsonify({"error": "Monto máximo: $10,000"}), 400

        balance = iq.get_balance()
        if amount > balance:
            return jsonify({"error": f"Fondos insuficientes. Balance: ${balance:.2f}"}), 400

        # Verificar si ya hay un bot activo
        if email in active_bots and active_bots[email]:
            return jsonify({"error": "Ya hay un bot activo. Deténgalo primero."}), 400

        # Cambiar tipo de cuenta
        iq.change_balance(account_type.upper())
        
        # Marcar bot como activo
        active_bots[email] = True
        
        # Enviar notificación de inicio
        start_message = f"""🚀 *BOT INICIADO*

👤 *Usuario:* `{email}`
📈 *Símbolo:* {symbol}
💰 *Monto inicial:* ${amount:.2f}
🎯 *Martingalas:* {martingalas}
🏦 *Cuenta:* {account_type}
⏰ *Inicio:* {datetime.datetime.now().strftime('%H:%M:%S')}

🤖 *Bot ejecutándose...*"""
        
        send_telegram_message(start_message)

        # Iniciar bot en hilo separado
        socketio.start_background_task(run_bot, iq, symbol, amount, martingalas, email)

        return jsonify({"message": "Bot iniciado correctamente"}), 200
        
    except ValueError as e:
        return jsonify({"error": f"Valor inválido: {str(e)}"}), 400
    except Exception as e:
        logger.error(f"❌ Error iniciando bot: {str(e)}")
        return jsonify({"error": "Error interno del servidor"}), 500

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    """Detener bot activo"""
    try:
        if 'user_email' not in session:
            return jsonify({"error": "Usuario no autenticado"}), 403

        email = session['user_email']
        
        if email in active_bots:
            active_bots[email] = False
            send_telegram_message(f"🛑 *BOT DETENIDO*\n👤 Usuario: `{email}`\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
            return jsonify({"message": "Bot detenido correctamente"}), 200
        else:
            return jsonify({"error": "No hay bot activo"}), 400
            
    except Exception as e:
        logger.error(f"❌ Error deteniendo bot: {str(e)}")
        return jsonify({"error": "Error interno"}), 500

def run_bot(iq, symbol, initial_amount, martingalas, email):
    """Función principal del bot mejorada"""
    try:
        current_amount = initial_amount
        original_martingalas = martingalas
        consecutive_losses = 0
        total_trades = 0
        max_loss_limit = initial_amount * (2 ** (martingalas + 1))
        
        logger.info(f"🤖 Bot iniciado para {email} - {symbol}")
        
        while active_bots.get(email, False):
            try:
                # Verificar conexión
                if not iq.check_connect():
                    send_telegram_message(f"❌ *CONEXIÓN PERDIDA*\n👤 Usuario: `{email}`\n🔄 Intentando reconectar...")
                    if not iq.connect():
                        break
                
                # Obtener velas
                end_time = time.time()
                candles = iq.get_candles(symbol, 60, 100, end_time)
                
                if not candles or len(candles) < 30:
                    logger.warning(f"⚠️ Datos insuficientes para {symbol}")
                    time.sleep(30)
                    continue
                
                # Calcular indicadores
                indicators = calculate_indicators(candles)
                if not indicators:
                    time.sleep(30)
                    continue
                
                # Generar señal
                direction = get_signal(indicators)
                
                # Enviar análisis a Telegram
                analysis_message = f"""📊 *ANÁLISIS TÉCNICO - {symbol}*

💹 *Precio actual:* {indicators['price']:.5f}
📈 *RSI:* {indicators['rsi']:.1f}
📊 *MACD:* {indicators['macd']:.4f}
📉 *Signal:* {indicators['signal']:.4f}
🎯 *Stoch K:* {indicators['stoch_k']:.1f}

{"🟢 *SEÑAL: " + direction.upper() + "*" if direction else "🟡 *Sin señal clara*"}"""
                
                send_telegram_message(analysis_message)
                
                if direction and active_bots.get(email, False):
                    # Verificar balance
                    balance = iq.get_balance()
                    if current_amount > balance:
                        stop_message = f"""🚫 *BOT DETENIDO - FONDOS INSUFICIENTES*

💰 *Monto requerido:* ${current_amount:.2f}
💳 *Balance actual:* ${balance:.2f}
📊 *Total operaciones:* {total_trades}"""
                        send_telegram_message(stop_message)
                        break
                    
                    # Ejecutar operación
                    result = execute_trade(iq, symbol, current_amount, direction, email)
                    total_trades += 1
                    
                    if result['result'] == 'WIN':
                        # Reset en caso de ganancia
                        current_amount = initial_amount
                        consecutive_losses = 0
                        martingalas = original_martingalas
                        
                        win_message = f"""✅ *OPERACIÓN GANADA*

📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto:* ${result['amount']:.2f}
💵 *Ganancia:* ${result['profit']:.2f}
📊 *Total operaciones:* {total_trades}

🎉 *¡Excelente trabajo!*"""
                        send_telegram_message(win_message)
                        
                    elif result['result'] == 'LOSS':
                        consecutive_losses += 1
                        
                        loss_message = f"""❌ *OPERACIÓN PERDIDA*

📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto:* ${result['amount']:.2f}
💸 *Pérdida:* ${abs(result['profit']):.2f}
🔄 *Pérdidas consecutivas:* {consecutive_losses}
📊 *Total operaciones:* {total_trades}"""
                        
                        if martingalas > 0:
                            current_amount *= 2
                            martingalas -= 1
                            loss_message += f"\n\n🎲 *MARTINGALA ACTIVADA*\n💰 *Nuevo monto:* ${current_amount:.2f}\n🎯 *Martingalas restantes:* {martingalas}"
                        else:
                            loss_message += "\n\n🚫 *MARTINGALAS AGOTADAS*"
                            send_telegram_message(loss_message)
                            break
                        
                        send_telegram_message(loss_message)
                        
                        # Verificar límite de pérdida
                        if current_amount > max_loss_limit:
                            limit_message = f"""🛑 *LÍMITE DE PÉRDIDA ALCANZADO*

💸 *Monto actual:* ${current_amount:.2f}
🚫 *Límite máximo:* ${max_loss_limit:.2f}
📊 *Total operaciones:* {total_trades}

🛡️ *Bot detenido por seguridad*"""
                            send_telegram_message(limit_message)
                            break
                    
                    # Pausa entre operaciones
                    time.sleep(90)
                else:
                    # Sin señal, esperar
                    time.sleep(60)
                    
            except Exception as e:
                logger.error(f"❌ Error en ciclo del bot: {str(e)}")
                send_telegram_message(f"⚠️ *ERROR EN BOT*\n👤 Usuario: `{email}`\n❌ Error: {str(e)}")
                time.sleep(30)
        
        # Bot finalizado
        active_bots[email] = False
        final_message = f"""🏁 *BOT FINALIZADO*

👤 *Usuario:* `{email}`
📈 *Símbolo:* {symbol}
📊 *Total operaciones:* {total_trades}
⏰ *Finalizado:* {datetime.datetime.now().strftime('%H:%M:%S')}

🤖 *Gracias por usar el bot*"""
        
        send_telegram_message(final_message)
        
    except Exception as e:
        logger.error(f"❌ Error crítico en run_bot: {str(e)}")
        active_bots[email] = False
        send_telegram_message(f"💀 *ERROR CRÍTICO*\n👤 Usuario: `{email}`\n❌ {str(e)}")

def execute_trade(iq, symbol, amount, direction, email):
    """Ejecutar operación con manejo de errores mejorado"""
    try:
        logger.info(f"🎯 Ejecutando {direction.upper()} en {symbol} por ${amount:.2f}")
        
        # Abrir posición
        status, order_id = iq.buy(amount, symbol, direction, 1)
        
        if not status or not order_id:
            error_msg = f"❌ *ERROR AL ABRIR POSICIÓN*\n👤 Usuario: `{email}`\n📈 Símbolo: {symbol}\n💰 Monto: ${amount:.2f}"
            send_telegram_message(error_msg)
            return {"symbol": symbol, "amount": amount, "result": "ERROR", "profit": 0}
        
        # Notificar apertura
        open_message = f"""🎯 *POSICIÓN ABIERTA*

📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto:* ${amount:.2f}
🆔 *ID:* {order_id}
⏰ *Hora:* {datetime.datetime.now().strftime('%H:%M:%S')}

⏳ *Esperando resultado...*"""
        
        send_telegram_message(open_message)
        
        # Esperar resultado (1 minuto)
        time.sleep(65)
        
        # Verificar resultado
        profit = iq.check_win(order_id)
        result = 'WIN' if profit > 0 else 'LOSS'
        
        # Notificar cierre
        close_message = f"""🏁 *POSICIÓN CERRADA*

📈 *Símbolo:* {symbol}
🎯 *Dirección:* {direction.upper()}
💰 *Monto:* ${amount:.2f}
🆔 *ID:* {order_id}
{"✅ *Resultado:* GANADA" if result == 'WIN' else "❌ *Resultado:* PERDIDA"}
💵 *P&L:* {"+" if profit > 0 else ""}${profit:.2f}
⏰ *Cierre:* {datetime.datetime.now().strftime('%H:%M:%S')}"""
        
        send_telegram_message(close_message)
        
        return {
            "symbol": symbol,
            "amount": amount,
            "result": result,
            "profit": profit,
            "order_id": order_id
        }
        
    except Exception as e:
        logger.error(f"❌ Error en execute_trade: {str(e)}")
        error_msg = f"❌ *ERROR EN EJECUCIÓN*\n👤 Usuario: `{email}`\n📈 Símbolo: {symbol}\n❌ Error: {str(e)}"
        send_telegram_message(error_msg)
        return {"symbol": symbol, "amount": amount, "result": "ERROR", "profit": 0}

@socketio.on('connect')
def handle_connect():
    """Manejar conexión WebSocket"""
    logger.info(f"🔌 Cliente conectado: {request.sid}")
    emit('status', {'message': 'Conectado al servidor de trading'})

@socketio.on('disconnect')
def handle_disconnect():
    """Manejar desconexión WebSocket"""
    logger.info(f"🔌 Cliente desconectado: {request.sid}")

# Ruta de prueba
@app.route('/test', methods=['GET'])
def test():
    """Endpoint de prueba"""
    return jsonify({
        "status": "OK",
        "message": "Servidor funcionando correctamente",
        "timestamp": datetime.datetime.now().isoformat(),
        "active_sessions": len(user_sessions),
        "active_bots": len([k for k, v in active_bots.items() if v])
    }), 200

if __name__ == '__main__':
    logger.info("🚀 Iniciando servidor de trading bot...")
    send_telegram_message("🚀 *SERVIDOR INICIADO*\n⏰ " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
