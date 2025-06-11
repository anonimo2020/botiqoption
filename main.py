    # … código previo del método …

    message += f"🎯 Win Rate: {self.session.win_rate:.1f}%\n"
    profit_sign = '+' if self.session.total_profit >= 0 else ''
    message += f"💰 Profit: {profit_sign}${self.session.total_profit:.2f}\n"
    message += f"💵 Balance Final: ${self.session.current_balance:.2f}\n"
    message += f"📉 Max Drawdown: {self.session.max_drawdown:.1f}%\n"
    message += f"🔥 Rachas: {self.session.max_consecutive_wins}W / {self.session.max_consecutive_losses}L"
    self._send_telegram_notification(message)

    # … sigue el resto del método …

    
    def get_status(self) -> Dict[str, Any]:
        """Obtiene el estado actual del bot"""
        return {
            'running': self.running,
            'email': self.email,
            'symbol': self.symbol,
            'strategies': [s.value for s in self.strategies],
            'session': {
                'start_time': self.session.start_time.isoformat(),
                'total_trades': self.session.total_trades,
                'winning_trades': self.session.winning_trades,
                'losing_trades': self.session.losing_trades,
                'win_rate': self.session.win_rate,
                'total_profit': self.session.total_profit,
                'current_balance': self.session.current_balance,
                'consecutive_wins': self.session.consecutive_wins,
                'consecutive_losses': self.session.consecutive_losses,
                'max_drawdown': self.session.max_drawdown
            },
            'risk_manager': {
                'current_balance': self.risk_manager.current_balance,
                'daily_loss': self.risk_manager.daily_loss,
                'max_daily_loss': self.risk_manager.max_daily_loss
            }
        }

# ============================================================================
# FUNCIONES AUXILIARES
# ============================================================================

def send_telegram_message(message: str):
    """Envía mensaje a Telegram (función global para compatibilidad)"""
    bot = AdvancedBinaryBot(None, {}, "system")
    bot._send_telegram_notification(message)

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
# WEBSOCKET EVENTS (SOCKETIO)
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Maneja conexión de WebSocket"""
    if 'user_email' in session:
        email = session['user_email']
        join_room(email)
        logger.info(f"WebSocket conectado para {email}")
        emit('connected', {'status': 'connected'})

@socketio.on('disconnect')
def handle_disconnect():
    """Maneja desconexión de WebSocket"""
    if 'user_email' in session:
        email = session['user_email']
        leave_room(email)
        logger.info(f"WebSocket desconectado para {email}")

@socketio.on('subscribe_candles')
def handle_subscribe_candles(data):
    """Suscribe a actualizaciones de velas"""
    if 'user_email' in session:
        email = session['user_email']
        symbol = data.get('symbol', 'EURUSD')
        
        with data_lock:
            if email not in market_data_streams:
                market_data_streams[email] = set()
            market_data_streams[email].add(symbol)
        
        emit('subscription_confirmed', {'symbol': symbol})

@socketio.on('unsubscribe_candles')
def handle_unsubscribe_candles(data):
    """Cancela suscripción a velas"""
    if 'user_email' in session:
        email = session['user_email']
        symbol = data.get('symbol', 'EURUSD')
        
        with data_lock:
            if email in market_data_streams:
                market_data_streams[email].discard(symbol)

# ============================================================================
# ENDPOINTS API REST
# ============================================================================

@app.after_request
def after_request(response):
    """Headers CORS"""
    origin = request.headers.get('Origin')
    
    if origin in FRONTEND_DOMAINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    elif origin and origin.startswith('http://localhost'):
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = 'https://iqoptionbot.ct.ws'
    
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Accept, Origin'
    response.headers['Access-Control-Max-Age'] = '3600'
    
    return response

@app.route('/', methods=['GET'])
def index():
    """Página principal"""
    return '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot Profesional de Opciones Binarias - IQ Option</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #333;
        }
        
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 50px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            max-width: 900px;
            width: 100%;
            backdrop-filter: blur(10px);
        }
        
        h1 {
            color: #1e3c72;
            font-size: 2.5em;
            margin-bottom: 10px;
            text-align: center;
        }
        
        h2 {
            color: #2a5298;
            font-size: 1.5em;
            margin-bottom: 30px;
            text-align: center;
            font-weight: 400;
        }
        
        .status-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 40px 0;
        }
        
        .status-card {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 10px;
            padding: 20px;
            text-align: center;
            transition: transform 0.3s ease;
        }
        
        .status-card:hover {
            transform: translateY(-5px);
        }
        
        .status-card h3 {
            color: #1e3c72;
            margin-bottom: 10px;
        }
        
        .status-card .value {
            font-size: 1.5em;
            font-weight: bold;
            color: #2a5298;
        }
        
        .status-card.active {
            background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
        }
        
        .endpoints {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 30px;
            margin-top: 40px;
        }
        
        .endpoints h3 {
            color: #1e3c72;
            margin-bottom: 20px;
        }
        
        .endpoints ul {
            list-style: none;
        }
        
        .endpoints li {
            padding: 10px;
            border-left: 3px solid #2a5298;
            margin-bottom: 10px;
            background: white;
            border-radius: 0 5px 5px 0;
            font-family: 'Courier New', monospace;
        }
        
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 30px 0;
        }
        
        .feature {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .feature-icon {
            width: 24px;
            height: 24px;
            background: #2a5298;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
        }
        
        .buttons {
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-top: 40px;
        }
        
        .btn {
            padding: 15px 30px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
            transition: all 0.3s ease;
            display: inline-block;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.4);
        }
        
        .btn-secondary {
            background: white;
            color: #1e3c72;
            border: 2px solid #1e3c72;
        }
        
        .btn-secondary:hover {
            background: #1e3c72;
            color: white;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Bot Profesional de Opciones Binarias</h1>
        <h2>Sistema Avanzado de Trading Automatizado para IQ Option</h2>
        
        <div class="status-grid">
            <div class="status-card active">
                <h3>Estado del Sistema</h3>
                <div class="value">✅ Operativo</div>
            </div>
            <div class="status-card">
                <h3>IQ Option API</h3>
                <div class="value">''' + ('✅ Conectada' if IQ_AVAILABLE else '⚠️ Simulación') + '''</div>
            </div>
            <div class="status-card">
                <h3>WebSocket</h3>
                <div class="value">✅ Activo</div>
            </div>
            <div class="status-card">
                <h3>Estrategias</h3>
                <div class="value">10 Activas</div>
            </div>
        </div>
        
        <div class="features">
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>10 Estrategias Profesionales</span>
            </div>
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>Gestión de Riesgo Avanzada</span>
            </div>
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>6 Métodos de Money Management</span>
            </div>
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>Análisis Técnico en Tiempo Real</span>
            </div>
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>WebSocket para Gráficos en Vivo</span>
            </div>
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>Notificaciones Telegram</span>
            </div>
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>Límites Configurables</span>
            </div>
            <div class="feature">
                <div class="feature-icon">✓</div>
                <span>Multi-Timeframe</span>
            </div>
        </div>
        
        <div class="endpoints">
            <h3>📡 API Endpoints Disponibles:</h3>
            <ul>
                <li>POST /api/login - Autenticación con IQ Option</li>
                <li>GET /api/strategies - Lista de estrategias disponibles</li>
                <li>GET /api/risk-levels - Niveles de riesgo</li>
                <li>POST /api/start_bot - Iniciar bot con configuración</li>
                <li>POST /api/stop_bot - Detener bot</li>
                <li>GET /api/bot_status - Estado actual del bot</li>
                <li>GET /api/live_data - Datos en tiempo real</li>
                <li>GET /api/trading_history - Historial de operaciones</li>
                <li>GET /api/performance - Métricas de rendimiento</li>
                <li>POST /api/update_config - Actualizar configuración</li>
                <li>WS /socket.io - WebSocket para datos en vivo</li>
            </ul>
        </div>
        
        <div class="buttons">
            <a href="/health" class="btn btn-secondary">Health Check</a>
            <a href="/api/strategies" class="btn btn-primary">Ver Estrategias</a>
        </div>
    </div>
</body>
</html>''', 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET'])
@cross_origin(origins=FRONTEND_DOMAINS)
def health_check():
    """Health check del sistema"""
    try:
        # Calcular estadísticas
        active_sessions = len(user_sessions)
        active_bots_count = len([b for b in active_bots.values() if b.running])
        total_bots = len(active_bots)
        
        health_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "version": "2.0.0",
            "environment": "production" if IQ_AVAILABLE else "simulation",
            "features": {
                "iqoption_api": IQ_AVAILABLE,
                "websocket": True,
                "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID),
                "real_time_data": True,
                "multi_strategy": True,
                "risk_management": True,
                "money_management": True
            },
            "statistics": {
                "active_sessions": active_sessions,
                "active_bots": active_bots_count,
                "total_bots": total_bots,
                "strategies_available": len(STRATEGY_CONFIG),
                "risk_levels": len(RiskLevel),
                "money_management_methods": len(MoneyManagement)
            },
            "endpoints": {
                "rest_api": "operational",
                "websocket": "operational",
                "cors": {
                    "enabled": True,
                    "allowed_origins": FRONTEND_DOMAINS
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
    """Login con IQ Option"""
    if request.method == 'OPTIONS':
        return '', 204
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "No se recibieron datos"}), 400
        
        email = data.get('email', '').strip()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({"success": False, "message": "Email y contraseña requeridos"}), 400
        
        logger.info(f"Intento de login: {email}")
        
        # Limpiar sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    if IQ_AVAILABLE and hasattr(user_sessions[email], 'close_websocket'):
                        user_sessions[email].close_websocket()
                except:
                    pass
                del user_sessions[email]
        
        # Detener bot anterior si existe
        with bots_lock:
            if email in active_bots:
                active_bots[email].stop()
                del active_bots[email]
        
        # Conectar con IQ Option
        balance = 1000.0  # Default para simulación
        account_type = "PRACTICE"
        
        if IQ_AVAILABLE:
            try:
                iq = IQ_Option(email, password)
                check, reason = iq.connect()
                
                if not check:
                    return jsonify({
                        "success": False,
                        "message": f"Error de autenticación: {reason}"
                    }), 401
                
                balance = iq.get_balance()
                account_type = iq.get_balance_mode()
                
                # Guardar sesión
                with sessions_lock:
                    user_sessions[email] = iq
                    
            except Exception as e:
                logger.error(f"Error conectando con IQ Option: {e}")
                return jsonify({
                    "success": False,
                    "message": f"Error de conexión: {str(e)}"
                }), 503
        else:
            # Modo simulación
            logger.info("Ejecutando en modo simulación")
            with sessions_lock:
                user_sessions[email] = {"simulation": True}
        
        # Establecer sesión
        session['user_email'] = email
        session.permanent = True
        
        # Notificar login exitoso
        send_telegram_message(
            f"🎯 *LOGIN EXITOSO*\n"
            f"👤 Usuario: {email}\n"
            f"💰 Balance: ${balance:.2f}\n"
            f"🏦 Cuenta: {account_type}\n"
            f"🔧 Modo: {'Real' if IQ_AVAILABLE else 'Simulación'}"
        )
        
        return jsonify({
            "success": True,
            "user": {
                "email": email,
                "name": email.split('@')[0].title(),
                "balance": balance,
                "account_type": account_type,
                "currency": "USD"
            },
            "features": {
                "real_trading": IQ_AVAILABLE,
                "websocket": True,
                "strategies": len(STRATEGY_CONFIG),
                "risk_levels": [r.value for r in RiskLevel],
                "money_management": [m.value for m in MoneyManagement]
            },
            "message": f"Bienvenido - Modo {'Real' if IQ_AVAILABLE else 'Simulación'}"
        }), 200
        
    except Exception as e:
        logger.error(f"Error en login: {e}")
        return jsonify({
            "success": False,
            "message": "Error interno del servidor"
        }), 500

@app.route('/api/strategies', methods=['GET'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_strategies():
    """Obtener todas las estrategias disponibles"""
    try:
        strategies = []
        
        for strategy, config in STRATEGY_CONFIG.items():
            strategies.append({
                "id": strategy.value,
                "name": config["name"],
                "description": config["description"],
                "risk_level": config["risk_level"].value,
                "timeframes": config["timeframes"],
                "min_confidence": config["min_confidence"],
                "indicators": config["indicators"],
                "expected_win_rate": config["expected_win_rate"],
                "avg_trades_per_hour": config["avg_trades_per_hour"],
                "best_sessions": config["best_sessions"],
                "avoid_news": config["avoid_news"]
            })
        
        # Agrupar por nivel de riesgo
        grouped = {}
        for strategy in strategies:
            risk_level = strategy["risk_level"]
            if risk_level not in grouped:
                grouped[risk_level] = []
            grouped[risk_level].append(strategy)
        
        return jsonify({
            "strategies": strategies,
            "grouped_by_risk": grouped,
            "total": len(strategies),
            "risk_levels": [
                {
                    "id": r.value,
                    "name": r.value.replace('_', ' ').title(),
                    "description": {
                        "conservative": "Bajo riesgo, 1-2% por operación",
                        "moderate": "Riesgo moderado, 2-5% por operación",
                        "aggressive": "Alto riesgo, 5-10% por operación",
                        "very_aggressive": "Muy alto riesgo, 10%+ por operación"
                    }.get(r.value, "")
                } for r in RiskLevel
            ]
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo estrategias: {e}")
        return jsonify({"error": "Error obteniendo estrategias"}), 500

@app.route('/api/risk-levels', methods=['GET'])
@cross_origin(origins=FRONTEND_DOMAINS)
def get_risk_levels():
    """Obtener niveles de riesgo disponibles"""
    risk_levels = [
        {
            "id": RiskLevel.CONSERVATIVE.value,
            "name": "Conservador",
            "description": "Ideal para principiantes",
            "max_risk_per_trade": "1-2%",
            "max_daily_loss": "5%",
            "recommended_for": "Traders principiantes o con aversión al riesgo"
        },
        {
            "id": RiskLevel.MODERATE.value,
            "name": "Moderado",
            "description": "Balance entre riesgo y recompensa",
            "max_risk_per_trade": "2-5%",
            "max_daily_loss": "10%",
            "recommended_for": "Traders con experiencia media"
        },
        {
            "id": RiskLevel.AGGRESSIVE.value,
            "name": "Agresivo",
            "description": "Para traders experimentados",
            "max_risk_per_trade": "5-10%",
            "max_daily_loss": "20%",
            "recommended_for": "Traders experimentados con alta tolerancia al riesgo"
        },
        {
            "id": RiskLevel.VERY_AGGRESSIVE.value,
            "name": "Muy Agresivo",
            "description": "Alto riesgo, alta recompensa",
            "max_risk_per_trade": "10%+",
            "max_daily_loss": "30%",
            "recommended_for": "Solo para expertos con capital que pueden perder"
        }
    ]
    
    return jsonify({"risk_levels": risk_levels}), 200

@app.route('/api/start_bot', methods=['POST'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
@limiter.limit("5 per minute")
def start_bot():
    """Iniciar bot de trading"""
    try:
        email = session['user_email']
        
        # Verificar si ya hay un bot activo
        with bots_lock:
            if email in active_bots and active_bots[email].running:
                return jsonify({
                    "success": False,
                    "message": "Ya hay un bot activo para esta cuenta"
                }), 400
        
        data = request.get_json()
        
        # Validar configuración
        config = {
            'symbol': data.get('symbol', 'EURUSD'),
            'strategies': data.get('strategies', ['support_resistance']),
            'risk_level': data.get('risk_level', 'moderate'),
            'money_management': data.get('money_management', 'percentage'),
            'account_type': data.get('account_type', 'PRACTICE'),
            'initial_balance': 1000.0,  # Se actualizará con el balance real
            'max_consecutive_losses': int(data.get('max_consecutive_losses', 5)),
            'max_consecutive_wins': int(data.get('max_consecutive_wins', 0)),
            'max_daily_trades': int(data.get('max_daily_trades', 20)),
            'stop_on_profit': float(data.get('stop_on_profit', 0)),
            'stop_on_loss': float(data.get('stop_on_loss', 0))
        }
        
        # Validar estrategias
        valid_strategies = [s.value for s in Strategy]
        for strategy in config['strategies']:
            if strategy not in valid_strategies:
                return jsonify({
                    "success": False,
                    "message": f"Estrategia inválida: {strategy}"
                }), 400
        
        # Obtener API de IQ Option
        iq_api = None
        with sessions_lock:
            if email in user_sessions:
                iq_api = user_sessions[email]
        
        # Obtener balance actual
        if IQ_AVAILABLE and iq_api and hasattr(iq_api, 'get_balance'):
            try:
                config['initial_balance'] = iq_api.get_balance()
            except:
                pass
        
        # Crear y configurar bot
        bot = AdvancedBinaryBot(iq_api, config, email)
        
        # Guardar referencia del bot
        with bots_lock:
            active_bots[email] = bot
        
        # Iniciar bot
        bot.start()
        
        return jsonify({
            "success": True,
            "message": "Bot iniciado exitosamente",
            "config": {
                "symbol": config['symbol'],
                "strategies": config['strategies'],
                "risk_level": config['risk_level'],
                "money_management": config['money_management'],
                "initial_balance": config['initial_balance'],
                "limits": {
                    "max_consecutive_losses": config['max_consecutive_losses'],
                    "max_consecutive_wins": config['max_consecutive_wins'],
                    "max_daily_trades": config['max_daily_trades'],
                    "stop_on_profit": config['stop_on_profit'],
                    "stop_on_loss": config['stop_on_loss']
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error iniciando bot: {e}")
        return jsonify({
            "success": False,
            "message": f"Error iniciando bot: {str(e)}"
        }), 500

@app.route('/api/stop_bot', methods=['POST'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def stop_bot():
    """Detener bot de trading"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                status = bot.get_status()
                bot.stop()
                del active_bots[email]
                
                return jsonify({
                    "success": True,
                    "message": "Bot detenido exitosamente",
                    "final_stats": status['session']
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "message": "No hay bot activo"
                }), 404
                
    except Exception as e:
        logger.error(f"Error deteniendo bot: {e}")
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        }), 500

@app.route('/api/bot_status', methods=['GET'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def bot_status():
    """Obtener estado del bot"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots and active_bots[email].running:
                bot = active_bots[email]
                return jsonify({
                    "success": True,
                    "status": bot.get_status()
                }), 200
            else:
                return jsonify({
                    "success": True,
                    "status": {
                        "running": False,
                        "message": "No hay bot activo"
                    }
                }), 200
                
    except Exception as e:
        logger.error(f"Error obteniendo estado: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/live_data', methods=['GET'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_live_data():
    """Obtener datos en tiempo real del bot"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots and active_bots[email].running:
                bot = active_bots[email]
                
                # Obtener última vela
                current_candle = bot._get_current_candle()
                
                # Obtener estado del bot
                status = bot.get_status()
                
                # Obtener trades recientes
                recent_trades = []
                if hasattr(bot.session, 'trades'):
                    for trade in bot.session.trades[-10:]:  # Últimos 10 trades
                        recent_trades.append({
                            'id': trade.id,
                            'time': trade.entry_time.isoformat(),
                            'symbol': trade.symbol,
                            'direction': trade.direction,
                            'amount': trade.amount,
                            'result': trade.result,
                            'profit': trade.profit
                        })
                
                return jsonify({
                    "success": True,
                    "data": {
                        "current_candle": current_candle,
                        "bot_status": status,
                        "recent_trades": recent_trades,
                        "timestamp": datetime.datetime.now().isoformat()
                    }
                }), 200
            else:
                return jsonify({
                    "success": False,
                    "message": "No hay bot activo"
                }), 404
                
    except Exception as e:
        logger.error(f"Error obteniendo datos en vivo: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/trading_history', methods=['GET'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_trading_history():
    """Obtener historial de trading"""
    try:
        email = session['user_email']
        
        # Parámetros de paginación
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        
        trades = []
        
        # Obtener trades del bot activo
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                if hasattr(bot.session, 'trades'):
                    for trade in bot.session.trades:
                        trades.append({
                            'id': trade.id,
                            'timestamp': trade.entry_time.isoformat(),
                            'symbol': trade.symbol,
                            'direction': trade.direction,
                            'amount': trade.amount,
                            'entry_price': trade.entry_price,
                            'strategy': trade.strategy.value,
                            'confidence': trade.confidence,
                            'result': trade.result,
                            'profit': trade.profit,
                            'expiry_time': trade.expiry_time
                        })
        
        # Ordenar por timestamp descendente
        trades.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Paginar
        start = (page - 1) * per_page
        end = start + per_page
        paginated_trades = trades[start:end]
        
        return jsonify({
            "success": True,
            "trades": paginated_trades,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": len(trades),
                "pages": math.ceil(len(trades) / per_page)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo historial: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/performance', methods=['GET'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def get_performance():
    """Obtener métricas de rendimiento"""
    try:
        email = session['user_email']
        
        performance = {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_profit": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "average_win": 0.0,
            "average_loss": 0.0,
            "best_trade": 0.0,
            "worst_trade": 0.0,
            "consecutive_wins": 0,
            "consecutive_losses": 0,
            "by_strategy": {},
            "by_timeframe": {},
            "daily_performance": []
        }
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                session = bot.session
                
                performance.update({
                    "total_trades": session.total_trades,
                    "winning_trades": session.winning_trades,
                    "losing_trades": session.losing_trades,
                    "win_rate": session.win_rate,
                    "total_profit": session.total_profit,
                    "profit_factor": session.profit_factor,
                    "max_drawdown": session.max_drawdown,
                    "consecutive_wins": session.max_consecutive_wins,
                    "consecutive_losses": session.max_consecutive_losses
                })
                
                # Calcular promedios
                if session.trades:
                    wins = [t.profit for t in session.trades if t.profit and t.profit > 0]
                    losses = [t.profit for t in session.trades if t.profit and t.profit < 0]
                    
                    if wins:
                        performance["average_win"] = np.mean(wins)
                        performance["best_trade"] = max(wins)
                    
                    if losses:
                        performance["average_loss"] = np.mean(losses)
                        performance["worst_trade"] = min(losses)
                    
                    # Rendimiento por estrategia
                    for trade in session.trades:
                        strategy = trade.strategy.value
                        if strategy not in performance["by_strategy"]:
                            performance["by_strategy"][strategy] = {
                                "trades": 0,
                                "wins": 0,
                                "profit": 0.0
                            }
                        
                        performance["by_strategy"][strategy]["trades"] += 1
                        if trade.result == "win":
                            performance["by_strategy"][strategy]["wins"] += 1
                        if trade.profit:
                            performance["by_strategy"][strategy]["profit"] += trade.profit
        
        return jsonify({
            "success": True,
            "performance": performance
        }), 200
        
    except Exception as e:
        logger.error(f"Error obteniendo rendimiento: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/update_config', methods=['POST'])
@cross_origin(origins=FRONTEND_DOMAINS)
@require_auth
def update_config():
    """Actualizar configuración del bot en ejecución"""
    try:
        email = session['user_email']
        data = request.get_json()
        
        with bots_lock:
            if email not in active_bots or not active_bots[email].running:
                return jsonify({
                    "success": False,
                    "message": "No hay bot activo"
                }), 404
            
            bot = active_bots[email]
            
            # Actualizar límites
            if 'max_consecutive_losses' in data:
                bot.max_consecutive_losses = int(data['max_consecutive_losses'])
            
            if 'max_consecutive_wins' in data:
                bot.max_consecutive_wins = int(data['max_consecutive_wins'])
            
            if 'max_daily_trades' in data:
                bot.max_daily_trades = int(data['max_daily_trades'])
            
            if 'stop_on_profit' in data:
                bot.stop_on_profit = float(data['stop_on_profit'])
            
            if 'stop_on_loss' in data:
                bot.stop_on_loss = float(data['stop_on_loss'])
            
            if 'min_time_between_trades' in data:
                bot.min_time_between_trades = int(data['min_time_between_trades'])
            
            # No se pueden cambiar estrategias o risk level en caliente
            # Requiere reiniciar el bot
            
            return jsonify({
                "success": True,
                "message": "Configuración actualizada",
                "updated_config": {
                    "max_consecutive_losses": bot.max_consecutive_losses,
                    "max_consecutive_wins": bot.max_consecutive_wins,
                    "max_daily_trades": bot.max_daily_trades,
                    "stop_on_profit": bot.stop_on_profit,
                    "stop_on_loss": bot.stop_on_loss,
                    "min_time_between_trades": bot.min_time_between_trades
                }
            }), 200
            
    except Exception as e:
        logger.error(f"Error actualizando configuración: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/logout', methods=['POST'])
@cross_origin(origins=FRONTEND_DOMAINS)
def logout():
    """Cerrar sesión"""
    try:
        email = session.get('user_email')
        
        if email:
            # Detener bot si está activo
            with bots_lock:
                if email in active_bots:
                    active_bots[email].stop()
                    del active_bots[email]
            
            # Cerrar conexión IQ Option
            with sessions_lock:
                if email in user_sessions:
                    if IQ_AVAILABLE and hasattr(user_sessions[email], 'close_websocket'):
                        try:
                            user_sessions[email].close_websocket()
                        except:
                            pass
                    del user_sessions[email]
            
            # Limpiar datos de mercado
            with data_lock:
                if email in market_data_streams:
                    del market_data_streams[email]
            
            # Limpiar sesión
            session.clear()
            
            send_telegram_message(
                f"👋 *LOGOUT*\n"
                f"👤 Usuario: {email}\n"
                f"⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
        
        return jsonify({
            "success": True,
            "message": "Sesión cerrada exitosamente"
        }), 200
        
    except Exception as e:
        logger.error(f"Error en logout: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# ============================================================================
# MANEJO DE ERRORES
# ============================================================================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Endpoint no encontrado",
        "message": "La ruta solicitada no existe",
        "available_endpoints": [
            "/health",
            "/api/login",
            "/api/strategies",
            "/api/risk-levels",
            "/api/start_bot",
            "/api/stop_bot",
            "/api/bot_status",
            "/api/live_data",
            "/api/trading_history",
            "/api/performance",
            "/api/update_config",
            "/api/logout"
        ]
    }), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Error interno: {error}")
    return jsonify({
        "error": "Error interno del servidor",
        "message": "Ha ocurrido un error inesperado"
    }), 500

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": "Límite de peticiones excedido",
        "message": f"Demasiadas peticiones. {e.description}"
    }), 429

# ============================================================================
# FUNCIONES DE LIMPIEZA Y MANTENIMIENTO
# ============================================================================

def cleanup_inactive_sessions():
    """Limpia sesiones inactivas periódicamente"""
    while True:
        try:
            time.sleep(3600)  # Cada hora
            
            with sessions_lock:
                inactive_emails = []
                
                for email, api in list(user_sessions.items()):
                    # Verificar si la sesión sigue activa
                    if email not in active_bots:
                        # No hay bot activo, verificar tiempo de inactividad
                        inactive_emails.append(email)
                
                # Limpiar sesiones inactivas
                for email in inactive_emails:
                    logger.info(f"Limpiando sesión inactiva: {email}")
                    if IQ_AVAILABLE and hasattr(user_sessions[email], 'close_websocket'):
                        try:
                            user_sessions[email].close_websocket()
                        except:
                            pass
                    del user_sessions[email]
                    
        except Exception as e:
            logger.error(f"Error en limpieza de sesiones: {e}")

def reset_daily_limits():
    """Reinicia límites diarios a medianoche"""
    while True:
        try:
            # Calcular tiempo hasta medianoche
            now = datetime.datetime.now()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
            sleep_time = (midnight - now).total_seconds()
            
            time.sleep(sleep_time)
            
            # Reiniciar límites diarios
            with bots_lock:
                for bot in active_bots.values():
                    bot.risk_manager.reset_daily_limits()
                    
            logger.info("Límites diarios reiniciados")
            
        except Exception as e:
            logger.error(f"Error reiniciando límites diarios: {e}")

def graceful_shutdown(signum=None, frame=None):
    """Cierre ordenado del sistema"""
    logger.info("🛑 Iniciando cierre ordenado del sistema...")
    
    # Detener todos los bots
    with bots_lock:
        for email, bot in list(active_bots.items()):
            try:
                logger.info(f"Deteniendo bot para {email}")
                bot.stop()
            except Exception as e:
                logger.error(f"Error deteniendo bot {email}: {e}")
        active_bots.clear()
    
    # Cerrar todas las conexiones IQ Option
    with sessions_lock:
        for email, api in list(user_sessions.items()):
            try:
                if IQ_AVAILABLE and hasattr(api, 'close_websocket'):
                    logger.info(f"Cerrando conexión para {email}")
                    api.close_websocket()
            except Exception as e:
                logger.error(f"Error cerrando conexión {email}: {e}")
        user_sessions.clear()
    
    logger.info("✅ Sistema cerrado correctamente")
    
    # Salir
    if signum:
        sys.exit(0)

# Registrar manejadores de señales
signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)
atexit.register(lambda: graceful_shutdown())

# THREADS DE MANTENIMIENTO CONDICIONADO PARA RENDER
def start_maintenance_threads():
    """Iniciar threads de mantenimiento solo si no es Render"""
    if not os.environ.get('RENDER'):
        # Solo en desarrollo local
        Thread(target=cleanup_inactive_sessions, daemon=True).start()
        Thread(target=reset_daily_limits, daemon=True).start()
        logger.info("Threads de mantenimiento iniciados")
    else:
        logger.info("Threads de mantenimiento deshabilitados en Render")

# ============================================================================
# MAIN - PUNTO DE ENTRADA OPTIMIZADO PARA RENDER
# ============================================================================

# Para producción, este bloque solo muestra información
port = int(os.environ.get('PORT', 5000))

logger.info("=" * 70)
logger.info("🎯 BOT PROFESIONAL DE OPCIONES BINARIAS - IQ OPTION V2.0")
logger.info("=" * 70)
logger.info(f"📍 Puerto: {port}")
logger.info(f"🌐 Frontend: https://iqoptionbot.ct.ws")
logger.info(f"🔧 Modo: {'REAL' if IQ_AVAILABLE else 'SIMULACIÓN'}")
logger.info(f"📱 Telegram: {'✅ Configurado' if TELEGRAM_BOT_TOKEN else '❌ No configurado'}")
logger.info(f"📊 Estrategias disponibles: {len(STRATEGY_CONFIG)}")
logger.info(f"💰 Métodos de gestión de dinero: {len(MoneyManagement)}")
logger.info(f"⚠️ Niveles de riesgo: {len(RiskLevel)}")
logger.info("")
logger.info("✨ CARACTERÍSTICAS PRINCIPALES:")
logger.info("   • 10 estrategias profesionales de trading")
logger.info("   • Análisis técnico en tiempo real")
logger.info("   • WebSocket para datos en vivo y gráficos")
logger.info("   • 6 métodos de gestión monetaria")
logger.info("   • 4 niveles de riesgo configurables")
logger.info("   • Límites automáticos (pérdidas/ganancias/diario)")
logger.info("   • Notificaciones Telegram en tiempo real")
logger.info("   • API REST completa + WebSocket")
logger.info("   • Interfaz para gráficos de velas en tiempo real")
logger.info("=" * 70)

if not IQ_AVAILABLE:
    logger.warning("⚠️ MODO SIMULACIÓN ACTIVO")
    logger.info("Para activar trading real:")
    logger.info("pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")

# Notificar inicio
send_telegram_message(
    f"🚀 *BACKEND INICIADO*\n"
    f"🔧 Versión: 2.0.0\n"
    f"📍 Puerto: {port}\n"
    f"💻 Modo: {'REAL' if IQ_AVAILABLE else 'SIMULACIÓN'}\n"
    f"📊 Estrategias: {len(STRATEGY_CONFIG)}\n"
    f"⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
)

# CONFIGURACIÓN OPTIMIZADA PARA RENDER
if __name__ == '__main__':
    # Detectar si estamos en Render
    if os.environ.get('RENDER'):
        # En producción con Render, NO ejecutar socketio.run()
        # Gunicorn manejará la aplicación
        logger.info("🚀 Ejecutando en modo producción con Render/Gunicorn")
        logger.info("⚠️ NO iniciando threads de mantenimiento para evitar loops infinitos")
        # NO ejecutar socketio.run() aquí
    else:
        # En desarrollo local
        logger.info("🔧 Ejecutando en modo desarrollo")
        start_maintenance_threads()
        try:
            socketio.run(app, host='0.0.0.0', port=port, debug=False)
        except KeyboardInterrupt:
            graceful_shutdown()
else:
    # Esta es la configuración para Gunicorn en producción
    logger.info("🚀 Aplicación cargada para Gunicorn en Render")
    
    # Para Gunicorn, la aplicación WSGI debe ser accesible
    # SocketIO se manejará automáticamente
    application = socketio.wsgi_app# main.py - Backend Profesional para Bot de Opciones Binarias IQ Option
# Con estrategias mejoradas, gestión de riesgo avanzada y datos en tiempo real

import os
import sys
import logging
import datetime
import time
import requests
import numpy as np
import pandas as pd
from functools import wraps
from threading import Thread, Lock, Event, Timer
import json
import math
import signal
import atexit
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from collections import deque
import asyncio
import websocket
from concurrent.futures import ThreadPoolExecutor

# Configuración de logging mejorada
log_format = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    handlers=[
        logging.FileHandler('/tmp/iqoption_bot.log') if not os.environ.get('RENDER') else logging.StreamHandler(),
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
from flask_socketio import SocketIO, emit, join_room, leave_room

# Importar IQOptionAPI
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada correctamente")
except ImportError as e:
    logger.error(f"❌ Error cargando IQOptionAPI: {e}")
    IQ_AVAILABLE = False

# ============================================================================
# CONFIGURACIÓN FLASK Y SOCKETIO
# ============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'iqoption-bot-secure-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24

# SocketIO para comunicación en tiempo real
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# CORS mejorado
FRONTEND_DOMAINS = [
    "https://iqoptionbot.ct.ws",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

CORS(app, 
     origins=FRONTEND_DOMAINS,
     methods=['GET', 'POST', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization', 'Accept', 'Origin'],
     supports_credentials=True,
     max_age=3600)

Session(app)

# Rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["2000 per day", "300 per hour"]
)

# Variables globales mejoradas
user_sessions = {}
active_bots = {}
market_data_streams = {}
sessions_lock = Lock()
bots_lock = Lock()
data_lock = Lock()

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# Pool de threads para operaciones asíncronas
executor = ThreadPoolExecutor(max_workers=10)

# ============================================================================
# ENUMS Y CONFIGURACIÓN MEJORADA
# ============================================================================

class RiskLevel(Enum):
    CONSERVATIVE = "conservative"      # 1-2% por operación
    MODERATE = "moderate"             # 2-5% por operación  
    AGGRESSIVE = "aggressive"         # 5-10% por operación
    VERY_AGGRESSIVE = "very_aggressive"  # 10%+ por operación

class Strategy(Enum):
    # Estrategias de bajo riesgo (60-70% win rate)
    SUPPORT_RESISTANCE = "support_resistance"
    TREND_FOLLOWING = "trend_following"
    
    # Estrategias de riesgo moderado (50-60% win rate)
    BOLLINGER_BOUNCE = "bollinger_bounce"
    RSI_DIVERGENCE = "rsi_divergence"
    MACD_CROSS = "macd_cross"
    
    # Estrategias de alto riesgo (40-50% win rate pero mayor payout)
    BREAKOUT = "breakout"
    NEWS_TRADING = "news_trading"
    MOMENTUM_SCALPING = "momentum_scalping"
    
    # Estrategias combinadas
    MULTI_INDICATOR = "multi_indicator"
    AI_PATTERN = "ai_pattern"

class MoneyManagement(Enum):
    FIXED_AMOUNT = "fixed_amount"
    PERCENTAGE = "percentage"
    MARTINGALE = "martingale"
    ANTI_MARTINGALE = "anti_martingale"
    FIBONACCI = "fibonacci"
    KELLY_CRITERION = "kelly_criterion"

# Configuración detallada de estrategias
STRATEGY_CONFIG = {
    Strategy.SUPPORT_RESISTANCE: {
        "name": "Soporte y Resistencia",
        "description": "Opera en rebotes de niveles clave identificados automáticamente",
        "risk_level": RiskLevel.CONSERVATIVE,
        "timeframes": [60, 300, 900],  # 1m, 5m, 15m
        "min_confidence": 75,
        "indicators": ["support_resistance", "volume", "rsi"],
        "expected_win_rate": 65,
        "avg_trades_per_hour": 2,
        "best_sessions": ["london", "new_york"],
        "avoid_news": True
    },
    Strategy.TREND_FOLLOWING: {
        "name": "Seguimiento de Tendencia",
        "description": "Identifica y sigue tendencias fuertes con confirmación múltiple",
        "risk_level": RiskLevel.CONSERVATIVE,
        "timeframes": [300, 900, 1800],  # 5m, 15m, 30m
        "min_confidence": 70,
        "indicators": ["ema", "macd", "adx", "volume"],
        "expected_win_rate": 62,
        "avg_trades_per_hour": 3,
        "best_sessions": ["london", "new_york"],
        "avoid_news": False
    },
    Strategy.BOLLINGER_BOUNCE: {
        "name": "Rebote en Bandas de Bollinger",
        "description": "Opera reversiones en los extremos de las bandas con filtros adicionales",
        "risk_level": RiskLevel.MODERATE,
        "timeframes": [60, 300],  # 1m, 5m
        "min_confidence": 65,
        "indicators": ["bollinger_bands", "rsi", "stochastic"],
        "expected_win_rate": 58,
        "avg_trades_per_hour": 4,
        "best_sessions": ["all"],
        "avoid_news": True
    },
    Strategy.RSI_DIVERGENCE: {
        "name": "Divergencias RSI",
        "description": "Detecta divergencias entre precio y RSI para anticipar reversiones",
        "risk_level": RiskLevel.MODERATE,
        "timeframes": [300, 900],  # 5m, 15m
        "min_confidence": 68,
        "indicators": ["rsi", "price_action", "volume"],
        "expected_win_rate": 56,
        "avg_trades_per_hour": 2,
        "best_sessions": ["london", "new_york"],
        "avoid_news": True
    },
    Strategy.MACD_CROSS: {
        "name": "Cruce MACD Optimizado",
        "description": "Cruces MACD con filtros de tendencia y momentum",
        "risk_level": RiskLevel.MODERATE,
        "timeframes": [300, 900],  # 5m, 15m
        "min_confidence": 60,
        "indicators": ["macd", "ema", "atr"],
        "expected_win_rate": 55,
        "avg_trades_per_hour": 3,
        "best_sessions": ["london", "new_york"],
        "avoid_news": False
    },
    Strategy.BREAKOUT: {
        "name": "Ruptura de Rangos",
        "description": "Opera rupturas de consolidaciones y rangos con volumen",
        "risk_level": RiskLevel.AGGRESSIVE,
        "timeframes": [60, 300],  # 1m, 5m
        "min_confidence": 55,
        "indicators": ["atr", "volume", "bollinger_bands"],
        "expected_win_rate": 48,
        "avg_trades_per_hour": 5,
        "best_sessions": ["london_open", "new_york_open"],
        "avoid_news": False
    },
    Strategy.NEWS_TRADING: {
        "name": "Trading de Noticias",
        "description": "Opera la volatilidad generada por noticias económicas importantes",
        "risk_level": RiskLevel.VERY_AGGRESSIVE,
        "timeframes": [60],  # 1m
        "min_confidence": 50,
        "indicators": ["atr", "volume_spike"],
        "expected_win_rate": 45,
        "avg_trades_per_hour": 1,
        "best_sessions": ["news_events"],
        "avoid_news": False
    },
    Strategy.MOMENTUM_SCALPING: {
        "name": "Scalping de Momentum",
        "description": "Operaciones rápidas siguiendo el momentum del mercado",
        "risk_level": RiskLevel.AGGRESSIVE,
        "timeframes": [60],  # 1m
        "min_confidence": 52,
        "indicators": ["momentum", "volume", "ema_fast"],
        "expected_win_rate": 47,
        "avg_trades_per_hour": 8,
        "best_sessions": ["high_volatility"],
        "avoid_news": False
    },
    Strategy.MULTI_INDICATOR: {
        "name": "Multi-Indicador Avanzado",
        "description": "Combina múltiples indicadores con machine learning básico",
        "risk_level": RiskLevel.MODERATE,
        "timeframes": [300, 900],  # 5m, 15m
        "min_confidence": 70,
        "indicators": ["all"],
        "expected_win_rate": 60,
        "avg_trades_per_hour": 3,
        "best_sessions": ["london", "new_york"],
        "avoid_news": True
    },
    Strategy.AI_PATTERN: {
        "name": "Reconocimiento de Patrones IA",
        "description": "Utiliza patrones históricos y análisis predictivo",
        "risk_level": RiskLevel.MODERATE,
        "timeframes": [300, 900],  # 5m, 15m
        "min_confidence": 72,
        "indicators": ["pattern_recognition", "ml_signals"],
        "expected_win_rate": 63,
        "avg_trades_per_hour": 2,
        "best_sessions": ["all"],
        "avoid_news": True
    }
}

# ============================================================================
# CLASES DE DATOS MEJORADAS
# ============================================================================

@dataclass
class Trade:
    id: str
    symbol: str
    direction: str  # "call" o "put"
    amount: float
    entry_price: float
    entry_time: datetime.datetime
    expiry_time: int  # en minutos
    strategy: Strategy
    confidence: float
    indicators_data: Dict[str, Any]
    result: Optional[str] = None  # "win", "loss", "draw"
    exit_price: Optional[float] = None
    profit: Optional[float] = None
    
@dataclass
class MarketData:
    symbol: str
    timeframe: int
    timestamp: datetime.datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    indicators: Dict[str, float] = field(default_factory=dict)

@dataclass
class TradingSession:
    start_time: datetime.datetime
    end_time: Optional[datetime.datetime] = None
    initial_balance: float = 0.0
    current_balance: float = 0.0
    trades: List[Trade] = field(default_factory=list)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    
    def add_trade(self, trade: Trade):
        self.trades.append(trade)
        self.total_trades += 1
        
        if trade.result == "win":
            self.winning_trades += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            self.max_consecutive_wins = max(self.max_consecutive_wins, self.consecutive_wins)
        elif trade.result == "loss":
            self.losing_trades += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.max_consecutive_losses = max(self.max_consecutive_losses, self.consecutive_losses)
            
        if trade.profit:
            self.total_profit += trade.profit
            self.current_balance += trade.profit
            
        # Calcular drawdown
        peak_balance = max(self.initial_balance, self.current_balance)
        self.current_drawdown = (peak_balance - self.current_balance) / peak_balance * 100
        self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
    
    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def profit_factor(self) -> float:
        total_wins = sum(t.profit for t in self.trades if t.profit and t.profit > 0)
        total_losses = abs(sum(t.profit for t in self.trades if t.profit and t.profit < 0))
        if total_losses == 0:
            return float('inf') if total_wins > 0 else 0
        return total_wins / total_losses

# ============================================================================
# ANÁLISIS TÉCNICO MEJORADO
# ============================================================================

class TechnicalAnalysis:
    """Clase para cálculo de indicadores técnicos"""
    
    @staticmethod
    def calculate_sma(data: List[float], period: int) -> float:
        """Media móvil simple"""
        if len(data) < period:
            return None
        return sum(data[-period:]) / period
    
    @staticmethod
    def calculate_ema(data: List[float], period: int) -> float:
        """Media móvil exponencial"""
        if len(data) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(data[:period]) / period
        
        for price in data[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    @staticmethod
    def calculate_rsi(data: List[float], period: int = 14) -> float:
        """Índice de fuerza relativa"""
        if len(data) < period + 1:
            return None
        
        gains = []
        losses = []
        
        for i in range(1, len(data)):
            change = data[i] - data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        
        if avg_loss == 0:
            return 100
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    @staticmethod
    def calculate_bollinger_bands(data: List[float], period: int = 20, std_dev: int = 2) -> Tuple[float, float, float]:
        """Bandas de Bollinger"""
        if len(data) < period:
            return None, None, None
        
        sma = sum(data[-period:]) / period
        variance = sum((x - sma) ** 2 for x in data[-period:]) / period
        std = math.sqrt(variance)
        
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        
        return upper_band, sma, lower_band
    
    @staticmethod
    def calculate_macd(data: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
        """MACD"""
        if len(data) < slow + signal:
            return None, None, None
        
        ema_fast = TechnicalAnalysis.calculate_ema(data, fast)
        ema_slow = TechnicalAnalysis.calculate_ema(data, slow)
        
        if ema_fast is None or ema_slow is None:
            return None, None, None
        
        macd_line = ema_fast - ema_slow
        
        # Calcular línea de señal
        macd_values = []
        for i in range(slow, len(data)):
            ema_f = TechnicalAnalysis.calculate_ema(data[:i+1], fast)
            ema_s = TechnicalAnalysis.calculate_ema(data[:i+1], slow)
            if ema_f and ema_s:
                macd_values.append(ema_f - ema_s)
        
        signal_line = TechnicalAnalysis.calculate_ema(macd_values, signal)
        histogram = macd_line - signal_line if signal_line else None
        
        return macd_line, signal_line, histogram
    
    @staticmethod
    def calculate_stochastic(high: List[float], low: List[float], close: List[float], period: int = 14) -> Tuple[float, float]:
        """Oscilador estocástico"""
        if len(high) < period or len(low) < period or len(close) < period:
            return None, None
        
        lowest_low = min(low[-period:])
        highest_high = max(high[-period:])
        
        if highest_high == lowest_low:
            return 50, 50
        
        k = ((close[-1] - lowest_low) / (highest_high - lowest_low)) * 100
        
        # %D es el SMA de 3 períodos de %K
        k_values = []
        for i in range(period, len(close)):
            ll = min(low[i-period+1:i+1])
            hh = max(high[i-period+1:i+1])
            if hh != ll:
                k_val = ((close[i] - ll) / (hh - ll)) * 100
                k_values.append(k_val)
        
        d = sum(k_values[-3:]) / 3 if len(k_values) >= 3 else k
        
        return k, d
    
    @staticmethod
    def find_support_resistance(data: List[float], window: int = 20) -> Tuple[List[float], List[float]]:
        """Encuentra niveles de soporte y resistencia"""
        if len(data) < window * 2:
            return [], []
        
        supports = []
        resistances = []
        
        for i in range(window, len(data) - window):
            # Buscar mínimos locales (soportes)
            if all(data[i] <= data[j] for j in range(i - window, i + window + 1)):
                supports.append(data[i])
            
            # Buscar máximos locales (resistencias)
            if all(data[i] >= data[j] for j in range(i - window, i + window + 1)):
                resistances.append(data[i])
        
        # Agrupar niveles cercanos
        def group_levels(levels, threshold=0.001):
            if not levels:
                return []
            
            grouped = []
            levels.sort()
            current_group = [levels[0]]
            
            for level in levels[1:]:
                if abs(level - current_group[-1]) / current_group[-1] < threshold:
                    current_group.append(level)
                else:
                    grouped.append(sum(current_group) / len(current_group))
                    current_group = [level]
            
            grouped.append(sum(current_group) / len(current_group))
            return grouped
        
        return group_levels(supports), group_levels(resistances)

# ============================================================================
# GESTIÓN DE RIESGO AVANZADA
# ============================================================================

class RiskManager:
    """Gestión avanzada de riesgo y tamaño de posiciones"""
    
    def __init__(self, initial_balance: float, risk_level: RiskLevel):
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.risk_level = risk_level
        self.max_risk_per_trade = self._get_max_risk_percentage()
        self.max_daily_loss = self._get_max_daily_loss()
        self.daily_loss = 0.0
        self.trade_history = deque(maxlen=100)
        
    def _get_max_risk_percentage(self) -> float:
        """Obtiene el porcentaje máximo de riesgo por operación"""
        risk_map = {
            RiskLevel.CONSERVATIVE: 0.01,      # 1%
            RiskLevel.MODERATE: 0.025,         # 2.5%
            RiskLevel.AGGRESSIVE: 0.05,        # 5%
            RiskLevel.VERY_AGGRESSIVE: 0.1     # 10%
        }
        return risk_map.get(self.risk_level, 0.02)
    
    def _get_max_daily_loss(self) -> float:
        """Obtiene la pérdida máxima diaria permitida"""
        loss_map = {
            RiskLevel.CONSERVATIVE: 0.05,      # 5%
            RiskLevel.MODERATE: 0.10,          # 10%
            RiskLevel.AGGRESSIVE: 0.20,        # 20%
            RiskLevel.VERY_AGGRESSIVE: 0.30    # 30%
        }
        return self.initial_balance * loss_map.get(self.risk_level, 0.10)
    
    def calculate_position_size(self, confidence: float, money_management: MoneyManagement, 
                              consecutive_losses: int = 0, win_rate: float = 0.5) -> float:
        """Calcula el tamaño óptimo de la posición"""
        
        # Verificar límite diario
        if self.daily_loss >= self.max_daily_loss:
            logger.warning("Límite de pérdida diaria alcanzado")
            return 0
        
        base_amount = self.current_balance * self.max_risk_per_trade
        
        if money_management == MoneyManagement.FIXED_AMOUNT:
            return min(base_amount, self.current_balance * 0.05)
        
        elif money_management == MoneyManagement.PERCENTAGE:
            # Ajustar por confianza
            confidence_multiplier = confidence / 100
            return base_amount * confidence_multiplier
        
        elif money_management == MoneyManagement.MARTINGALE:
            # Martingala con límites
            max_multiplier = 8  # Máximo 3 duplicaciones
            multiplier = min(2 ** consecutive_losses, max_multiplier)
            amount = base_amount * multiplier
            
            # Limitar al 10% del balance
            return min(amount, self.current_balance * 0.10)
        
        elif money_management == MoneyManagement.ANTI_MARTINGALE:
            # Anti-martingala: aumentar después de ganar
            if consecutive_losses > 0:
                return base_amount * 0.5
            else:
                return base_amount * 1.5
        
        elif money_management == MoneyManagement.FIBONACCI:
            # Secuencia de Fibonacci
            fib_sequence = [1, 1, 2, 3, 5, 8, 13, 21]
            index = min(consecutive_losses, len(fib_sequence) - 1)
            multiplier = fib_sequence[index]
            amount = base_amount * multiplier
            
            return min(amount, self.current_balance * 0.10)
        
        elif money_management == MoneyManagement.KELLY_CRITERION:
            # Criterio de Kelly
            if win_rate <= 0 or win_rate >= 1:
                return base_amount
            
            # Asumiendo payout de 0.8 (80%)
            payout = 0.8
            kelly_percentage = (payout * win_rate - (1 - win_rate)) / payout
            
            # Aplicar fracción de Kelly (25%) para ser más conservador
            kelly_fraction = 0.25
            amount = self.current_balance * kelly_percentage * kelly_fraction
            
            # Limitar entre 1% y 5% del balance
            return max(min(amount, self.current_balance * 0.05), self.current_balance * 0.01)
        
        return base_amount
    
    def update_balance(self, profit: float):
        """Actualiza el balance y estadísticas"""
        self.current_balance += profit
        if profit < 0:
            self.daily_loss += abs(profit)
        
        self.trade_history.append({
            'profit': profit,
            'balance': self.current_balance,
            'timestamp': datetime.datetime.now()
        })
    
    def reset_daily_limits(self):
        """Reinicia los límites diarios"""
        self.daily_loss = 0.0
    
    def should_stop_trading(self, consecutive_losses: int) -> bool:
        """Determina si se debe detener el trading"""
        if self.daily_loss >= self.max_daily_loss:
            return True
        
        if self.current_balance <= self.initial_balance * 0.5:
            return True
        
        max_consecutive_losses = {
            RiskLevel.CONSERVATIVE: 3,
            RiskLevel.MODERATE: 5,
            RiskLevel.AGGRESSIVE: 7,
            RiskLevel.VERY_AGGRESSIVE: 10
        }
        
        if consecutive_losses >= max_consecutive_losses.get(self.risk_level, 5):
            return True
        
        return False

# ============================================================================
# BOT DE TRADING MEJORADO
# ============================================================================

class AdvancedBinaryBot:
    """Bot de trading avanzado para opciones binarias"""
    
    def __init__(self, iq_api, config: Dict[str, Any], email: str):
        self.iq_api = iq_api
        self.config = config
        self.email = email
        self.running = False
        self.thread = None
        
        # Configuración de trading
        self.symbol = config.get('symbol', 'EURUSD')
        self.strategies = [Strategy(s) for s in config.get('strategies', ['support_resistance'])]
        self.money_management = MoneyManagement(config.get('money_management', 'percentage'))
        self.risk_level = RiskLevel(config.get('risk_level', 'moderate'))
        
        # Gestión de riesgo
        initial_balance = config.get('initial_balance', 1000)
        self.risk_manager = RiskManager(initial_balance, self.risk_level)
        
        # Sesión de trading
        self.session = TradingSession(
            start_time=datetime.datetime.now(),
            initial_balance=initial_balance,
            current_balance=initial_balance
        )
        
        # Datos de mercado
        self.candles_data = {
            60: deque(maxlen=500),     # 1 minuto
            300: deque(maxlen=200),    # 5 minutos
            900: deque(maxlen=100),    # 15 minutos
            1800: deque(maxlen=50)     # 30 minutos
        }
        
        # WebSocket para datos en tiempo real
        self.ws_running = False
        self.ws_thread = None
        
        # Control de operaciones
        self.min_time_between_trades = 30  # segundos
        self.last_trade_time = None
        self.pending_signals = deque(maxlen=10)
        
        # Límites configurables
        self.max_consecutive_losses = config.get('max_consecutive_losses', 5)
        self.max_consecutive_wins = config.get('max_consecutive_wins', 0)
        self.max_daily_trades = config.get('max_daily_trades', 20)
        self.stop_on_profit = config.get('stop_on_profit', 0)
        self.stop_on_loss = config.get('stop_on_loss', 0)
        
        logger.info(f"Bot inicializado para {email} con estrategias: {[s.value for s in self.strategies]}")
    
    def start(self):
        """Iniciar bot de trading"""
        if self.running:
            logger.warning("El bot ya está en ejecución")
            return
        
        self.running = True
        self.session.start_time = datetime.datetime.now()
        
        # Iniciar recolección de datos
        self._start_data_collection()
        
        # Iniciar thread principal del bot
        self.thread = Thread(target=self._run, daemon=True)
        self.thread.start()
        
        logger.info(f"🚀 Bot iniciado exitosamente para {self.email}")
        self._send_telegram_notification(
            f"🚀 *BOT INICIADO*\n"
            f"👤 Usuario: {self.email}\n"
            f"📈 Estrategias: {', '.join([s.value for s in self.strategies])}\n"
            f"💰 Balance: ${self.session.initial_balance:.2f}\n"
            f"🎯 Gestión: {self.money_management.value}\n"
            f"⚠️ Riesgo: {self.risk_level.value}"
        )
    
    def stop(self):
        """Detener bot de trading"""
        if not self.running:
            return
        
        logger.info("Deteniendo bot...")
        self.running = False
        self.ws_running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        if self.ws_thread:
            self.ws_thread.join(timeout=5)
        
        self.session.end_time = datetime.datetime.now()
        
        # Enviar resumen final
        self._send_final_report()
        logger.info(f"🛑 Bot detenido para {self.email}")
    
    def _start_data_collection(self):
        """Iniciar recolección de datos del mercado"""
        if IQ_AVAILABLE and self.iq_api:
            try:
                # Suscribirse a datos de velas
                self.iq_api.start_candles_stream(self.symbol, 60)
                
                # Iniciar WebSocket para datos en tiempo real
                self.ws_running = True
                self.ws_thread = Thread(target=self._websocket_handler, daemon=True)
                self.ws_thread.start()
                
                logger.info(f"📊 Recolección de datos iniciada para {self.symbol}")
            except Exception as e:
                logger.error(f"Error iniciando recolección de datos: {e}")
    
    def _websocket_handler(self):
        """Maneja la conexión WebSocket para datos en tiempo real"""
        while self.ws_running and self.running:
            try:
                if IQ_AVAILABLE and self.iq_api:
                    # Obtener velas en tiempo real
                    candles = self.iq_api.get_realtime_candles(self.symbol, 60)
                    
                    if candles:
                        for candle_data in candles:
                            self._process_candle(candle_data)
                    
                    # Emitir datos al frontend via SocketIO
                    if self.email in market_data_streams:
                        current_candle = self._get_current_candle()
                        if current_candle:
                            socketio.emit('candle_update', {
                                'symbol': self.symbol,
                                'candle': current_candle
                            }, room=self.email)
                
                time.sleep(1)  # Actualizar cada segundo
                
            except Exception as e:
                logger.error(f"Error en WebSocket handler: {e}")
                time.sleep(5)
    
    def _process_candle(self, candle_data):
        """Procesa datos de velas recibidos"""
        try:
            market_data = MarketData(
                symbol=self.symbol,
                timeframe=60,
                timestamp=datetime.datetime.fromtimestamp(candle_data.get('from', 0)),
                open=candle_data.get('open', 0),
                high=candle_data.get('max', 0),
                low=candle_data.get('min', 0),
                close=candle_data.get('close', 0),
                volume=candle_data.get('volume', 0)
            )
            
            # Almacenar en diferentes timeframes
            self.candles_data[60].append(market_data)
            
            # Agregar a timeframes superiores
            self._aggregate_candles(market_data)
            
        except Exception as e:
            logger.error(f"Error procesando vela: {e}")
    
    def _aggregate_candles(self, candle: MarketData):
        """Agrega velas a timeframes superiores"""
        # Implementación simplificada
        # En producción, esto debería ser más sofisticado
        pass
    
    def _run(self):
        """Loop principal del bot"""
        try:
            # Esperar a tener suficientes datos
            logger.info("Recopilando datos iniciales...")
            time.sleep(10)
            
            while self.running:
                try:
                    # Verificar límites de trading
                    if self._should_stop_trading():
                        logger.info("Límites de trading alcanzados, deteniendo bot")
                        self.stop()
                        break
                    
                    # Analizar mercado y buscar señales
                    signals = self._analyze_market()
                    
                    if signals:
                        # Filtrar y ejecutar mejores señales
                        best_signal = self._filter_signals(signals)
                        if best_signal:
                            self._execute_trade(best_signal)
                    
                    # Verificar trades abiertos
                    self._check_open_trades()
                    
                    # Esperar antes del próximo análisis
                    time.sleep(5)
                    
                except Exception as e:
                    logger.error(f"Error en loop principal: {e}")
                    time.sleep(10)
                    
        except Exception as e:
            logger.error(f"Error crítico en bot: {e}")
        finally:
            self.running = False
    
    def _should_stop_trading(self) -> bool:
        """Verifica si se deben detener las operaciones"""
        # Verificar límites de pérdidas consecutivas
        if self.max_consecutive_losses > 0 and self.session.consecutive_losses >= self.max_consecutive_losses:
            logger.warning(f"Límite de pérdidas consecutivas alcanzado: {self.session.consecutive_losses}")
            return True
        
        # Verificar límites de ganancias consecutivas
        if self.max_consecutive_wins > 0 and self.session.consecutive_wins >= self.max_consecutive_wins:
            logger.info(f"Límite de ganancias consecutivas alcanzado: {self.session.consecutive_wins}")
            return True
        
        # Verificar límite diario de operaciones
        if self.session.total_trades >= self.max_daily_trades:
            logger.info(f"Límite diario de operaciones alcanzado: {self.session.total_trades}")
            return True
        
        # Verificar objetivo de ganancia
        if self.stop_on_profit > 0 and self.session.total_profit >= self.stop_on_profit:
            logger.info(f"Objetivo de ganancia alcanzado: ${self.session.total_profit:.2f}")
            return True
        
        # Verificar límite de pérdida
        if self.stop_on_loss > 0 and abs(self.session.total_profit) >= self.stop_on_loss:
            logger.warning(f"Límite de pérdida alcanzado: ${self.session.total_profit:.2f}")
            return True
        
        # Verificar con el gestor de riesgo
        return self.risk_manager.should_stop_trading(self.session.consecutive_losses)
    
    def _analyze_market(self) -> List[Dict[str, Any]]:
        """Analiza el mercado y genera señales de trading"""
        signals = []
        
        for strategy in self.strategies:
            try:
                signal = self._analyze_strategy(strategy)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Error analizando estrategia {strategy.value}: {e}")
        
        return signals
    
    def _analyze_strategy(self, strategy: Strategy) -> Optional[Dict[str, Any]]:
        """Analiza una estrategia específica"""
        config = STRATEGY_CONFIG[strategy]
        
        # Obtener datos para el timeframe de la estrategia
        timeframe = config['timeframes'][0]
        candles = list(self.candles_data.get(timeframe, []))
        
        if len(candles) < 50:  # Necesitamos suficientes datos
            return None
        
        # Calcular indicadores
        close_prices = [c.close for c in candles]
        high_prices = [c.high for c in candles]
        low_prices = [c.low for c in candles]
        volumes = [c.volume for c in candles]
        
        indicators = {}
        
        # RSI
        indicators['rsi'] = TechnicalAnalysis.calculate_rsi(close_prices)
        
        # Bollinger Bands
        indicators['bb_upper'], indicators['bb_middle'], indicators['bb_lower'] = \
            TechnicalAnalysis.calculate_bollinger_bands(close_prices)
        
        # MACD
        indicators['macd'], indicators['macd_signal'], indicators['macd_hist'] = \
            TechnicalAnalysis.calculate_macd(close_prices)
        
        # Stochastic
        indicators['stoch_k'], indicators['stoch_d'] = \
            TechnicalAnalysis.calculate_stochastic(high_prices, low_prices, close_prices)
        
        # EMAs
        indicators['ema_fast'] = TechnicalAnalysis.calculate_ema(close_prices, 9)
        indicators['ema_slow'] = TechnicalAnalysis.calculate_ema(close_prices, 21)
        
        # Soporte y Resistencia
        supports, resistances = TechnicalAnalysis.find_support_resistance(close_prices)
        indicators['supports'] = supports
        indicators['resistances'] = resistances
        
        # Analizar según la estrategia
        signal = None
        
        if strategy == Strategy.SUPPORT_RESISTANCE:
            signal = self._analyze_support_resistance(candles[-1], indicators)
        elif strategy == Strategy.TREND_FOLLOWING:
            signal = self._analyze_trend_following(candles[-1], indicators)
        elif strategy == Strategy.BOLLINGER_BOUNCE:
            signal = self._analyze_bollinger_bounce(candles[-1], indicators)
        elif strategy == Strategy.RSI_DIVERGENCE:
            signal = self._analyze_rsi_divergence(candles, indicators)
        elif strategy == Strategy.MACD_CROSS:
            signal = self._analyze_macd_cross(candles[-1], indicators)
        elif strategy == Strategy.BREAKOUT:
            signal = self._analyze_breakout(candles, indicators)
        elif strategy == Strategy.MOMENTUM_SCALPING:
            signal = self._analyze_momentum(candles, indicators)
        
        if signal:
            signal['strategy'] = strategy
            signal['timeframe'] = timeframe
            signal['indicators_data'] = indicators
            signal['confidence'] = self._calculate_signal_confidence(signal, indicators)
            
            # Solo retornar si supera el umbral de confianza
            if signal['confidence'] >= config['min_confidence']:
                return signal
        
        return None
    
    def _analyze_support_resistance(self, candle: MarketData, indicators: Dict) -> Optional[Dict]:
        """Analiza señales basadas en soporte y resistencia"""
        current_price = candle.close
        supports = indicators.get('supports', [])
        resistances = indicators.get('resistances', [])
        
        if not supports or not resistances:
            return None
        
        # Buscar rebote en soporte
        for support in supports:
            if abs(current_price - support) / support < 0.002:  # Dentro del 0.2%
                if indicators.get('rsi', 50) < 40:  # RSI oversold
                    return {
                        'direction': 'call',
                        'reason': f'Rebote en soporte {support:.5f}',
                        'entry_price': current_price
                    }
        
        # Buscar rebote en resistencia
        for resistance in resistances:
            if abs(current_price - resistance) / resistance < 0.002:
                if indicators.get('rsi', 50) > 60:  # RSI overbought
                    return {
                        'direction': 'put',
                        'reason': f'Rebote en resistencia {resistance:.5f}',
                        'entry_price': current_price
                    }
        
        return None
    
    def _analyze_trend_following(self, candle: MarketData, indicators: Dict) -> Optional[Dict]:
        """Analiza señales de seguimiento de tendencia"""
        ema_fast = indicators.get('ema_fast')
        ema_slow = indicators.get('ema_slow')
        macd_hist = indicators.get('macd_hist')
        
        if not all([ema_fast, ema_slow, macd_hist]):
            return None
        
        # Tendencia alcista
        if ema_fast > ema_slow and macd_hist > 0:
            if candle.close > ema_fast:  # Precio sobre EMA rápida
                return {
                    'direction': 'call',
                    'reason': 'Tendencia alcista confirmada',
                    'entry_price': candle.close
                }
        
        # Tendencia bajista
        elif ema_fast < ema_slow and macd_hist < 0:
            if candle.close < ema_fast:  # Precio bajo EMA rápida
                return {
                    'direction': 'put',
                    'reason': 'Tendencia bajista confirmada',
                    'entry_price': candle.close
                }
        
        return None
    
    def _analyze_bollinger_bounce(self, candle: MarketData, indicators: Dict) -> Optional[Dict]:
        """Analiza rebotes en Bandas de Bollinger"""
        bb_upper = indicators.get('bb_upper')
        bb_lower = indicators.get('bb_lower')
        rsi = indicators.get('rsi', 50)
        stoch_k = indicators.get('stoch_k', 50)
        
        if not all([bb_upper, bb_lower]):
            return None
        
        # Rebote en banda inferior
        if candle.close <= bb_lower and rsi < 30 and stoch_k < 20:
            return {
                'direction': 'call',
                'reason': 'Rebote en Bollinger inferior + RSI/Stoch oversold',
                'entry_price': candle.close
            }
        
        # Rebote en banda superior
        elif candle.close >= bb_upper and rsi > 70 and stoch_k > 80:
            return {
                'direction': 'put',
                'reason': 'Rebote en Bollinger superior + RSI/Stoch overbought',
                'entry_price': candle.close
            }
        
        return None
    
    def _analyze_rsi_divergence(self, candles: List[MarketData], indicators: Dict) -> Optional[Dict]:
        """Analiza divergencias del RSI"""
        if len(candles) < 20:
            return None
        
        # Implementación simplificada de detección de divergencias
        # En producción, esto sería más sofisticado
        current_rsi = indicators.get('rsi', 50)
        
        # Divergencia alcista: precio hace mínimos más bajos, RSI hace mínimos más altos
        if current_rsi < 35:
            return {
                'direction': 'call',
                'reason': 'Posible divergencia alcista RSI',
                'entry_price': candles[-1].close
            }
        
        # Divergencia bajista: precio hace máximos más altos, RSI hace máximos más bajos  
        elif current_rsi > 65:
            return {
                'direction': 'put',
                'reason': 'Posible divergencia bajista RSI',
                'entry_price': candles[-1].close
            }
        
        return None
    
    def _analyze_macd_cross(self, candle: MarketData, indicators: Dict) -> Optional[Dict]:
        """Analiza cruces del MACD"""
        macd = indicators.get('macd')
        macd_signal = indicators.get('macd_signal')
        macd_hist = indicators.get('macd_hist')
        
        if not all([macd is not None, macd_signal is not None, macd_hist is not None]):
            return None
        
        # Cruce alcista
        if macd > macd_signal and macd_hist > 0 and abs(macd_hist) > 0.00001:
            return {
                'direction': 'call',
                'reason': 'Cruce alcista MACD',
                'entry_price': candle.close
            }
        
        # Cruce bajista
        elif macd < macd_signal and macd_hist < 0 and abs(macd_hist) > 0.00001:
            return {
                'direction': 'put',
                'reason': 'Cruce bajista MACD',
                'entry_price': candle.close
            }
        
        return None
    
    def _analyze_breakout(self, candles: List[MarketData], indicators: Dict) -> Optional[Dict]:
        """Analiza rupturas de rangos"""
        if len(candles) < 20:
            return None
        
        # Detectar rango de consolidación
        recent_highs = [c.high for c in candles[-20:]]
        recent_lows = [c.low for c in candles[-20:]]
        
        range_high = max(recent_highs[:-1])  # Excluir última vela
        range_low = min(recent_lows[:-1])
        
        current_candle = candles[-1]
        
        # Ruptura alcista
        if current_candle.close > range_high and current_candle.volume > np.mean([c.volume for c in candles[-20:]]) * 1.5:
            return {
                'direction': 'call',
                'reason': f'Ruptura alcista de {range_high:.5f}',
                'entry_price': current_candle.close
            }
        
        # Ruptura bajista
        elif current_candle.close < range_low and current_candle.volume > np.mean([c.volume for c in candles[-20:]]) * 1.5:
            return {
                'direction': 'put',
                'reason': f'Ruptura bajista de {range_low:.5f}',
                'entry_price': current_candle.close
            }
        
        return None
    
    def _analyze_momentum(self, candles: List[MarketData], indicators: Dict) -> Optional[Dict]:
        """Analiza momentum del mercado para scalping"""
        if len(candles) < 10:
            return None
        
        # Calcular momentum
        momentum = (candles[-1].close - candles[-5].close) / candles[-5].close * 100
        
        # Volumen creciente
        recent_volume = np.mean([c.volume for c in candles[-5:]])
        prev_volume = np.mean([c.volume for c in candles[-10:-5]])
        volume_increase = recent_volume > prev_volume * 1.2
        
        # Momentum alcista fuerte
        if momentum > 0.1 and volume_increase and indicators.get('rsi', 50) > 55:
            return {
                'direction': 'call',
                'reason': 'Momentum alcista fuerte',
                'entry_price': candles[-1].close
            }
        
        # Momentum bajista fuerte
        elif momentum < -0.1 and volume_increase and indicators.get('rsi', 50) < 45:
            return {
                'direction': 'put',
                'reason': 'Momentum bajista fuerte',
                'entry_price': candles[-1].close
            }
        
        return None
    
    def _calculate_signal_confidence(self, signal: Dict, indicators: Dict) -> float:
        """Calcula la confianza de una señal"""
        confidence = 50.0  # Base
        
        # Ajustar por dirección y indicadores
        if signal['direction'] == 'call':
            if indicators.get('rsi', 50) < 40:
                confidence += 10
            if indicators.get('stoch_k', 50) < 30:
                confidence += 5
            if indicators.get('macd_hist', 0) > 0:
                confidence += 10
        else:  # put
            if indicators.get('rsi', 50) > 60:
                confidence += 10
            if indicators.get('stoch_k', 50) > 70:
                confidence += 5
            if indicators.get('macd_hist', 0) < 0:
                confidence += 10
        
        # Ajustar por volatilidad
        if 'bb_upper' in indicators and 'bb_lower' in indicators:
            bb_width = (indicators['bb_upper'] - indicators['bb_lower']) / indicators.get('bb_middle', 1)
            if bb_width < 0.01:  # Baja volatilidad
                confidence -= 5
            elif bb_width > 0.02:  # Alta volatilidad
                confidence += 5
        
        return min(max(confidence, 0), 100)
    
    def _filter_signals(self, signals: List[Dict]) -> Optional[Dict]:
        """Filtra y selecciona la mejor señal"""
        if not signals:
            return None
        
        # Verificar tiempo desde última operación
        if self.last_trade_time:
            time_since_last = (datetime.datetime.now() - self.last_trade_time).total_seconds()
            if time_since_last < self.min_time_between_trades:
                return None
        
        # Ordenar por confianza
        signals.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Retornar la señal con mayor confianza
        return signals[0]
    
    def _execute_trade(self, signal: Dict):
        """Ejecuta una operación"""
        try:
            # Calcular tamaño de posición
            position_size = self.risk_manager.calculate_position_size(
                confidence=signal['confidence'],
                money_management=self.money_management,
                consecutive_losses=self.session.consecutive_losses,
                win_rate=self.session.win_rate / 100
            )
            
            if position_size <= 0:
                logger.warning("Tamaño de posición calculado es 0, omitiendo trade")
                return
            
            # Crear trade
            trade = Trade(
                id=f"{self.email}_{datetime.datetime.now().timestamp()}",
                symbol=self.symbol,
                direction=signal['direction'],
                amount=position_size,
                entry_price=signal['entry_price'],
                entry_time=datetime.datetime.now(),
                expiry_time=5,  # 5 minutos por defecto
                strategy=signal['strategy'],
                confidence=signal['confidence'],
                indicators_data=signal['indicators_data']
            )
            
            # Ejecutar en IQ Option
            success = False
            if IQ_AVAILABLE and self.iq_api:
                try:
                    # Cambiar a cuenta real o práctica según configuración
                    account_type = self.config.get('account_type', 'PRACTICE')
                    self.iq_api.change_balance(account_type)
                    
                    # Ejecutar operación
                    check, trade_id = self.iq_api.buy(
                        position_size,
                        self.symbol,
                        signal['direction'],
                        5  # 5 minutos
                    )
                    
                    if check:
                        trade.id = str(trade_id)
                        success = True
                        logger.info(f"✅ Trade ejecutado: {trade.id}")
                except Exception as e:
                    logger.error(f"Error ejecutando trade en IQ Option: {e}")
            else:
                # Modo simulación
                success = True
                logger.info(f"📊 Trade simulado: {trade.id}")
            
            if success:
                self.session.trades.append(trade)
                self.last_trade_time = datetime.datetime.now()
                
                # Notificar
                self._send_trade_notification(trade, "ABIERTO")
                
                # Emitir evento al frontend
                self._emit_trade_event(trade, "open")
                
                # Programar verificación del resultado
                Timer(310, self._check_trade_result, args=[trade]).start()  # 5 min + 10 seg
                
        except Exception as e:
            logger.error(f"Error ejecutando trade: {e}")
    
    def _check_trade_result(self, trade: Trade):
        """Verifica el resultado de un trade"""
        try:
            if IQ_AVAILABLE and self.iq_api:
                # Obtener resultado real
                result = self.iq_api.check_win_v3(trade.id)
                
                if result is not None:
                    if result > 0:
                        trade.result = "win"
                        trade.profit = result
                    elif result < 0:
                        trade.result = "loss"
                        trade.profit = result
                    else:
                        trade.result = "draw"
                        trade.profit = 0
            else:
                # Simulación con probabilidad basada en win rate esperado
                strategy_config = STRATEGY_CONFIG[trade.strategy]
                win_rate = strategy_config['expected_win_rate'] / 100
                
                if np.random.random() < win_rate:
                    trade.result = "win"
                    trade.profit = trade.amount * 0.85  # 85% payout
                else:
                    trade.result = "loss"
                    trade.profit = -trade.amount
            
            # Actualizar sesión
            self.session.add_trade(trade)
            
            # Actualizar balance del risk manager
            self.risk_manager.update_balance(trade.profit)
            
            # Notificar resultado
            self._send_trade_notification(trade, "CERRADO")
            
            # Emitir evento al frontend
            self._emit_trade_event(trade, "close")
            
        except Exception as e:
            logger.error(f"Error verificando resultado del trade: {e}")
    
    def _check_open_trades(self):
        """Verifica trades abiertos (para futuras implementaciones)"""
        pass
    
    def _get_current_candle(self) -> Optional[Dict]:
        """Obtiene la vela actual para enviar al frontend"""
        if 60 in self.candles_data and self.candles_data[60]:
            candle = self.candles_data[60][-1]
            return {
                'time': candle.timestamp.timestamp() * 1000,  # Timestamp en ms
                'open': candle.open,
                'high': candle.high,
                'low': candle.low,
                'close': candle.close,
                'volume': candle.volume
            }
        return None
    
    def _emit_trade_event(self, trade: Trade, event_type: str):
        """Emite evento de trade al frontend"""
        try:
            trade_data = {
                'id': trade.id,
                'symbol': trade.symbol,
                'direction': trade.direction,
                'amount': trade.amount,
                'entry_price': trade.entry_price,
                'entry_time': trade.entry_time.isoformat(),
                'strategy': trade.strategy.value,
                'confidence': trade.confidence,
                'result': trade.result,
                'profit': trade.profit,
                'event_type': event_type
            }
            
            socketio.emit('trade_update', trade_data, room=self.email)
        except Exception as e:
            logger.error(f"Error emitiendo evento de trade: {e}")
    
    def _send_telegram_notification(self, message: str):
        """Envía notificación a Telegram"""
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
                    logger.error(f"Error enviando Telegram: {response.text}")
                    
            except Exception as e:
                logger.error(f"Error en notificación Telegram: {e}")
        
        executor.submit(send)
    
    def _send_trade_notification(self, trade: Trade, status: str):
        """Envía notificación de trade"""
        emoji = "🟢" if status == "ABIERTO" else ("✅" if trade.result == "win" else "❌")
        
        message = f"{emoji} *TRADE {status}*\n"
        message += f"📈 Estrategia: {trade.strategy.value}\n"
        message += f"🎯 Dirección: {trade.direction.upper()}\n"
        message += f"💰 Monto: ${trade.amount:.2f}\n"
        message += f"📍 Precio: {trade.entry_price:.5f}\n"
        
        if status == "CERRADO" and trade.profit is not None:
            profit_sign = '+' if trade.profit >= 0 else ''
            message += f"💵 Resultado: {profit_sign}${trade.profit:.2f}\n"
            message += f"📊 Balance: ${self.session.current_balance:.2f}\n"
            message += f"🎯 Win Rate: {self.session.win_rate:.1f}%"
        
        self._send_telegram_notification(message)
    
    def _send_final_report(self):
        """Envía reporte final de la sesión"""
        duration = (self.session.end_time - self.session.start_time).total_seconds() / 3600
        
        message = f"📊 *REPORTE FINAL DE SESIÓN*\n\n"
        message += f"⏱ Duración: {duration:.1f} horas\n"
        message += f"📈 Total trades: {self.session.total_trades}\n"
        message += f"✅ Ganadas: {self.session.winning_trades}\n"
        message += f"❌ Perdidas: {self.session.losing_trades}\n"
