from flask import Flask, request, jsonify, render_template_string
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import asyncio
import threading
import time
import logging
import os
from datetime import datetime
import json

# Importar la librería de IQ Option (instalar con: pip install iqoptionapi)
try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError:
    print("⚠️  Instala iqoptionapi: pip install iqoptionapi")
    IQ_Option = None

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
CORS(app)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class IQOptionBot:
    def __init__(self):
        self.api = None
        self.is_connected = False
        self.is_running = False
        self.current_balance = 0
        self.active_positions = {}
        
    def connect(self, email, password):
        """Conectar a IQ Option"""
        try:
            if not IQ_Option:
                raise Exception("iqoptionapi no está instalada")
                
            self.api = IQ_Option(email, password)
            check, reason = self.api.connect()
            
            if check:
                self.is_connected = True
                logger.info("✅ Conectado a IQ Option exitosamente")
                return True, "Conectado exitosamente"
            else:
                logger.error(f"❌ Error de conexión: {reason}")
                return False, f"Error de conexión: {reason}"
                
        except Exception as e:
            logger.error(f"❌ Error en conexión: {str(e)}")
            return False, f"Error: {str(e)}"
    
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
            logger.error(f"❌ Error obteniendo balance: {str(e)}")
            return 0
    
    def get_available_symbols(self):
        """Obtener símbolos disponibles"""
        try:
            if not self.is_connected:
                return []
                
            # Símbolos más comunes en IQ Option
            common_symbols = [
                "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                "EURGBP", "EURJPY", "GBPJPY", "AUDCAD", "NZDUSD",
                "XAUUSD", "BTCUSD", "ETHUSD", "LTCUSD"
            ]
            
            # Verificar cuáles están disponibles
            available = []
            for symbol in common_symbols:
                try:
                    # Verificar si el activo está abierto
                    if self.api.get_all_open_time().get("binary", {}).get(symbol, {}).get("open", False):
                        available.append(symbol)
                except:
                    continue
                    
            return available if available else common_symbols[:10]  # Fallback
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo símbolos: {str(e)}")
            # Retornar símbolos por defecto en caso de error
            return ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD"]
    
    def place_order(self, symbol, amount, direction, duration=1):
        """Realizar una operación"""
        try:
            if not self.is_connected:
                return False, "No conectado a IQ Option"
            
            # Validar parámetros
            if amount < 1:
                return False, "El monto mínimo es $1"
                
            if direction not in ["call", "put"]:
                return False, "Dirección inválida (call/put)"
            
            # Realizar la operación
            success, order_id = self.api.buy(amount, symbol, direction, duration)
            
            if success:
                logger.info(f"✅ Operación exitosa: {symbol} - ${amount} - {direction}")
                return True, order_id
            else:
                logger.error(f"❌ Operación fallida: {symbol}")
                return False, "Error al realizar la operación"
                
        except Exception as e:
            logger.error(f"❌ Error en operación: {str(e)}")
            return False, f"Error: {str(e)}"
    
    def check_win(self, order_id):
        """Verificar resultado de una operación"""
        try:
            if not self.is_connected:
                return None, 0
                
            # Esperar un momento para que se procese la orden
            time.sleep(2)
            
            # Obtener resultado
            result = self.api.check_win_v3(order_id)
            
            if result > 0:
                return "WIN", result
            elif result < 0:
                return "LOSS", result
            else:
                return "PENDING", 0
                
        except Exception as e:
            logger.error(f"❌ Error verificando resultado: {str(e)}")
            return "ERROR", 0

# Instancia global del bot
bot = IQOptionBot()

# HTML del frontend (tu código actual)
FRONTEND_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Bot IQ Option</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
  <style>
    body {
      font-family: Arial, sans-serif;
      background: #f4f7fa;
      padding: 20px;
    }
    .container {
      max-width: 500px;
      margin: auto;
      background: #fff;
      padding: 20px;
      border-radius: 8px;
      box-shadow: 0 0 10px rgba(0,0,0,0.1);
    }
    h2 {
      text-align: center;
    }
    label, select, input, button {
      display: block;
      width: 100%;
      margin-top: 10px;
    }
    select, input {
      padding: 10px;
      border: 1px solid #ccc;
      border-radius: 5px;
    }
    button {
      background-color: #007bff;
      color: #fff;
      border: none;
      padding: 10px;
      cursor: pointer;
      margin-top: 20px;
      border-radius: 5px;
    }
    button:disabled {
      background-color: #ccc;
      cursor: not-allowed;
    }
    #status {
      margin-top: 20px;
      padding: 10px;
      background: #eee;
      border-radius: 5px;
    }
    .login-section {
      border-bottom: 1px solid #ddd;
      padding-bottom: 20px;
      margin-bottom: 20px;
    }
  </style>
</head>
<body>
  <div class="container">
    <h2>📊 Panel del Bot IQ Option</h2>
    
    <!-- Sección de login -->
    <div class="login-section">
      <label for="email">Email IQ Option:</label>
      <input type="email" id="email" placeholder="tu@email.com" />
      
      <label for="password">Contraseña:</label>
      <input type="password" id="password" placeholder="Tu contraseña" />
      
      <button onclick="connectToIQ()" id="connectBtn">🔌 Conectar a IQ Option</button>
    </div>

    <!-- Sección de trading -->
    <div id="tradingSection" style="display: none;">
      <label for="account">Tipo de cuenta:</label>
      <select id="account">
        <option value="PRACTICE">Demo</option>
        <option value="REAL">Real</option>
      </select>

      <label for="symbol">Activo:</label>
      <select id="symbol">
        <option>Cargando...</option>
      </select>

      <label for="amount">Monto por operación:</label>
      <input type="number" id="amount" placeholder="Ej: 1" min="1" value="1" />

      <label for="martingalas">Martingalas:</label>
      <input type="number" id="martingalas" placeholder="Ej: 2" min="0" value="2" />

      <label for="direction">Dirección:</label>
      <select id="direction">
        <option value="call">CALL (Subir)</option>
        <option value="put">PUT (Bajar)</option>
      </select>

      <button onclick="startBot()" id="startBtn">🚀 Iniciar Bot</button>
    </div>

    <div id="status">📝 Ingresa tus credenciales para comenzar...</div>
  </div>

  <script>
    const socket = io();
    let isConnected = false;

    function updateStatus(msg) {
      document.getElementById("status").innerText = msg;
    }

    async function connectToIQ() {
      const email = document.getElementById("email").value;
      const password = document.getElementById("password").value;
      
      if (!email || !password) {
        updateStatus("❌ Ingresa email y contraseña");
        return;
      }
      
      document.getElementById("connectBtn").disabled = true;
      updateStatus("⏳ Conectando a IQ Option...");
      
      try {
        const res = await fetch("/connect", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password })
        });
        
        const data = await res.json();
        
        if (data.success) {
          isConnected = true;
          document.getElementById("tradingSection").style.display = "block";
          updateStatus("✅ Conectado exitosamente");
          loadSymbols();
        } else {
          updateStatus("❌ " + data.message);
          document.getElementById("connectBtn").disabled = false;
        }
      } catch (err) {
        updateStatus("❌ Error de conexión: " + err.message);
        document.getElementById("connectBtn").disabled = false;
      }
    }

    async function loadSymbols() {
      try {
        const res = await fetch("/symbols");
        const data = await res.json();
        const select = document.getElementById("symbol");
        select.innerHTML = "";
        data.symbols.forEach(s => {
          const opt = document.createElement("option");
          opt.value = s;
          opt.text = s;
          select.appendChild(opt);
        });
      } catch (err) {
        updateStatus("❌ Error cargando símbolos");
        document.getElementById("symbol").innerHTML = '<option>Error al cargar</option>';
      }
    }

    function startBot() {
      if (!isConnected) {
        updateStatus("❌ Primero conecta a IQ Option");
        return;
      }
      
      const symbol = document.getElementById("symbol").value;
      const amount = parseFloat(document.getElementById("amount").value) || 1;
      const martingalas = parseInt(document.getElementById("martingalas").value) || 0;
      const account = document.getElementById("account").value;
      const direction = document.getElementById("direction").value;

      updateStatus("⏳ Enviando operación...");
      document.getElementById("startBtn").disabled = true;

      fetch("/start_bot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, amount, martingalas, account, direction })
      })
      .then(res => res.json())
      .then(data => {
        updateStatus(data.message || data.error);
        document.getElementById("startBtn").disabled = false;
      })
      .catch(err => {
        updateStatus("❌ Error: " + err.message);
        document.getElementById("startBtn").disabled = false;
      });
    }

    // Socket events
    socket.on("balance", (data) => {
      updateStatus(`💰 Balance: $${data.balance}`);
    });

    socket.on("operation", (data) => {
      updateStatus(`📤 Operación: ${data.symbol} - $${data.amount} - ${data.direction.toUpperCase()}`);
    });

    socket.on("result", (data) => {
      updateStatus(`🎯 Resultado: ${data.result} | P&L: $${data.profit}`);
    });

    socket.on("error", (data) => {
      updateStatus(`❌ Error: ${data.msg}`);
    });
  </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(FRONTEND_HTML)

@app.route('/connect', methods=['POST'])
def connect():
    """Endpoint para conectar a IQ Option"""
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña requeridos"})
        
        success, message = bot.connect(email, password)
        
        if success:
            # Emitir balance inicial
            balance = bot.get_balance()
            socketio.emit('balance', {'balance': balance})
            
        return jsonify({"success": success, "message": message})
        
    except Exception as e:
        logger.error(f"Error en /connect: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route('/symbols')
def get_symbols():
    """Endpoint para obtener símbolos disponibles"""
    try:
        symbols = bot.get_available_symbols()
        return jsonify({"symbols": symbols})
    except Exception as e:
        logger.error(f"Error en /symbols: {str(e)}")
        return jsonify({"symbols": ["EURUSD", "GBPUSD", "USDJPY"]})  # Fallback

@app.route('/start_bot', methods=['POST'])
def start_bot():
    """Endpoint para iniciar el bot"""
    try:
        if not bot.is_connected:
            return jsonify({"error": "No conectado a IQ Option"})
        
        data = request.get_json()
        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        martingalas = int(data.get('martingalas', 0))
        account = data.get('account', 'PRACTICE')
        direction = data.get('direction', 'call')
        
        # Cambiar tipo de cuenta
        bot.api.change_balance(account)
        
        # Emitir balance actual
        balance = bot.get_balance(account)
        socketio.emit('balance', {'balance': balance})
        
        # Ejecutar operación en hilo separado
        def execute_trade():
            try:
                current_amount = amount
                trades_count = 0
                max_trades = martingalas + 1
                
                while trades_count < max_trades:
                    # Verificar balance suficiente
                    current_balance = bot.get_balance(account)
                    if current_balance < current_amount:
                        socketio.emit('error', {'msg': f'Balance insuficiente: ${current_balance}'})
                        break
                    
                    # Emitir información de la operación
                    socketio.emit('operation', {
                        'symbol': symbol,
                        'amount': current_amount,
                        'direction': direction
                    })
                    
                    # Realizar operación
                    success, order_id = bot.place_order(symbol, current_amount, direction)
                    
                    if not success:
                        socketio.emit('error', {'msg': f'Error en operación: {order_id}'})
                        break
                    
                    # Esperar resultado (operaciones de 1 minuto)
                    time.sleep(65)  # Esperar un poco más del tiempo de expiración
                    
                    # Verificar resultado
                    result, profit = bot.check_win(order_id)
                    
                    # Emitir resultado
                    socketio.emit('result', {
                        'result': result,
                        'profit': profit
                    })
                    
                    if result == "WIN":
                        # Operación ganadora - terminar
                        final_balance = bot.get_balance(account)
                        socketio.emit('balance', {'balance': final_balance})
                        break
                    elif result == "LOSS" and trades_count < max_trades - 1:
                        # Operación perdedora - aplicar martingala
                        current_amount *= 2.2  # Factor de martingala
                        trades_count += 1
                        
                        # Cambiar dirección (opcional)
                        direction = "put" if direction == "call" else "call"
                        
                        time.sleep(5)  # Pausa entre operaciones
                    else:
                        # No más martingalas o error
                        break
                
                # Balance final
                final_balance = bot.get_balance(account)
                socketio.emit('balance', {'balance': final_balance})
                
            except Exception as e:
                logger.error(f"Error en execute_trade: {str(e)}")
                socketio.emit('error', {'msg': f'Error en ejecución: {str(e)}'})
        
        # Ejecutar en hilo separado para no bloquear
        thread = threading.Thread(target=execute_trade)
        thread.daemon = True
        thread.start()
        
        return jsonify({"message": "🚀 Bot iniciado correctamente"})
        
    except Exception as e:
        logger.error(f"Error en /start_bot: {str(e)}")
        return jsonify({"error": f"Error: {str(e)}"})

@app.route('/balance')
def get_balance():
    """Endpoint para obtener balance actual"""
    try:
        if not bot.is_connected:
            return jsonify({"balance": 0, "error": "No conectado"})
        
        balance = bot.get_balance()
        return jsonify({"balance": balance})
        
    except Exception as e:
        logger.error(f"Error en /balance: {str(e)}")
        return jsonify({"balance": 0, "error": str(e)})

@socketio.on('connect')
def handle_connect():
    """Manejar conexión de socket"""
    logger.info("Cliente conectado via WebSocket")
    emit('status', {'msg': 'Conectado al servidor'})

@socketio.on('disconnect')
def handle_disconnect():
    """Manejar desconexión de socket"""
    logger.info("Cliente desconectado")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Servidor iniciando en puerto {port}")
    
    # Para desarrollo local
    # socketio.run(app, debug=True, host='0.0.0.0', port=port)
    
    # Para producción (Render)
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
