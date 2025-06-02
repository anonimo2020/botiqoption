from flask import Flask, request, jsonify
import logging
import threading
import time
from datetime import datetime
import telegram

# Credenciales y configuraciones
IQ_EMAIL = "sebaselwspo@gmail.com"
IQ_PASSWORD = "Octubre2001"
TELEGRAM_BOT_TOKEN = "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM"
TELEGRAM_CHAT_ID = "7009100334"

# Importar la librería de IQ Option
try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    print("Instala iqoptionapi: pip install iqoptionapi")
    IQ_Option = None

app = Flask(__name__)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurar el bot de Telegram
bot_telegram = telegram.Bot(token=TELEGRAM_BOT_TOKEN)

class IQOptionBot:
    def __init__(self):
        self.api = None
        self.is_connected = False
        self.current_balance = 0

    def connect(self, email, password):
        """Conectar a IQ Option"""
        try:
            if not IQ_Option:
                raise Exception("iqoptionapi no está instalada")

            self.api = IQ_Option(email, password)
            check, reason = self.api.connect()

            if check:
                self.is_connected = True
                logger.info("Conectado a IQ Option exitosamente")
                self.send_telegram_message("Conectado a IQ Option exitosamente")
                return True, "Conectado exitosamente"
            else:
                error_message = f"Error de conexión: {reason}"
                logger.error(error_message)
                self.send_telegram_message(error_message)
                return False, error_message

        except Exception as e:
            error_message = f"Error en conexión: {str(e)}"
            logger.error(error_message)
            self.send_telegram_message(error_message)
            return False, error_message

    def send_telegram_message(self, message):
        """Enviar mensaje a Telegram"""
        try:
            bot_telegram.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        except Exception as e:
            logger.error(f"Error al enviar mensaje a Telegram: {str(e)}")

    def get_balance(self, account_type="PRACTICE"):
        """Obtener balance de la cuenta"""
        try:
            if not self.is_connected:
                return 0

            self.api.change_balance(account_type)
            balance = self.api.get_balance()
            self.current_balance = balance
            return balance

        except Exception as e:
            error_message = f"Error obteniendo balance: {str(e)}"
            logger.error(error_message)
            self.send_telegram_message(error_message)
            return 0

    def get_available_symbols(self):
        """Obtener símbolos disponibles"""
        try:
            if not self.is_connected:
                return []

            is_weekend = datetime.now().weekday() >= 5

            if is_weekend:
                common_symbols = ["XAUUSD", "BTCUSD", "ETHUSD", "LTCUSD"]
            else:
                common_symbols = [
                    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                    "EURGBP", "EURJPY", "GBPJPY", "AUDCAD", "NZDUSD",
                    "XAUUSD", "BTCUSD", "ETHUSD", "LTCUSD"
                ]

            available = []
            for symbol in common_symbols:
                try:
                    if self.api.get_all_open_time().get("binary", {}).get(symbol, {}).get("open", False):
                        available.append(symbol)
                except Exception as e:
                    logger.error(f"Error al verificar símbolo {symbol}: {str(e)}")
                    continue

            return available if available else common_symbols[:10]

        except Exception as e:
            error_message = f"Error obteniendo símbolos: {str(e)}"
            logger.error(error_message)
            self.send_telegram_message(error_message)
            return ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]

    def place_order(self, symbol, amount, direction, duration=1):
        """Realizar una operación"""
        try:
            if not self.is_connected:
                return False, "No conectado a IQ Option"

            if amount < 1:
                return False, "El monto mínimo es $1"

            if direction not in ["call", "put"]:
                return False, "Dirección inválida (call/put)"

            success, order_id = self.api.buy(amount, symbol, direction, duration)

            if success:
                message = f"Operación exitosa: {symbol} - ${amount} - {direction}"
                logger.info(message)
                self.send_telegram_message(message)
                return True, order_id
            else:
                error_message = f"Operación fallida: {symbol}"
                logger.error(error_message)
                self.send_telegram_message(error_message)
                return False, error_message

        except Exception as e:
            error_message = f"Error en operación: {str(e)}"
            logger.error(error_message)
            self.send_telegram_message(error_message)
            return False, error_message

    def check_win(self, order_id):
        """Verificar resultado de una operación"""
        try:
            if not self.is_connected:
                return None, 0

            time.sleep(2)

            result = self.api.check_win_v3(order_id)

            if result > 0:
                return "WIN", result
            elif result < 0:
                return "LOSS", result
            else:
                return "PENDING", 0

        except Exception as e:
            error_message = f"Error verificando resultado: {str(e)}"
            logger.error(error_message)
            self.send_telegram_message(error_message)
            return "ERROR", 0

bot = IQOptionBot()

@app.route('/connect', methods=['POST'])
def connect():
    """Endpoint para conectar a IQ Option"""
    try:
        data = request.get_json()
        email = data.get('email', IQ_EMAIL)
        password = data.get('password', IQ_PASSWORD)

        success, message = bot.connect(email, password)

        if success:
            balance = bot.get_balance()
            return jsonify({"success": True, "message": message, "balance": balance})

        return jsonify({"success": success, "message": message})

    except Exception as e:
        error_message = f"Error en /connect: {str(e)}"
        logger.error(error_message)
        return jsonify({"success": False, "message": error_message}), 500

@app.route('/symbols', methods=['GET'])
def get_symbols():
    """Endpoint para obtener símbolos disponibles"""
    try:
        symbols = bot.get_available_symbols()
        return jsonify({"symbols": symbols})
    except Exception as e:
        error_message = f"Error en /symbols: {str(e)}"
        logger.error(error_message)
        return jsonify({"symbols": []}), 500

@app.route('/start_bot', methods=['POST'])
def start_bot():
    """Endpoint para iniciar el bot"""
    try:
        if not bot.is_connected:
            return jsonify({"error": "No conectado a IQ Option"}), 400

        data = request.get_json()
        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account = data.get('account', 'PRACTICE')
        direction = data.get('direction', 'call')

        bot.api.change_balance(account)

        balance = bot.get_balance(account)

        def execute_trade():
            try:
                current_amount = amount
                trades_count = 0
                max_trades = martingalas + 1

                while trades_count < max_trades:
                    current_balance = bot.get_balance(account)
                    if current_balance < current_amount:
                        message = f'Balance insuficiente: ${current_balance}'
                        logger.error(message)
                        bot.send_telegram_message(message)
                        break

                    message = f'Operación: {symbol} - ${current_amount} - {direction}'
                    logger.info(message)
                    bot.send_telegram_message(message)

                    success, order_id = bot.place_order(symbol, current_amount, direction)

                    if not success:
                        message = f'Error en operación: {order_id}'
                        logger.error(message)
                        bot.send_telegram_message(message)
                        break

                    time.sleep(65)

                    result, profit = bot.check_win(order_id)

                    message = f'Resultado: {result} | P&L: ${profit}'
                    logger.info(message)
                    bot.send_telegram_message(message)

                    if result == "WIN":
                        final_balance = bot.get_balance(account)
                        message = f'Balance final: ${final_balance}'
                        logger.info(message)
                        bot.send_telegram_message(message)
                        break
                    elif result == "LOSS" and trades_count < max_trades - 1:
                        current_amount *= 2.2
                        trades_count += 1
                        direction = "put" if direction == "call" else "call"
                        time.sleep(5)
                    else:
                        break

                final_balance = bot.get_balance(account)
                message = f'Balance final: ${final_balance}'
                logger.info(message)
                bot.send_telegram_message(message)

            except Exception as e:
                error_message = f"Error en execute_trade: {str(e)}"
                logger.error(error_message)
                bot.send_telegram_message(error_message)

        thread = threading.Thread(target=execute_trade)
        thread.daemon = True
        thread.start()

        return jsonify({"message": "Bot iniciado correctamente"})

    except Exception as e:
        error_message = f"Error en /start_bot: {str(e)}"
        logger.error(error_message)
        return jsonify({"error": error_message}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
