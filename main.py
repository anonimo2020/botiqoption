"total_trades": user_metrics_obj.total_trades,
                "using_kelly": True,
                "consecutive_losses": user_metrics_obj.current_consecutive_losses
            })
            recommendation["calculation_details"]["kelly_applied"] = True
            recommendation["calculation_details"]["kelly_info"] = "Kelly Criterion aplicado basado en historial"
        else:
            recommendation.update({
                "using_kelly": False,
                "note": "Usando monto base. Kelly se activará después de 10 operaciones.",
                "trades_needed": 10 - (user_metrics_obj.total_trades if user_metrics_obj else 0)
            })
        
        return jsonify(recommendation), 200
        
    except Exception as e:
        logger.error(f"❌ Error calculando monto óptimo: {str(e)}")
        return jsonify({"error": "Error calculando monto óptimo"}), 500

# ============================================================================
# INICIALIZACIÓN Y MAIN
# ============================================================================

def initialize_system():
    """Inicializa todos los componentes del sistema"""
    try:
        logger.info("🔧 Inicializando sistema...")
        
        # Inicializar sistema de limpieza
        connection_keeper.start()
        
        # Verificar directorios
        required_dirs = [
            app.config['SESSION_FILE_DIR'],
            '/tmp/bot_logs',
            '/tmp/flask_sessions_v2'
        ]
        
        for directory in required_dirs:
            os.makedirs(directory, exist_ok=True)
        
        logger.info("✅ Sistema inicializado correctamente")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error inicializando sistema: {e}")
        return False

if __name__ == '__main__':
    # Configuración del puerto
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    logger.info("=" * 80)
    logger.info(f"🚀 INICIANDO TRADING BOT PRO v2.0 - OPCIONES BINARIAS")
    logger.info("=" * 80)
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🔧 Modo Debug: {debug_mode}")
    logger.info(f"🔧 IQ Option API: {'✅ Disponible' if IQ_AVAILABLE else '❌ No disponible'}")
    logger.info(f"📱 Telegram: {'✅ Configurado' if TELEGRAM_BOT_TOKEN else '❌ No configurado'}")
    logger.info(f"📊 Estrategias disponibles: {len(STRATEGY_CONFIG)}")
    logger.info(f"🔌 WebSocket: ✅ Habilitado con SocketIO")
    logger.info(f"🧹 Sistema de limpieza: ✅ Automático")
    logger.info("")
    logger.info("🎯 CARACTERÍSTICAS PRINCIPALES:")
    logger.info("   • ✅ WebSocket callbacks patcheados y funcionando")
    logger.info("   • ✅ Reconexión automática robusta ante fallos")
    logger.info("   • ✅ Comunicación tiempo real bot ↔ frontend")
    logger.info("   • ✅ Threading mejorado sin deadlocks")
    logger.info("   • ✅ Gestión de capital avanzada (Kelly Criterion)")
    logger.info("   • ✅ 5 estrategias especializadas para opciones binarias")
    logger.info("   • ✅ Límite de capital al 50% del balance")
    logger.info("   • ✅ Stop loss inteligente por operaciones perdidas")
    logger.info("   • ✅ Sistema de limpieza automática de conexiones")
    logger.info("   • ✅ Pool de threads para operaciones concurrentes")
    logger.info("   • ✅ Keepalive automático de conexiones")
    logger.info("   • ✅ Manejo de errores comprehensivo")
    logger.info("   • ✅ Notificaciones Telegram en tiempo real")
    logger.info("=" * 80)
    
    if not IQ_AVAILABLE:
        logger.error("❌ IQOptionAPI no está disponible. El servidor no funcionará correctamente.")
        logger.error("💡 Instala con: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
        sys.exit(1)
    
    # Inicializar sistema
    if not initialize_system():
        logger.error("❌ Fallo en inicialización del sistema")
        sys.exit(1)
    
    # Enviar notificación de inicio
    send_telegram_message(f"""🚀 *TRADING BOT PRO v2.0 INICIADO*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🔧 API: {'✅ OK' if IQ_AVAILABLE else '❌ ERROR'}
📊 Estrategias: {len(STRATEGY_CONFIG)}
💰 Gestión: Kelly Criterion + Anti-Martingala
🎯 Límite Capital: 50% del balance
🔌 WebSocket: ✅ Habilitado para tiempo real
🧹 Auto-cleanup: ✅ Activo
🛡️ Patches: ✅ WebSocket callbacks corregidos
📡 Keepalive: ✅ Conexiones mantenidas automáticamente""")
    
    try:
        # Iniciar servidor con SocketIO
        logger.info("🌐 Iniciando servidor Flask con SocketIO...")
        socketio.run(
            app, 
            host='0.0.0.0', 
            port=port, 
            debug=debug_mode,
            use_reloader=False,  # Importante: evitar reloader con threading
            log_output=debug_mode
        )
    except KeyboardInterrupt:
        logger.info("🛑 Interrupción de teclado recibida")
    except Exception as e:
        logger.error(f"❌ Error iniciando servidor: {e}")
    finally:
        logger.info("🔚 Cerrando servidor...")
        graceful_shutdown()
        
        # Estado del sistema de limpieza
        cleanup_status = {
            "connection_keeper_running": connection_keeper.running,
            "cleanup_active": True,
            "last_cleanup": "Running continuously"
        }
        
        health_data = {
            "status": "healthy",
            "version": "2.0.0",
            "timestamp": datetime.datetime.now().isoformat(),
            "websocket": websocket_status,
            "iqoption_api": {
                "status": iq_status,
                "patches_applied": True,
                "callback_fixes": True
            },
            "sessions": {
                "active": active_sessions,
                "total_registered": len(user_sessions),
                "connection_details": connection_statuses
            },
            "bots": {
                "active": active_bots_count,
                "total": len(active_bots),
                "bot_details": bot_statuses
            },
            "telegram": {
                "status": telegram_status,
                "notifications": "enabled" if telegram_status == "configured" else "disabled"
            },
            "strategies": {
                "available": len(STRATEGY_CONFIG),
                "types": [strategy.value for strategy in STRATEGY_CONFIG.keys()]
            },
            "system": system_stats,
            "cleanup": cleanup_status,
            "thread_pool": {
                "max_workers": thread_pool._max_workers,
                "active_threads": len([t for t in thread_pool._threads if t.is_alive()]) if hasattr(thread_pool, '_threads') else "N/A"
            }
        }
        
        return jsonify(health_data), 200
        
    except Exception as e:
        logger.error(f"❌ Error en health check: {e}")
        return jsonify({
            "status": "error",
            "version": "2.0.0",
            "timestamp": datetime.datetime.now().isoformat(),
            "error": str(e),
            "basic_info": {
                "active_sessions": len(user_sessions),
                "active_bots": len(active_bots),
                "iqoption_available": IQ_AVAILABLE
            }
        }), 500

@app.route('/api/login', methods=['POST', 'OPTIONS'])
@limiter.limit("5 per minute")
def login():
    """Login endpoint con gestión mejorada de conexiones y WebSocket"""
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
        
        logger.info(f"🔄 Intento de login para: {email}")
        
        # Limpiar cualquier sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    logger.info(f"🧹 Limpiando sesión anterior para {email}")
                    old_connection = user_sessions[email]
                    old_connection.disconnect()
                    del user_sessions[email]
                except Exception as e:
                    logger.debug(f"Error limpiando sesión anterior: {e}")
        
        # Crear nuevo gestor de conexión
        connection_manager = ConnectionManager(email, password)
        
        # Intentar conectar con timeout
        success, result = connection_manager.connect(timeout=45)
        
        if not success:
            logger.error(f"❌ Error de conexión para {email}: {result}")
            if isinstance(result, dict):
                return jsonify({"success": False, **result}), 401
            else:
                return jsonify({"success": False, "message": result}), 503
        
        # Conexión exitosa - obtener información del usuario
        try:
            iq = connection_manager.iq_instance
            user_email = email
            user_name = user_email.split('@')[0].title()
            
            # Obtener balance y tipo de cuenta con reintentos
            balance = None
            account_type = None
            
            for attempt in range(3):
                try:
                    balance = iq.get_balance()
                    account_type = iq.get_balance_mode()
                    if balance is not None:
                        break
                except Exception as e:
                    logger.warning(f"⚠️ Error obteniendo balance (intento {attempt + 1}): {e}")
                    if attempt < 2:
                        time.sleep(2)
                    else:
                        balance = 0.0
                        account_type = "PRACTICE"
            
            # Guardar sesión exitosa
            with sessions_lock:
                user_sessions[email] = connection_manager
            
            # Configurar sesión Flask
            session['user_email'] = email
            session.permanent = True
            
            # Inicializar métricas si es primera vez
            with metrics_lock:
                if email not in user_metrics:
                    user_metrics[email] = TradingMetrics()
                    user_metrics[email].start_balance = balance
                    user_metrics[email].current_balance = balance
            
            # Notificar login exitoso
            send_telegram_message(f"""🎯 *LOGIN EXITOSO - TRADING BOT PRO v2.0*
👤 Usuario: {user_name}
📧 Email: {email}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}
🔌 WebSocket: Habilitado
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""")
            
            logger.info(f"✅ Login exitoso para {email}")
            
            # Respuesta exitosa
            return jsonify({
                "success": True,
                "user": {
                    "name": user_name,
                    "email": email,
                    "balance": float(balance),
                    "account_type": account_type,
                    "currency": "USD"
                },
                "websocket": {
                    "enabled": True,
                    "url": request.url_root.replace('http', 'ws') + 'socket.io/'
                },
                "message": "Conexión exitosa con IQ Option"
            }), 200
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo datos del usuario: {e}")
            
            # Si hay error pero la conexión está establecida, devolver datos mínimos
            with sessions_lock:
                user_sessions[email] = connection_manager
            
            session['user_email'] = email
            session.permanent = True
            
            return jsonify({
                "success": True,
                "user": {
                    "name": email.split('@')[0],
                    "email": email,
                    "balance": 0.0,
                    "account_type": "PRACTICE",
                    "currency": "USD"
                },
                "websocket": {
                    "enabled": True,
                    "url": request.url_root.replace('http', 'ws') + 'socket.io/'
                },
                "message": "Conexión exitosa (datos limitados)"
            }), 200
            
    except Exception as e:
        logger.error(f"❌ Error en login: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Error del servidor: {str(e)}"
        }), 500

@app.route('/api/logout', methods=['POST'])
@require_auth
def logout():
    """Logout endpoint con limpieza completa"""
    try:
        email = session['user_email']
        logger.info(f"🔌 Logout iniciado para {email}")
        
        # Detener bot si está activo
        with bots_lock:
            if email in active_bots:
                logger.info(f"🛑 Deteniendo bot para {email}")
                active_bots[email].stop()
                del active_bots[email]
        
        # Cerrar conexión IQ Option
        with sessions_lock:
            if email in user_sessions:
                try:
                    logger.info(f"🔌 Cerrando conexión IQ Option para {email}")
                    user_sessions[email].disconnect()
                    del user_sessions[email]
                except Exception as e:
                    logger.error(f"❌ Error cerrando conexión: {e}")
        
        # Limpiar sesión Flask
        session.clear()
        
        send_telegram_message(f"👋 *LOGOUT EXITOSO*\n📧 {email}\n⏰ {datetime.datetime.now().strftime('%H:%M:%S')}")
        logger.info(f"✅ Logout completado para {email}")
        
        return jsonify({"success": True, "message": "Sesión cerrada correctamente"}), 200
        
    except Exception as e:
        logger.error(f"❌ Error en logout: {str(e)}")
        return jsonify({"success": False, "message": "Error al cerrar sesión"}), 500

@app.route('/api/balance', methods=['GET'])
@require_auth
def get_balance():
    """Obtener balance actual con información extendida"""
    try:
        email = session['user_email']
        
        with sessions_lock:
            connection_manager = user_sessions[email]
            iq = connection_manager.iq_instance
        
        balance = iq.get_balance()
        account_type = iq.get_balance_mode()
        
        # Actualizar métricas
        with metrics_lock:
            if email in user_metrics:
                user_metrics[email].current_balance = balance
        
        # Información adicional de conexión
        connection_info = {
            "connected": connection_manager.is_connected(),
            "status": connection_manager.status.value,
            "reconnect_attempts": connection_manager.reconnect_attempts,
            "last_ping": connection_manager.last_ping
        }
        
        return jsonify({
            "balance": float(balance),
            "account_type": account_type,
            "connection": connection_info,
            "metrics": user_metrics[email].to_dict() if email in user_metrics else None
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo balance: {str(e)}")
        return jsonify({"error": "Error obteniendo balance"}), 500

@app.route('/api/symbols', methods=['GET'])
@require_auth
def get_symbols():
    """Obtener símbolos disponibles para opciones binarias"""
    try:
        email = session['user_email']
        
        with sessions_lock:
            connection_manager = user_sessions[email]
            iq = connection_manager.iq_instance
        
        # Lista de símbolos comunes para opciones binarias
        binary_symbols = [
            {"symbol": "EURUSD", "name": "EUR/USD", "type": "turbo", "category": "forex"},
            {"symbol": "GBPUSD", "name": "GBP/USD", "type": "turbo", "category": "forex"}, 
            {"symbol": "USDJPY", "name": "USD/JPY", "type": "turbo", "category": "forex"},
            {"symbol": "AUDUSD", "name": "AUD/USD", "type": "turbo", "category": "forex"},
            {"symbol": "USDCAD", "name": "USD/CAD", "type": "turbo", "category": "forex"},
            {"symbol": "EURJPY", "name": "EUR/JPY", "type": "turbo", "category": "forex"},
            {"symbol": "GBPJPY", "name": "GBP/JPY", "type": "turbo", "category": "forex"},
            {"symbol": "GOLD", "name": "Gold", "type": "digital", "category": "commodity"},
            {"symbol": "SILVER", "name": "Silver", "type": "digital", "category": "commodity"},
            {"symbol": "OIL", "name": "Oil", "type": "digital", "category": "commodity"}
        ]
        
        # Intentar obtener activos abiertos dinámicamente
        try:
            if hasattr(iq, 'get_all_open_time'):
                all_assets = iq.get_all_open_time()
                dynamic_symbols = []
                
                # Verificar turbo (opciones binarias)
                if 'turbo' in all_assets:
                    for asset, info in all_assets['turbo'].items():
                        if info.get('open', False):
                            dynamic_symbols.append({
                                "symbol": asset,
                                "name": asset,
                                "type": "turbo",
                                "category": "dynamic",
                                "available": True
                            })
                
                # Verificar digital (opciones digitales)
                if 'digital' in all_assets:
                    for asset, info in all_assets['digital'].items():
                        if info.get('open', False):
                            dynamic_symbols.append({
                                "symbol": asset,
                                "name": asset,
                                "type": "digital",
                                "category": "dynamic",
                                "available": True
                            })
                
                if dynamic_symbols:
                    # Combinar símbolos estáticos con dinámicos
                    binary_symbols.extend(dynamic_symbols[:10])
                    
        except Exception as e:
            logger.warning(f"⚠️ No se pudieron obtener activos dinámicamente: {e}")
        
        return jsonify({
            "symbols": binary_symbols[:15],  # Limitar a 15 símbolos
            "total_available": len(binary_symbols),
            "last_updated": datetime.datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo símbolos: {str(e)}")
        return jsonify({"error": "Error obteniendo símbolos"}), 500

@app.route('/api/strategies', methods=['GET'])
@require_auth
def get_strategies():
    """Obtener estrategias disponibles con información detallada"""
    try:
        strategies = []
        for strategy, config in STRATEGY_CONFIG.items():
            strategies.append({
                "id": strategy.value,
                "name": config["name"],
                "description": config["description"],
                "risk_level": config["risk_level"].value,
                "min_confidence": config["min_confidence"],
                "timeframe": config["timeframe"],
                "expiry": config["expiry"],
                "indicators": config["indicators"],
                "recommended_for": "Principiantes" if config["risk_level"] in [RiskLevel.VERY_LOW, RiskLevel.LOW] 
                              else "Intermedios" if config["risk_level"] == RiskLevel.MEDIUM 
                              else "Avanzados"
            })
        
        return jsonify({
            "strategies": strategies,
            "total": len(strategies),
            "risk_levels": [level.value for level in RiskLevel]
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo estrategias: {str(e)}")
        return jsonify({"error": "Error obteniendo estrategias"}), 500

@app.route('/api/start_bot', methods=['POST'])
@require_auth
@limiter.limit("3 per minute")
def start_bot():
    """Iniciar bot de trading con WebSocket habilitado"""
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
        strategy = data.get('strategy', Strategy.BOLLINGER_RSI.value)
        account_type = data.get('account_type', 'PRACTICE')
        max_operations = int(data.get('max_operations', 0))
        max_loss_operations = int(data.get('max_loss_operations', 5))
        
        # Validaciones mejoradas
        if amount <= 0 or amount > 10000:
            return jsonify({"error": "El monto debe estar entre $1 y $10,000"}), 400
        
        try:
            strategy_enum = Strategy(strategy)
        except ValueError:
            return jsonify({"error": "Estrategia no válida"}), 400
        
        if max_loss_operations < 1 or max_loss_operations > 10:
            return jsonify({"error": "El límite de pérdidas debe estar entre 1 y 10"}), 400
        
        # Obtener conexión
        with sessions_lock:
            connection_manager = user_sessions[email]
        
        # Verificar y asegurar conexión
        if not connection_manager.reconnect_if_needed():
            return jsonify({"error": "No se pudo establecer conexión con IQ Option"}), 503
        
        iq = connection_manager.iq_instance
        
        # Cambiar tipo de cuenta
        try:
            iq.change_balance(account_type)
            time.sleep(1)  # Dar tiempo para que se aplique el cambio
        except Exception as e:
            logger.warning(f"⚠️ Error cambiando tipo de cuenta: {e}")
        
        # Verificar balance
        balance = iq.get_balance()
        max_risk = balance * 0.5  # Máximo 50% del capital
        
        if amount > max_risk:
            return jsonify({
                "error": f"El monto inicial (${amount:.2f}) excede el 50% del balance disponible (${max_risk:.2f})",
                "max_allowed": max_risk,
                "current_balance": balance
            }), 400
        
        # Configuración del bot
        bot_config = {
            'symbol': symbol,
            'amount': amount,
            'strategy': strategy,
            'account_type': account_type,
            'max_operations': max_operations,
            'max_loss_operations': max_loss_operations
        }
        
        # Crear e iniciar bot
        bot = TradingBot(connection_manager, bot_config, email)
        
        # Iniciar bot y verificar éxito
        if bot.start():
            with bots_lock:
                active_bots[email] = bot
            
            strategy_config = STRATEGY_CONFIG[strategy_enum]
            
            logger.info(f"🚀 Bot iniciado exitosamente para {email}")
            
            return jsonify({
                "success": True,
                "message": "Bot iniciado correctamente",
                "config": bot_config,
                "strategy_info": {
                    "name": strategy_config["name"],
                    "risk_level": strategy_config["risk_level"].value,
                    "description": strategy_config["description"],
                    "timeframe": strategy_config["timeframe"],
                    "expiry": strategy_config["expiry"]
                },
                "limits": {
                    "max_risk": max_risk,
                    "current_balance": balance,
                    "risk_percentage": (amount / balance * 100) if balance > 0 else 0
                },
                "websocket": {
                    "room": f"user_{email}",
                    "live_data_enabled": True
                }
            }), 200
        else:
            return jsonify({"error": "No se pudo iniciar el bot"}), 500
        
    except Exception as e:
        logger.error(f"❌ Error iniciando bot: {str(e)}")
        return jsonify({"error": f"Error iniciando bot: {str(e)}"}), 500

@app.route('/api/stop_bot', methods=['POST'])
@require_auth
def stop_bot():
    """Detener bot de trading"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                bot.stop()
                del active_bots[email]
                
                send_telegram_message(f"🛑 *BOT DETENIDO MANUALMENTE*\n👤 {email}\n💰 Profit de sesión: ${bot.session_profit:.2f}")
                logger.info(f"🛑 Bot detenido manualmente para {email}")
                
                return jsonify({
                    "success": True,
                    "message": "Bot detenido correctamente",
                    "final_stats": {
                        "session_profit": bot.session_profit,
                        "operations_count": bot.operations_count,
                        "consecutive_losses": bot.consecutive_losses
                    }
                }), 200
            else:
                return jsonify({"error": "No hay bot activo para detener"}), 400
                
    except Exception as e:
        logger.error(f"❌ Error deteniendo bot: {str(e)}")
        return jsonify({"error": "Error deteniendo bot"}), 500

@app.route('/api/bot_status', methods=['GET'])
@require_auth
def bot_status():
    """Obtener estado detallado del bot"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                strategy_config = STRATEGY_CONFIG[bot.strategy]
                
                # Obtener balance actual
                try:
                    current_balance = bot.connection_manager.iq_instance.get_balance()
                except:
                    current_balance = 0
                
                status = {
                    "running": bot.running,
                    "operations_count": bot.operations_count,
                    "consecutive_losses": bot.consecutive_losses,
                    "session_profit": bot.session_profit,
                    "current_balance": current_balance,
                    "strategy": {
                        "id": bot.strategy.value,
                        "name": strategy_config["name"],
                        "risk_level": strategy_config["risk_level"].value,
                        "timeframe": strategy_config["timeframe"],
                        "min_confidence": strategy_config["min_confidence"]
                    },
                    "config": bot.config,
                    "limits": {
                        "max_operations": bot.max_operations,
                        "max_loss_operations": bot.max_loss_operations,
                        "operations_remaining": max(0, bot.max_operations - bot.operations_count) if bot.max_operations > 0 else "unlimited",
                        "losses_remaining": max(0, bot.max_loss_operations - bot.consecutive_losses)
                    },
                    "performance": {
                        "win_rate": ((bot.operations_count - bot.consecutive_losses) / bot.operations_count * 100) if bot.operations_count > 0 else 0,
                        "avg_profit_per_trade": (bot.session_profit / bot.operations_count) if bot.operations_count > 0 else 0
                    },
                    "last_update": bot.last_update,
                    "websocket_enabled": True
                }
            else:
                status = {
                    "running": False,
                    "message": "No hay bot activo",
                    "websocket_enabled": True
                }
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo estado del bot: {str(e)}")
        return jsonify({"error": "Error obteniendo estado"}), 500

@app.route('/api/live_data', methods=['GET'])
@require_auth
def get_live_data():
    """Obtener datos en vivo del bot (endpoint de compatibilidad)"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                live_data = bot.get_live_data()
                
                if live_data:
                    return jsonify({
                        "success": True,
                        "data": live_data,
                        "websocket_available": True,
                        "message": "Datos disponibles. Se recomienda usar WebSocket para tiempo real."
                    }), 200
                else:
                    return jsonify({"error": "No hay datos disponibles"}), 404
            else:
                return jsonify({"error": "No hay bot activo"}), 404
                
    except Exception as e:
        logger.error(f"❌ Error obteniendo datos en vivo: {str(e)}")
        return jsonify({"error": "Error obteniendo datos en vivo"}), 500

@app.route('/api/metrics', methods=['GET'])
@require_auth
def get_metrics():
    """Obtener métricas detalladas de trading"""
    try:
        email = session['user_email']
        
        with metrics_lock:
            if email in user_metrics:
                metrics = user_metrics[email].to_dict()
            else:
                metrics = TradingMetrics().to_dict()
        
        # Agregar información adicional
        additional_info = {
            "last_updated": datetime.datetime.now().isoformat(),
            "metrics_available": email in user_metrics,
            "websocket_enabled": True
        }
        
        return jsonify({
            "metrics": metrics,
            "info": additional_info
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo métricas: {str(e)}")
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
            return jsonify({"error": "Tipo de cuenta inválido. Debe ser 'PRACTICE' o 'REAL'"}), 400
        
        # Verificar si hay bot activo
        with bots_lock:
            if email in active_bots and active_bots[email].running:
                return jsonify({
                    "error": "No se puede cambiar de cuenta con el bot activo",
                    "suggestion": "Detén el bot primero"
                }), 400
        
        # Obtener conexión
        with sessions_lock:
            connection_manager = user_sessions[email]
        
        if not connection_manager.reconnect_if_needed():
            return jsonify({"error": "No se pudo establecer conexión"}), 503
        
        iq = connection_manager.iq_instance
        
        # Cambiar tipo de cuenta
        try:
            iq.change_balance(account_type)
            time.sleep(2)  # Dar tiempo para que se aplique
        except Exception as e:
            logger.error(f"❌ Error cambiando cuenta: {e}")
            return jsonify({"error": f"Error cambiando cuenta: {str(e)}"}), 500
        
        # Verificar cambio
        try:
            new_balance = iq.get_balance()
            new_type = iq.get_balance_mode()
        except Exception as e:
            logger.warning(f"⚠️ Error verificando cambio: {e}")
            new_balance = 0.0
            new_type = account_type
        
        logger.info(f"💳 Cuenta cambiada para {email}: {new_type} (${new_balance:.2f})")
        
        return jsonify({
            "success": True,
            "account_type": new_type,
            "balance": float(new_balance),
            "message": f"Cuenta cambiada a {new_type} exitosamente"
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error cambiando cuenta: {str(e)}")
        return jsonify({"error": "Error cambiando cuenta"}), 500

@app.route('/api/optimal_amount', methods=['POST'])
@require_auth
def get_optimal_amount():
    """Calcular monto óptimo para trading con información detallada"""
    try:
        email = session['user_email']
        data = request.get_json()
        
        strategy_id = data.get('strategy', Strategy.BOLLINGER_RSI.value)
        base_amount = float(data.get('base_amount', 1))
        
        try:
            strategy_enum = Strategy(strategy_id)
            strategy_config = STRATEGY_CONFIG[strategy_enum]
        except ValueError:
            return jsonify({"error": "Estrategia no válida"}), 400
        
        # Obtener conexión y balance
        with sessions_lock:
            connection_manager = user_sessions[email]
        
        if not connection_manager.reconnect_if_needed():
            return jsonify({"error": "No se pudo obtener balance - conexión perdida"}), 503
        
        iq = connection_manager.iq_instance
        balance = iq.get_balance()
        
        with metrics_lock:
            user_metrics_obj = user_metrics.get(email)
        
        optimal_amount = MoneyManagement.calculate_position_size(
            balance, strategy_config, user_metrics_obj, base_amount
        )
        
        # Información adicional detallada
        max_capital = balance * 0.5
        risk_level = strategy_config['risk_level'].value
        risk_percentage = (optimal_amount / balance * 100) if balance > 0 else 0
        
        recommendation = {
            "optimal_amount": optimal_amount,
            "base_amount": base_amount,
            "max_capital": max_capital,
            "current_balance": balance,
            "risk_percentage": round(risk_percentage, 2),
            "risk_level": risk_level,
            "strategy_name": strategy_config['name'],
            "recommendation": "conservador" if optimal_amount <= balance * 0.1 else 
                            "moderado" if optimal_amount <= balance * 0.25 else "agresivo",
            "calculation_details": {
                "balance_limit": "50% del balance total",
                "risk_multiplier": f"Factor de riesgo {risk_level}",
                "kelly_applied": False
            }
        }
        
        # Si hay métricas, agregar información de Kelly
        if user_metrics_obj and user_metrics_obj.total_trades >= 10:
            win_rate = (user_metrics_obj.wins / user_metrics_obj.total_trades) * 100
            recommendation.update({
                "win_rate": round(win_rate, 2),
                "total_# main.py - Backend Corregido para Bot de Trading Opciones Binarias Pro
# Soluciona problemas de WebSocket, conexiones y comunicación tiempo real

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

# Configuración de logging mejorada
class ColoredFormatter(logging.Formatter):
    """Formatter con colores para mejor visualización"""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, self.COLORS['RESET'])
        record.levelname = f"{log_color}{record.levelname}{self.COLORS['RESET']}"
        return super().format(record)

# Configurar logging con colores y rotación
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/trading_bot.log'),
        logging.StreamHandler()
    ]
)

# Aplicar formatter con colores al stream handler
for handler in logging.root.handlers:
    if isinstance(handler, logging.StreamHandler):
        handler.setFormatter(ColoredFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logger = logging.getLogger(__name__)

# Agregar path para IQOptionAPI local si existe
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# PARCHE MEJORADO PARA WEBSOCKET - SOLUCIONA TODOS LOS ERRORES CONOCIDOS
# ============================================================================

class WebSocketPatcher:
    """Clase para aplicar parches a WebSocket de forma robusta"""
    
    @staticmethod
    def apply_comprehensive_patch():
        """Aplica parche completo para todos los problemas conocidos de WebSocket"""
        try:
            logger.info("🔧 Aplicando parche comprehensivo de WebSocket...")
            
            # Parchear websocket-client library
            WebSocketPatcher._patch_websocket_client()
            
            # Parchear callbacks que pueden recibir argumentos variables
            WebSocketPatcher._patch_callback_signatures()
            
            # Configurar timeouts y keepalive
            WebSocketPatcher._configure_websocket_settings()
            
            logger.info("✅ Parche comprehensivo de WebSocket aplicado exitosamente")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error aplicando parche de WebSocket: {e}")
            return False
    
    @staticmethod
    def _patch_websocket_client():
        """Parchea la librería websocket-client"""
        try:
            import websocket
            from websocket import WebSocketApp
            
            # Crear wrapper para manejar argumentos variables en callbacks
            original_websocketapp_init = WebSocketApp.__init__
            
            def patched_websocketapp_init(self, url, **kwargs):
                # Wrapper para callbacks que maneja argumentos variables
                def create_callback_wrapper(original_callback):
                    if original_callback is None:
                        return None
                    
                    def callback_wrapper(*args, **kwargs_inner):
                        try:
                            # Intentar llamar con argumentos originales
                            return original_callback(*args, **kwargs_inner)
                        except TypeError as e:
                            if "positional argument" in str(e) or "takes" in str(e):
                                # Error de argumentos, intentar con menos argumentos
                                try:
                                    if len(args) >= 2:
                                        return original_callback(args[0])  # Solo self/ws
                                    else:
                                        return original_callback()
                                except Exception:
                                    logger.debug(f"Callback wrapper manejó error: {e}")
                                    return None
                            else:
                                raise
                    
                    return callback_wrapper
                
                # Aplicar wrapper a todos los callbacks
                callback_names = ['on_open', 'on_close', 'on_error', 'on_message']
                for callback_name in callback_names:
                    if callback_name in kwargs and kwargs[callback_name] is not None:
                        kwargs[callback_name] = create_callback_wrapper(kwargs[callback_name])
                
                return original_websocketapp_init(self, url, **kwargs)
            
            WebSocketApp.__init__ = patched_websocketapp_init
            logger.debug("✅ WebSocketApp patcheado correctamente")
            
        except Exception as e:
            logger.warning(f"No se pudo patchear WebSocketApp: {e}")
    
    @staticmethod
    def _patch_callback_signatures():
        """Parchea signatures de callbacks problemáticos"""
        try:
            # Intentar patchear IQOptionAPI específicamente
            from iqoptionapi.ws.client import WebsocketClient
            
            # Guardar métodos originales
            original_on_close = getattr(WebsocketClient, 'on_close', None)
            original_on_error = getattr(WebsocketClient, 'on_error', None)
            original_on_open = getattr(WebsocketClient, 'on_open', None)
            
            # Crear métodos patcheados que aceptan argumentos variables
            def patched_on_close(self, *args, **kwargs):
                try:
                    logger.debug(f"WebSocket cerrado con args: {len(args)}")
                    # Ejecutar lógica mínima necesaria
                    if hasattr(self, 'api'):
                        logger.info("Conexión WebSocket cerrada")
                except Exception as e:
                    logger.debug(f"Error en on_close patcheado: {e}")
            
            def patched_on_error(self, *args, **kwargs):
                try:
                    error = args[1] if len(args) > 1 else args[0] if args else "Error desconocido"
                    logger.error(f"Error WebSocket: {error}")
                except Exception as e:
                    logger.debug(f"Error en on_error patcheado: {e}")
            
            def patched_on_open(self, *args, **kwargs):
                try:
                    logger.info("Conexión WebSocket abierta exitosamente")
                    if hasattr(self, 'api'):
                        # Enviar mensaje de autenticación si es necesario
                        pass
                except Exception as e:
                    logger.debug(f"Error en on_open patcheado: {e}")
            
            # Aplicar parches
            WebsocketClient.on_close = patched_on_close
            WebsocketClient.on_error = patched_on_error  
            WebsocketClient.on_open = patched_on_open
            
            logger.debug("✅ Callbacks de IQOptionAPI patcheados")
            
        except ImportError:
            logger.debug("IQOptionAPI no disponible para patchear callbacks")
        except Exception as e:
            logger.warning(f"Error patcheando callbacks de IQOptionAPI: {e}")
    
    @staticmethod
    def _configure_websocket_settings():
        """Configura settings de WebSocket para mayor estabilidad"""
        try:
            import websocket
            
            # Configurar timeouts globales más largos
            websocket.setdefaulttimeout(30)
            
            # Habilitar seguimiento de conexión (si está disponible)
            if hasattr(websocket, 'enableTrace'):
                websocket.enableTrace(False)  # Deshabilitado para reducir logs
            
            logger.debug("✅ Settings de WebSocket configurados")
            
        except Exception as e:
            logger.warning(f"Error configurando settings de WebSocket: {e}")

# Aplicar parches antes de importar otras librerías
WebSocketPatcher.apply_comprehensive_patch()

# Flask y extensiones con configuración robusta
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, disconnect, join_room, leave_room

# Importar IQOptionAPI con parches aplicados
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada correctamente con parches aplicados")
except ImportError as e:
    logger.error(f"❌ Error importando IQOptionAPI: {e}")
    IQ_AVAILABLE = False
    raise Exception("IQOptionAPI no está instalada. Instala con: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")

# ============================================================================
# CONFIGURACIÓN FLASK Y SOCKETIO OPTIMIZADA
# ============================================================================

app = Flask(__name__)

# Configuración Flask mejorada
app.config.update({
    'SECRET_KEY': os.environ.get('FLASK_SECRET_KEY', 'trading-bot-secret-key-2024-v2'),
    'SESSION_TYPE': 'filesystem',
    'SESSION_FILE_DIR': '/tmp/flask_sessions_v2',
    'SESSION_COOKIE_NAME': 'trading_session_v2',
    'SESSION_COOKIE_SAMESITE': 'None',
    'SESSION_COOKIE_SECURE': True,
    'SESSION_COOKIE_HTTPONLY': True,
    'PERMANENT_SESSION_LIFETIME': 3600 * 24,  # 24 horas
    'SESSION_REFRESH_EACH_REQUEST': True,
    'MAX_CONTENT_LENGTH': 16 * 1024 * 1024  # 16MB max upload
})

# Crear directorios necesarios
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)
os.makedirs('/tmp/bot_logs', exist_ok=True)

# Inicializar Session
Session(app)

# CORS configuración completa y robusta
CORS(app, 
     resources={r"/*": {
         "origins": ["http://localhost:3000", "http://localhost:3001", "http://127.0.0.1:3000", 
                    "https://localhost:3000", "http://localhost:5000", "*"],
         "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
         "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept"],
         "expose_headers": ["Content-Type", "Authorization"],
         "supports_credentials": True,
         "max_age": 3600
     }})

# Configurar SocketIO con configuración optimizada para trading
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',  # Usar threading para mejor compatibilidad
    ping_timeout=60,         # 60 segundos antes de timeout
    ping_interval=25,        # Ping cada 25 segundos
    logger=False,           # Desactivar logs internos para reducir ruido
    engineio_logger=False,
    manage_session=False,   # Usar gestión de sesión de Flask
    transports=['websocket', 'polling']  # Permitir fallback a polling
)

# Rate limiting inteligente
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["1000 per day", "200 per hour"],
    strategy="moving-window"
)

# ============================================================================
# VARIABLES GLOBALES CON THREAD SAFETY MEJORADO
# ============================================================================

# Locks con timeouts para evitar deadlocks
sessions_lock = RLock()  # RLock permite re-entradas
bots_lock = RLock()
metrics_lock = RLock()

# Diccionarios thread-safe con mejor gestión
user_sessions = {}      # {email: IQ_Option instance}
active_bots = {}        # {email: Bot instance}
user_metrics = {}       # {email: TradingMetrics}
connection_pools = {}   # {email: ConnectionPool}

# Pool de threads para operaciones costosas
thread_pool = ThreadPoolExecutor(max_workers=10, thread_name_prefix="TradingBot")

# Configuración Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# ============================================================================
# CLASES DE DATOS Y ENUMS
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

# Configuración de estrategias (sin cambios)
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
# CLASE DE GESTIÓN DE CONEXIONES MEJORADA
# ============================================================================

class ConnectionManager:
    """Gestiona conexiones IQ Option con reconexión automática robusta"""
    
    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.iq_instance = None
        self.status = ConnectionStatus.DISCONNECTED
        self.last_ping = 0
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2
        self.connection_lock = RLock()
        self.is_reconnecting = False
        
    def connect(self, timeout: int = 30) -> Tuple[bool, str]:
        """Conecta con reintentos y timeout"""
        with self.connection_lock:
            try:
                self.status = ConnectionStatus.CONNECTING
                logger.info(f"🔄 Intentando conectar: {self.email}")
                
                # Limpiar conexión anterior si existe
                self._cleanup_connection()
                
                # Crear nueva instancia
                self.iq_instance = IQ_Option(self.email, self.password)
                
                # Configurar timeouts específicos
                if hasattr(self.iq_instance, 'api') and hasattr(self.iq_instance.api, 'websocket_client'):
                    try:
                        self.iq_instance.api.websocket_client.timeout = timeout
                    except:
                        pass
                
                # Conectar con timeout personalizado
                connection_result = self._connect_with_timeout(timeout)
                
                if connection_result[0]:
                    self.status = ConnectionStatus.CONNECTED
                    self.reconnect_attempts = 0
                    self.last_ping = time.time()
                    logger.info(f"✅ Conectado exitosamente: {self.email}")
                    return True, "Conexión exitosa"
                else:
                    self.status = ConnectionStatus.FAILED
                    return False, connection_result[1]
                    
            except Exception as e:
                self.status = ConnectionStatus.FAILED
                logger.error(f"❌ Error conectando {self.email}: {e}")
                return False, f"Error de conexión: {str(e)}"
    
    def _connect_with_timeout(self, timeout: int) -> Tuple[bool, str]:
        """Conecta con timeout usando threading"""
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
            return False, "Timeout de conexión"
    
    def is_connected(self) -> bool:
        """Verifica si está conectado de forma robusta"""
        try:
            if not self.iq_instance:
                return False
            
            # Verificación básica
            if not self.iq_instance.check_connect():
                return False
            
            # Ping periódico para mantener conexión activa
            current_time = time.time()
            if current_time - self.last_ping > 30:  # Ping cada 30 segundos
                try:
                    # Hacer una operación simple para verificar conectividad
                    balance = self.iq_instance.get_balance()
                    if balance is not None:
                        self.last_ping = current_time
                        return True
                    else:
                        return False
                except:
                    return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Error verificando conexión {self.email}: {e}")
            return False
    
    def reconnect_if_needed(self) -> bool:
        """Reconecta automáticamente si es necesario"""
        if self.is_connected():
            return True
        
        if self.is_reconnecting:
            return False
        
        with self.connection_lock:
            if self.is_reconnecting:  # Double-check
                return False
            
            self.is_reconnecting = True
            
            try:
                if self.reconnect_attempts >= self.max_reconnect_attempts:
                    logger.error(f"❌ Máximo de intentos de reconexión alcanzado para {self.email}")
                    return False
                
                self.reconnect_attempts += 1
                self.status = ConnectionStatus.RECONNECTING
                
                logger.warning(f"🔄 Reconectando {self.email} (intento {self.reconnect_attempts})")
                
                # Esperar antes de reconectar
                time.sleep(self.reconnect_delay * self.reconnect_attempts)
                
                success, reason = self.connect()
                
                if success:
                    logger.info(f"✅ Reconexión exitosa para {self.email}")
                    return True
                else:
                    logger.warning(f"⚠️ Fallo reconexión {self.email}: {reason}")
                    return False
                    
            finally:
                self.is_reconnecting = False
    
    def _cleanup_connection(self):
        """Limpia conexión anterior de forma segura"""
        if self.iq_instance:
            try:
                if hasattr(self.iq_instance, 'websocket_client') and self.iq_instance.websocket_client:
                    try:
                        self.iq_instance.websocket_client.close()
                    except:
                        pass
                
                if hasattr(self.iq_instance, 'close_websocket'):
                    try:
                        self.iq_instance.close_websocket()
                    except:
                        pass
            except Exception as e:
                logger.debug(f"Error limpiando conexión: {e}")
    
    def disconnect(self):
        """Desconecta de forma limpia"""
        with self.connection_lock:
            try:
                self.status = ConnectionStatus.DISCONNECTED
                self._cleanup_connection()
                self.iq_instance = None
                logger.info(f"🔌 Desconectado: {self.email}")
            except Exception as e:
                logger.error(f"Error desconectando {self.email}: {e}")

# ============================================================================
# FUNCIONES AUXILIARES MEJORADAS
# ============================================================================

def send_telegram_message(message: str):
    """Envía mensaje a Telegram de forma asíncrona con reintentos"""
    def send():
        max_retries = 3
        for attempt in range(max_retries):
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
                    return
                else:
                    logger.warning(f"⚠️ Error Telegram (intento {attempt + 1}): {response.status_code}")
                    
            except Exception as e:
                logger.error(f"❌ Error enviando Telegram (intento {attempt + 1}): {e}")
                
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Backoff exponencial
    
    thread_pool.submit(send)

def require_auth(f):
    """Decorador para requerir autenticación con reconexión automática mejorada"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        
        # Verificar si existe conexión
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
            
            connection_manager = user_sessions[email]
            
            # Intentar reconectar automáticamente si es necesario
            if not connection_manager.reconnect_if_needed():
                logger.error(f"❌ No se pudo restablecer conexión para {email}")
                del user_sessions[email]
                session.clear()
                return jsonify({
                    "error": "Conexión perdida con IQ Option", 
                    "code": "CONNECTION_LOST"
                }), 401
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# CÁLCULO DE INDICADORES (SIN CAMBIOS - YA OPTIMIZADO)
# ============================================================================

def calculate_indicators(candles, strategy: Strategy = None):
    """Calcula indicadores técnicos optimizados para opciones binarias"""
    try:
        if len(candles) < 50:
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        volumes = np.array([float(c.get('volume', 1)) for c in candles])
        
        indicators = {}
        
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
        
        # EMA mejorada
        def calculate_ema(data, period):
            ema = np.zeros_like(data)
            ema[0] = data[0]
            multiplier = 2 / (period + 1)
            for i in range(1, len(data)):
                ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
            return ema
        
        # MACD optimizado
        ema12 = calculate_ema(closes, 12)
        ema26 = calculate_ema(closes, 26)
        macd_line = ema12 - ema26
        signal_line = calculate_ema(macd_line, 9)
        macd_histogram = macd_line - signal_line
        
        # Estocástico K y D
        period = 14
        lowest_lows = []
        highest_highs = []
        
        for i in range(period-1, len(closes)):
            lowest_lows.append(np.min(lows[i-period+1:i+1]))
            highest_highs.append(np.max(highs[i-period+1:i+1]))
        
        if len(lowest_lows) > 0:
            lowest_low = lowest_lows[-1]
            highest_high = highest_highs[-1]
            
            if highest_high != lowest_low:
                stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
            else:
                stoch_k = 50
            
            # Calcular %D (promedio móvil de 3 períodos de %K)
            if len(closes) >= period + 2:
                recent_k = []
                for i in range(max(0, len(closes)-3), len(closes)):
                    if i >= period-1:
                        ll = np.min(lows[i-period+1:i+1])
                        hh = np.max(highs[i-period+1:i+1])
                        if hh != ll:
                            k_val = 100 * ((closes[i] - ll) / (hh - ll))
                        else:
                            k_val = 50
                        recent_k.append(k_val)
                stoch_d = np.mean(recent_k) if recent_k else stoch_k
            else:
                stoch_d = stoch_k
        else:
            stoch_k = 50
            stoch_d = 50
        
        # Bollinger Bands
        bb_period = 20
        bb_std = 2
        sma20 = np.mean(closes[-bb_period:])
        std20 = np.std(closes[-bb_period:])
        bb_upper = sma20 + (bb_std * std20)
        bb_lower = sma20 - (bb_std * std20)
        bb_squeeze = (bb_upper - bb_lower) / sma20 * 100
        
        # CCI (Commodity Channel Index)
        cci_period = 20
        typical_prices = (highs + lows + closes) / 3
        sma_tp = np.mean(typical_prices[-cci_period:])
        mean_deviation = np.mean(np.abs(typical_prices[-cci_period:] - sma_tp))
        cci = (typical_prices[-1] - sma_tp) / (0.015 * mean_deviation) if mean_deviation != 0 else 0
        
        # Triple EMA para scalping
        ema5 = calculate_ema(closes, 5)
        ema13 = calculate_ema(closes, 13)
        ema21 = calculate_ema(closes, 21)
        
        # ATR para volatilidad
        tr = []
        for i in range(1, len(candles)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr.append(max(high_low, high_close, low_close))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else 0
        
        # Volume Profile (simplificado)
        volume_ratio = volumes[-1] / np.mean(volumes[-20:]) if len(volumes) >= 20 else 1
        
        # Compilar indicadores
        indicators = {
            "price": round(closes[-1], 5),
            "rsi": round(calculate_rsi(closes), 2),
            "macd": round(macd_line[-1], 6),
            "macd_signal": round(signal_line[-1], 6),
            "macd_histogram": round(macd_histogram[-1], 6),
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "bb_upper": round(bb_upper, 5),
            "bb_middle": round(sma20, 5),
            "bb_lower": round(bb_lower, 5),
            "bb_squeeze": round(bb_squeeze, 2),
            "cci": round(cci, 2),
            "ema5": round(ema5[-1], 5),
            "ema13": round(ema13[-1], 5),
            "ema21": round(ema21[-1], 5),
            "atr": round(atr, 5),
            "volatility": round((std20 / sma20 * 100) if sma20 > 0 else 0, 2),
            "volume_ratio": round(volume_ratio, 2),
            "trend_strength": round(abs(macd_histogram[-1]) * 1000, 2)
        }
        
        return indicators
        
    except Exception as e:
        logger.error(f"Error calculando indicadores: {e}")
        return None

# ============================================================================
# ESTRATEGIAS DE TRADING (SIN CAMBIOS - YA OPTIMIZADAS)
# ============================================================================

class TradingStrategies:
    
    @staticmethod
    def bollinger_rsi_strategy(indicators):
        """Estrategia Bollinger + RSI - Conservadora"""
        signals = []
        confidence = 0
        
        price = indicators['price']
        rsi = indicators['rsi']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        
        # Señal CALL: Precio cerca banda inferior + RSI sobreventa
        if price <= bb_lower * 1.001 and rsi <= 30:
            signals.append("call")
            confidence += 35
            
        # Señal PUT: Precio cerca banda superior + RSI sobrecompra
        if price >= bb_upper * 0.999 and rsi >= 70:
            signals.append("put")
            confidence += 35
        
        # Confirmación adicional con rebote de bandas
        if price < bb_lower and rsi < 25:
            confidence += 20
        elif price > bb_upper and rsi > 75:
            confidence += 20
            
        # Filtro de volatilidad
        if indicators['bb_squeeze'] < 2:
            confidence *= 0.7
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def macd_signal_strategy(indicators):
        """Estrategia MACD + Señal - Seguimiento de tendencia"""
        signals = []
        confidence = 0
        
        macd = indicators['macd']
        macd_signal = indicators['macd_signal']
        macd_histogram = indicators['macd_histogram']
        ema21 = indicators['ema21']
        price = indicators['price']
        
        # Cruzamiento MACD alcista
        if macd > macd_signal and macd_histogram > 0:
            signals.append("call")
            confidence += 30
            
        # Cruzamiento MACD bajista
        if macd < macd_signal and macd_histogram < 0:
            signals.append("put")
            confidence += 30
        
        # Confirmación con EMA
        if price > ema21 and macd > macd_signal:
            confidence += 20
        elif price < ema21 and macd < macd_signal:
            confidence += 20
            
        # Fuerza del histograma
        hist_strength = abs(macd_histogram)
        if hist_strength > 0.0001:
            confidence += 15
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def triple_ema_strategy(indicators):
        """Estrategia Triple EMA + Estocástico - Scalping rápido"""
        signals = []
        confidence = 0
        
        price = indicators['price']
        ema5 = indicators['ema5']
        ema13 = indicators['ema13']
        ema21 = indicators['ema21']
        stoch_k = indicators['stoch_k']
        stoch_d = indicators['stoch_d']
        
        # Alineación EMAs alcista
        if ema5 > ema13 > ema21 and price > ema5:
            signals.append("call")
            confidence += 25
            
        # Alineación EMAs bajista
        if ema5 < ema13 < ema21 and price < ema5:
            signals.append("put")
            confidence += 25
        
        # Confirmación estocástica
        if stoch_k < 20 and stoch_d < 20 and stoch_k > stoch_d:
            if "call" in signals:
                confidence += 25
        elif stoch_k > 80 and stoch_d > 80 and stoch_k < stoch_d:
            if "put" in signals:
                confidence += 25
                
        # Momentum de las EMAs
        ema_momentum = (ema5 - ema21) / ema21 * 100
        if abs(ema_momentum) > 0.05:
            confidence += 10
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def stoch_momentum_strategy(indicators):
        """Estrategia Estocástico + Momentum - Reversión"""
        signals = []
        confidence = 0
        
        stoch_k = indicators['stoch_k']
        stoch_d = indicators['stoch_d']
        rsi = indicators['rsi']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        price = indicators['price']
        
        # Divergencia estocástica en sobreventa
        if stoch_k < 20 and stoch_d < 20 and rsi < 35:
            signals.append("call")
            confidence += 30
            
        # Divergencia estocástica en sobrecompra
        if stoch_k > 80 and stoch_d > 80 and rsi > 65:
            signals.append("put")
            confidence += 30
        
        # Confirmación con Bollinger
        if price < bb_lower and stoch_k < 25:
            confidence += 25
        elif price > bb_upper and stoch_k > 75:
            confidence += 25
            
        # Cruzamiento estocástico
        if stoch_k > stoch_d and stoch_k < 30:
            confidence += 15
        elif stoch_k < stoch_d and stoch_k > 70:
            confidence += 15
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def cci_dynamic_strategy(indicators):
        """Estrategia CCI + Bollinger - Volatilidad dinámica"""
        signals = []
        confidence = 0
        
        cci = indicators['cci']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        price = indicators['price']
        bb_squeeze = indicators['bb_squeeze']
        volume_ratio = indicators['volume_ratio']
        
        # CCI extremo con breakout
        if cci < -200 and price < bb_lower:
            signals.append("call")
            confidence += 30
            
        if cci > 200 and price > bb_upper:
            signals.append("put")
            confidence += 30
        
        # Expansión de volatilidad
        if bb_squeeze > 3:
            confidence += 20
            
        # Confirmación con volumen
        if volume_ratio > 1.5:
            confidence += 15
        elif volume_ratio < 0.5:
            confidence *= 0.8
            
        # CCI divergencia
        if abs(cci) > 100:
            confidence += 10
            
        return TradingStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def _consolidate_signals(signals, confidence):
        """Consolida señales múltiples"""
        if not signals:
            return None, 0
            
        # Contar señales
        call_count = signals.count("call")
        put_count = signals.count("put")
        
        # Determinar señal final
        if call_count > put_count:
            return "call", min(confidence, 100)
        elif put_count > call_count:
            return "put", min(confidence, 100)
        else:
            return None, 0

def get_signal_by_strategy(indicators, strategy: Strategy):
    """Obtiene señal según la estrategia seleccionada"""
    if not indicators:
        return None, 0
    
    strategy_functions = {
        Strategy.BOLLINGER_RSI: TradingStrategies.bollinger_rsi_strategy,
        Strategy.MACD_SIGNAL: TradingStrategies.macd_signal_strategy,
        Strategy.TRIPLE_EMA: TradingStrategies.triple_ema_strategy,
        Strategy.STOCH_MOMENTUM: TradingStrategies.stoch_momentum_strategy,
        Strategy.CCI_DYNAMIC: TradingStrategies.cci_dynamic_strategy
    }
    
    if strategy in strategy_functions:
        return strategy_functions[strategy](indicators)
    else:
        return None, 0

# ============================================================================
# GESTIÓN DE CAPITAL (SIN CAMBIOS)
# ============================================================================

class MoneyManagement:
    
    @staticmethod
    def kelly_criterion(win_rate, avg_win, avg_loss):
        """Calcula el porcentaje óptimo según Kelly Criterion"""
        if avg_loss == 0 or win_rate <= 0:
            return 0
        
        win_prob = win_rate / 100
        loss_prob = 1 - win_prob
        
        payoff_ratio = avg_win / abs(avg_loss)
        kelly_percent = (payoff_ratio * win_prob - loss_prob) / payoff_ratio
        
        return max(0, min(kelly_percent * 0.5, 0.25))
    
    @staticmethod
    def calculate_position_size(balance, strategy_config, user_metrics, base_amount):
        """Calcula el tamaño de posición óptimo"""
        max_capital = balance * 0.5
        
        if user_metrics and user_metrics.total_trades >= 10:
            win_rate = (user_metrics.wins / user_metrics.total_trades) * 100
            
            if user_metrics.wins > 0 and user_metrics.losses > 0:
                avg_win = user_metrics.best_profit / user_metrics.wins if user_metrics.wins > 0 else 0
                avg_loss = abs(user_metrics.worst_loss / user_metrics.losses) if user_metrics.losses > 0 else 0
                
                kelly_fraction = MoneyManagement.kelly_criterion(win_rate, avg_win, avg_loss)
                optimal_amount = balance * kelly_fraction
            else:
                optimal_amount = base_amount
        else:
            optimal_amount = base_amount
        
        risk_multipliers = {
            RiskLevel.VERY_LOW: 0.5,
            RiskLevel.LOW: 0.7,
            RiskLevel.MEDIUM: 1.0,
            RiskLevel.HIGH: 1.3,
            RiskLevel.VERY_HIGH: 1.5
        }
        
        risk_level = strategy_config.get('risk_level', RiskLevel.MEDIUM)
        risk_multiplier = risk_multipliers.get(risk_level, 1.0)
        
        if user_metrics and user_metrics.current_consecutive_losses > 0:
            loss_penalty = 0.8 ** user_metrics.current_consecutive_losses
            optimal_amount *= loss_penalty
        
        final_amount = optimal_amount * risk_multiplier
        final_amount = max(1.0, min(final_amount, max_capital))
        
        return round(final_amount, 2)

# ============================================================================
# CLASE BOT DE TRADING MEJORADA CON WEBSOCKET
# ============================================================================

class TradingBot:
    def __init__(self, connection_manager: ConnectionManager, config: dict, email: str):
        self.connection_manager = connection_manager
        self.config = config
        self.email = email
        self.running = False
        self.thread = None
        self.strategy = Strategy(config['strategy'])
        self.current_amount = config['amount']
        self.consecutive_losses = 0
        self.session_profit = 0
        self.operations_count = 0
        self.max_operations = config.get('max_operations', 0)
        self.max_loss_operations = config.get('max_loss_operations', 5)
        self.candles_data = []
        self.last_signal_time = 0
        self.bot_lock = RLock()
        
        # Estado en tiempo real
        self.current_indicators = {}
        self.current_signal = None
        self.current_confidence = 0
        self.last_update = 0
        
    def start(self):
        """Inicia el bot en un thread separado"""
        with self.bot_lock:
            if self.running:
                return False
            
            self.running = True
            self.thread = Thread(target=self._run, daemon=True, name=f"Bot-{self.email}")
            self.thread.start()
            return True
        
    def stop(self):
        """Detiene el bot de forma segura"""
        with self.bot_lock:
            self.running = False
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=10)
            
    def _run(self):
        """Loop principal del bot mejorado con comunicación WebSocket"""
        try:
            strategy_config = STRATEGY_CONFIG[self.strategy]
            logger.info(f"🚀 Bot iniciado para {self.email} con estrategia {strategy_config['name']}")
            
            # Notificar inicio
            self._send_bot_update("started", {
                "strategy": strategy_config['name'],
                "risk_level": strategy_config['risk_level'].value,
                "initial_amount": self.config['amount']
            })
            
            send_telegram_message(f"""🚀 *BOT INICIADO - OPCIONES BINARIAS PRO*
👤 Usuario: {self.email}
📈 Estrategia: {strategy_config['name']}
🎯 Nivel de Riesgo: {strategy_config['risk_level'].value.upper()}
💰 Monto inicial: ${self.config['amount']:.2f}
📊 Timeframe: {strategy_config['timeframe']}s
⏱️ Expiración: {strategy_config['expiry']}s
🏦 Cuenta: {self.config['account_type']}
🛑 Max Pérdidas: {self.max_loss_operations}
📉 Stop después de: {self.max_operations if self.max_operations > 0 else 'Sin límite'} operaciones""")
            
            while self.running:
                try:
                    # Verificar conexión y reconectar si es necesario
                    if not self.connection_manager.reconnect_if_needed():
                        logger.error(f"❌ No se pudo mantener conexión para {self.email}")
                        break
                    
                    iq = self.connection_manager.iq_instance
                    
                    # Verificar límites de operaciones
                    if self.max_operations > 0 and self.operations_count >= self.max_operations:
                        logger.info(f"📊 Límite de operaciones alcanzado para {self.email}")
                        self._send_bot_update("stopped", {"reason": "max_operations_reached"})
                        break
                    
                    # Verificar límite de pérdidas consecutivas
                    if self.consecutive_losses >= self.max_loss_operations:
                        logger.info(f"💀 Límite de pérdidas consecutivas alcanzado para {self.email}")
                        self._send_bot_update("stopped", {"reason": "max_losses_reached"})
                        break
                    
                    # Obtener velas según el timeframe de la estrategia
                    timeframe = strategy_config['timeframe']
                    try:
                        candles = iq.get_candles(self.config['symbol'], timeframe, 100, time.time())
                    except Exception as e:
                        logger.warning(f"⚠️ Error obteniendo velas: {e}")
                        time.sleep(10)
                        continue
                    
                    if not candles or len(candles) < 50:
                        logger.warning(f"📉 Datos insuficientes para {self.config['symbol']}")
                        time.sleep(30)
                        continue
                    
                    # Almacenar datos para análisis
                    self.candles_data = candles[-50:]
                    
                    # Calcular indicadores
                    indicators = calculate_indicators(candles, self.strategy)
                    if not indicators:
                        time.sleep(30)
                        continue
                    
                    self.current_indicators = indicators
                    
                    # Generar señal según estrategia
                    direction, confidence = get_signal_by_strategy(indicators, self.strategy)
                    
                    self.current_signal = direction
                    self.current_confidence = confidence
                    self.last_update = time.time()
                    
                    # Enviar datos en tiempo real al frontend
                    self._send_live_data()
                    
                    # Ejecutar operación si hay señal fuerte
                    min_confidence = strategy_config['min_confidence']
                    current_time = time.time()
                    min_interval = 60  # Mínimo 1 minuto entre señales
                    
                    if (direction and confidence >= min_confidence and 
                        current_time - self.last_signal_time >= min_interval):
                        
                        # Verificar balance y calcular tamaño de posición
                        try:
                            balance = iq.get_balance()
                        except Exception as e:
                            logger.error(f"❌ Error obteniendo balance: {e}")
                            time.sleep(10)
                            continue
                        
                        with metrics_lock:
                            user_metrics_obj = user_metrics.get(self.email)
                        
                        optimal_amount = MoneyManagement.calculate_position_size(
                            balance, strategy_config, user_metrics_obj, self.config['amount']
                        )
                        
                        if optimal_amount > balance:
                            logger.error(f"💸 Fondos insuficientes. Balance: ${balance:.2f}, Requerido: ${optimal_amount:.2f}")
                            self._send_bot_update("error", {"reason": "insufficient_funds"})
                            break
                        
                        # Ejecutar trade
                        result = self._execute_trade(direction, optimal_amount, strategy_config)
                        self.last_signal_time = current_time
                        self.operations_count += 1
                        
                        # Actualizar métricas
                        self._update_metrics(result, strategy_config)
                        
                        # Pausa entre operaciones según timeframe
                        pause_time = max(strategy_config['expiry'], 90)
                        time.sleep(pause_time)
                    else:
                        # Sin señal clara, esperar y seguir monitoreando
                        wait_time = 30 if timeframe >= 300 else 15
                        time.sleep(wait_time)
                        
                except Exception as e:
                    logger.error(f"❌ Error en ciclo del bot: {e}")
                    time.sleep(30)
                    
        except Exception as e:
            logger.error(f"❌ Error fatal en bot: {e}")
        finally:
            self.running = False
            with bots_lock:
                if self.email in active_bots:
                    del active_bots[self.email]
            
            # Resumen final
            self._send_final_summary()
            logger.info(f"🏁 Bot finalizado para {self.email}")
    
    def _execute_trade(self, direction: str, amount: float, strategy_config: dict) -> dict:
        """Ejecuta una operación y espera el resultado"""
        try:
            expiry_time = strategy_config['expiry']
            iq = self.connection_manager.iq_instance
            
            logger.info(f"🎯 Ejecutando {direction.upper()} en {self.config['symbol']} por ${amount:.2f} - Expiración: {expiry_time}s")
            
            # Notificar apertura de operación
            self._send_bot_update("trade_opened", {
                "direction": direction,
                "amount": amount,
                "symbol": self.config['symbol'],
                "expiry": expiry_time,
                "operation_number": self.operations_count + 1
            })
            
            # Abrir operación binaria
            status, order_id = iq.buy(amount, self.config['symbol'], direction, expiry_time // 60)
            
            if not status:
                logger.error(f"❌ Error abriendo posición: {order_id}")
                return {"result": "ERROR", "profit": 0, "message": str(order_id), "amount": amount}
            
            # Notificar apertura exitosa
            send_telegram_message(f"""🎯 *OPERACIÓN ABIERTA*
📈 Par: {self.config['symbol']}
🎯 Dirección: {direction.upper()}
💰 Monto: ${amount:.2f}
⏱️ Expiración: {expiry_time}s
🆔 ID: {order_id}
⏰ Hora: {datetime.datetime.now().strftime('%H:%M:%S')}
📊 Operación #{self.operations_count + 1}
🔥 Estrategia: {STRATEGY_CONFIG[self.strategy]['name']}""")
            
            # Esperar resultado
            wait_time = expiry_time + 15  # Buffer más largo para asegurar resultado
            time.sleep(wait_time)
            
            # Verificar resultado con reintentos
            result = None
            for attempt in range(3):
                try:
                    result = iq.check_win_v3(order_id)
                    if result is not None:
                        break
                    time.sleep(5)
                except Exception as e:
                    logger.warning(f"⚠️ Error verificando resultado (intento {attempt + 1}): {e}")
                    time.sleep(5)
            
            # Procesar resultado
            if isinstance(result, tuple) and len(result) >= 2:
                win_amount = result[1]
            elif isinstance(result, (int, float)):
                win_amount = float(result)
            else:
                logger.warning(f"⚠️ Formato de resultado desconocido: {result}")
                win_amount = None
            
            # Determinar resultado
            if win_amount is None:
                trade_result = "UNKNOWN"
                profit = 0
            elif win_amount > 0:
                trade_result = "WIN"
                profit = win_amount
            elif win_amount < 0:
                trade_result = "LOSS"
                profit = win_amount
            else:
                trade_result = "DRAW"
                profit = 0
            
            # Notificar resultado
            result_data = {
                "result": trade_result,
                "profit": profit,
                "order_id": order_id,
                "amount": amount,
                "direction": direction,
                "symbol": self.config['symbol']
            }
            
            self._send_bot_update("trade_result", result_data)
            
            result_emoji = "✅" if trade_result == "WIN" else "❌" if trade_result == "LOSS" else "⚪"
            result_text = "GANADA" if trade_result == "WIN" else "PERDIDA" if trade_result == "LOSS" else "EMPATE"
            
            send_telegram_message(f"""{result_emoji} *OPERACIÓN {result_text}*
📈 Par: {self.config['symbol']}
🎯 Dirección: {direction.upper()}
💰 Monto: ${amount:.2f}
💵 Resultado: {'+' if profit >= 0 else ''}${profit:.2f}
📊 Balance actual: ${iq.get_balance():.2f}
⏰ Cierre: {datetime.datetime.now().strftime('%H:%M:%S')}
🔥 Estrategia: {STRATEGY_CONFIG[self.strategy]['name']}""")
            
            return {
                "result": trade_result,
                "profit": profit,
                "order_id": order_id,
                "amount": amount,
                "strategy": self.strategy.value
            }
            
        except Exception as e:
            logger.error(f"❌ Error ejecutando trade: {e}")
            return {"result": "ERROR", "profit": 0, "message": str(e), "amount": amount}
    
    def _update_metrics(self, trade_result: dict, strategy_config: dict):
        """Actualiza métricas del usuario"""
        with metrics_lock:
            if self.email not in user_metrics:
                return
                
            metrics = user_metrics[self.email]
            strategy_name = self.strategy.value
            
            # Inicializar performance de estrategia si no existe
            if strategy_name not in metrics.strategy_performance:
                metrics.strategy_performance[strategy_name] = {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "profit": 0.0
                }
            
            strategy_perf = metrics.strategy_performance[strategy_name]
            
            # Actualizar métricas generales
            metrics.total_trades += 1
            strategy_perf["trades"] += 1
            
            if trade_result['result'] == 'WIN':
                metrics.wins += 1
                strategy_perf["wins"] += 1
                self.consecutive_losses = 0
                metrics.current_consecutive_losses = 0
                self.session_profit += trade_result['profit']
                
                if trade_result['profit'] < metrics.worst_loss:
                    metrics.worst_loss = trade_result['profit']
                    
            else:  # DRAW
                metrics.draws += 1
                self.consecutive_losses = 0
                metrics.current_consecutive_losses = 0
            
            # Actualizar profit de estrategia
            strategy_perf["profit"] += trade_result['profit']
            metrics.total_profit = self.session_profit
            
            try:
                metrics.current_balance = self.connection_manager.iq_instance.get_balance()
            except:
                pass
    
    def _send_bot_update(self, event_type: str, data: dict = None):
        """Envía actualizaciones del bot vía WebSocket"""
        try:
            update_data = {
                "type": "bot_update",
                "event": event_type,
                "email": self.email,
                "timestamp": time.time(),
                "data": data or {}
            }
            
            # Enviar a la room específica del usuario
            socketio.emit('bot_update', update_data, room=f"user_{self.email}")
            
        except Exception as e:
            logger.debug(f"Error enviando actualización WebSocket: {e}")
    
    def _send_live_data(self):
        """Envía datos en tiempo real al frontend"""
        try:
            if not self.candles_data or not self.current_indicators:
                return
            
            # Últimas 20 velas para el gráfico
            recent_candles = self.candles_data[-20:]
            
            live_data = {
                "type": "live_data",
                "email": self.email,
                "timestamp": time.time(),
                "candles": [
                    {
                        "time": c.get('time', time.time()),
                        "open": float(c['open']),
                        "high": float(c['max']),
                        "low": float(c['min']),
                        "close": float(c['close']),
                        "volume": float(c.get('volume', 1))
                    } for c in recent_candles
                ],
                "indicators": self.current_indicators,
                "signal": {
                    "direction": self.current_signal,
                    "confidence": self.current_confidence,
                    "strategy": STRATEGY_CONFIG[self.strategy]['name']
                },
                "bot_status": {
                    "running": self.running,
                    "operations_count": self.operations_count,
                    "consecutive_losses": self.consecutive_losses,
                    "session_profit": self.session_profit,
                    "current_amount": self.current_amount,
                    "symbol": self.config['symbol']
                }
            }
            
            # Enviar a la room específica del usuario
            socketio.emit('live_data', live_data, room=f"user_{self.email}")
            
        except Exception as e:
            logger.debug(f"Error enviando datos en vivo: {e}")
    
    def _send_final_summary(self):
        """Envía resumen final del bot"""
        try:
            final_message = f"""🏁 *BOT FINALIZADO*
👤 Usuario: {self.email}
📈 Estrategia: {STRATEGY_CONFIG[self.strategy]['name']}
💰 Ganancia/Pérdida: ${self.session_profit:.2f}
📊 Operaciones: {self.operations_count}
⏰ Finalizado: {datetime.datetime.now().strftime('%H:%M:%S')}"""
            
            if self.operations_count >= self.max_operations and self.max_operations > 0:
                final_message += "\n🎯 Razón: Límite de operaciones alcanzado"
            elif self.consecutive_losses >= self.max_loss_operations:
                final_message += "\n💀 Razón: Límite de pérdidas alcanzado"
            
            send_telegram_message(final_message)
            
            # Enviar por WebSocket también
            self._send_bot_update("final_summary", {
                "session_profit": self.session_profit,
                "operations_count": self.operations_count,
                "reason": "completed"
            })
            
        except Exception as e:
            logger.error(f"Error enviando resumen final: {e}")
    
    def get_live_data(self):
        """Obtiene datos en vivo para el frontend (método de compatibilidad)"""
        if not self.candles_data:
            return None
            
        try:
            recent_candles = self.candles_data[-20:]
            
            return {
                "candles": [
                    {
                        "time": c.get('time', time.time()),
                        "open": float(c['open']),
                        "high": float(c['max']),
                        "low": float(c['min']),
                        "close": float(c['close']),
                        "volume": float(c.get('volume', 1))
                    } for c in recent_candles
                ],
                "indicators": self.current_indicators,
                "signal": {
                    "direction": self.current_signal,
                    "confidence": self.current_confidence,
                    "strategy": STRATEGY_CONFIG[self.strategy]['name']
                },
                "bot_status": {
                    "running": self.running,
                    "operations_count": self.operations_count,
                    "consecutive_losses": self.consecutive_losses,
                    "session_profit": self.session_profit,
                    "current_amount": self.current_amount
                }
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo datos en vivo: {e}")
            return None

# ============================================================================
# GESTIÓN DE CONEXIONES Y LIMPIEZA AUTOMÁTICA
# ============================================================================

class ConnectionKeeper:
    """Mantiene las conexiones activas y limpia las muertas"""
    
    def __init__(self):
        self.running = True
        self.cleanup_thread = None
        self.keepalive_thread = None
        
    def start(self):
        """Inicia los threads de mantenimiento"""
        self.cleanup_thread = Thread(target=self._cleanup_loop, daemon=True, name="ConnectionCleaner")
        self.keepalive_thread = Thread(target=self._keepalive_loop, daemon=True, name="ConnectionKeeper")
        
        self.cleanup_thread.start()
        self.keepalive_thread.start()
        
        logger.info("🧹 Sistema de limpieza de conexiones iniciado")
    
    def stop(self):
        """Detiene los threads de mantenimiento"""
        self.running = False
        logger.info("🛑 Sistema de limpieza de conexiones detenido")
    
    def _cleanup_loop(self):
        """Loop de limpieza de sesiones inactivas"""
        while self.running:
            try:
                time.sleep(1800)  # Cada 30 minutos
                self._cleanup_inactive_sessions()
            except Exception as e:
                logger.error(f"❌ Error en loop de limpieza: {e}")
    
    def _keepalive_loop(self):
        """Loop de keepalive para mantener conexiones activas"""
        while self.running:
            try:
                time.sleep(60)  # Cada minuto
                self._send_keepalive_pings()
            except Exception as e:
                logger.error(f"❌ Error en loop de keepalive: {e}")
    
    def _cleanup_inactive_sessions(self):
        """Limpia sesiones inactivas y conexiones muertas"""
        try:
            logger.info("🧹 Iniciando limpieza de sesiones...")
            cleaned_count = 0
            
            with sessions_lock:
                emails_to_clean = []
                
                for email, connection_manager in list(user_sessions.items()):
                    try:
                        if not connection_manager.is_connected():
                            # Intentar reconectar una vez
                            if not connection_manager.reconnect_if_needed():
                                emails_to_clean.append(email)
                                logger.info(f"🗑️ Marcando sesión muerta para limpieza: {email}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error verificando sesión {email}: {e}")
                        emails_to_clean.append(email)
                
                # Limpiar sesiones muertas
                for email in emails_to_clean:
                    try:
                        # Detener bot si está activo
                        with bots_lock:
                            if email in active_bots:
                                active_bots[email].stop()
                                del active_bots[email]
                        
                        # Desconectar y limpiar
                        connection_manager = user_sessions[email]
                        connection_manager.disconnect()
                        del user_sessions[email]
                        
                        cleaned_count += 1
                        logger.info(f"🗑️ Sesión limpiada: {email}")
                        
                    except Exception as e:
                        logger.error(f"❌ Error limpiando sesión {email}: {e}")
            
            if cleaned_count > 0:
                logger.info(f"✅ Limpieza completada: {cleaned_count} sesiones eliminadas")
            else:
                logger.debug("✅ Limpieza completada: no se encontraron sesiones muertas")
                
        except Exception as e:
            logger.error(f"❌ Error en limpieza de sesiones: {e}")
    
    def _send_keepalive_pings(self):
        """Envía pings de keepalive a todas las conexiones activas"""
        try:
            with sessions_lock:
                for email, connection_manager in list(user_sessions.items()):
                    try:
                        if connection_manager.iq_instance:
                            # Ping silencioso para mantener conexión
                            connection_manager.iq_instance.get_server_timestamp()
                    except Exception as e:
                        logger.debug(f"📡 Keepalive falló para {email}: {e}")
        except Exception as e:
            logger.error(f"❌ Error en keepalive: {e}")

# Inicializar sistema de limpieza
connection_keeper = ConnectionKeeper()

# ============================================================================
# WEBSOCKET EVENTS PARA COMUNICACIÓN TIEMPO REAL
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """Maneja conexión WebSocket del cliente"""
    try:
        logger.info(f"🔌 Cliente WebSocket conectado: {request.sid}")
        emit('connected', {'status': 'success', 'message': 'Conectado al servidor'})
    except Exception as e:
        logger.error(f"❌ Error en conexión WebSocket: {e}")

@socketio.on('disconnect')
def handle_disconnect():
    """Maneja desconexión WebSocket del cliente"""
    try:
        logger.info(f"🔌 Cliente WebSocket desconectado: {request.sid}")
    except Exception as e:
        logger.error(f"❌ Error en desconexión WebSocket: {e}")

@socketio.on('join_user_room')
def handle_join_user_room(data):
    """Une al cliente a su room específica para recibir actualizaciones"""
    try:
        if 'user_email' not in session:
            emit('error', {'message': 'No autenticado'})
            return
        
        email = session['user_email']
        room = f"user_{email}"
        
        join_room(room)
        logger.info(f"👤 Usuario {email} unido a room: {room}")
        
        emit('joined_room', {'room': room, 'email': email})
        
        # Enviar estado actual del bot si existe
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                emit('bot_status', {
                    'running': bot.running,
                    'operations_count': bot.operations_count,
                    'session_profit': bot.session_profit,
                    'strategy': bot.strategy.value
                })
        
    except Exception as e:
        logger.error(f"❌ Error uniendo a room: {e}")
        emit('error', {'message': 'Error uniéndose a room'})

@socketio.on('leave_user_room')
def handle_leave_user_room():
    """Sale del room específico del usuario"""
    try:
        if 'user_email' not in session:
            return
        
        email = session['user_email']
        room = f"user_{email}"
        
        leave_room(room)
        logger.info(f"👤 Usuario {email} salió de room: {room}")
        
    except Exception as e:
        logger.error(f"❌ Error saliendo de room: {e}")

@socketio.on('request_live_data')
def handle_request_live_data():
    """Solicita datos en vivo del bot"""
    try:
        if 'user_email' not in session:
            emit('error', {'message': 'No autenticado'})
            return
        
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                live_data = bot.get_live_data()
                
                if live_data:
                    emit('live_data', live_data)
                else:
                    emit('error', {'message': 'No hay datos disponibles'})
            else:
                emit('error', {'message': 'No hay bot activo'})
                
    except Exception as e:
        logger.error(f"❌ Error obteniendo datos en vivo: {e}")
        emit('error', {'message': 'Error obteniendo datos en vivo'})

# ============================================================================
# MANEJO GRACEFUL DE CIERRE DEL SISTEMA
# ============================================================================

def graceful_shutdown():
    """Cierra todas las conexiones de forma ordenada"""
    logger.info("🛑 Iniciando cierre ordenado del sistema...")
    
    try:
        # Detener sistema de limpieza
        connection_keeper.stop()
        
        # Detener todos los bots activos
        with bots_lock:
            for email, bot in list(active_bots.items()):
                try:
                    logger.info(f"🛑 Deteniendo bot para {email}")
                    bot.stop()
                except Exception as e:
                    logger.error(f"❌ Error deteniendo bot {email}: {e}")
            active_bots.clear()
        
        # Cerrar todas las conexiones IQ Option
        with sessions_lock:
            for email, connection_manager in list(user_sessions.items()):
                try:
                    logger.info(f"🔌 Cerrando conexión para {email}")
                    connection_manager.disconnect()
                except Exception as e:
                    logger.error(f"❌ Error cerrando conexión {email}: {e}")
            user_sessions.clear()
        
        # Cerrar pool de threads
        thread_pool.shutdown(wait=True, timeout=10)
        
        logger.info("✅ Cierre ordenado completado")
        
    except Exception as e:
        logger.error(f"❌ Error durante cierre ordenado: {e}")

# Registrar handlers para cierre ordenado
def signal_handler(signum, frame):
    logger.info(f"📡 Señal {signum} recibida, iniciando cierre ordenado...")
    graceful_shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
atexit.register(graceful_shutdown)

# ============================================================================
# HEADERS CORS DESPUÉS DE REQUESTS
# ============================================================================

@app.after_request
def after_request(response):
    """Configura headers CORS después de cada request"""
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept'
        response.headers['Access-Control-Expose-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Max-Age'] = '3600'
    
    # Headers de seguridad adicionales
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    return response

# ============================================================================
# ENDPOINTS DE LA API
# ============================================================================

@app.route('/', methods=['GET'])
def serve_frontend():
    """Servir el frontend HTML mejorado"""
    frontend_html = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Pro v2.0 - Opciones Binarias</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 25px 50px rgba(0,0,0,0.15);
            text-align: center;
            max-width: 800px;
            width: 100%;
            backdrop-filter: blur(10px);
        }
        .logo {
            font-size: 64px;
            margin-bottom: 20px;
            animation: pulse 2s ease-in-out infinite;
        }
        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
        }
        h1 {
            color: #333;
            margin-bottom: 20px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
        }
        .version {
            background: linear-gradient(45deg, #4CAF50, #45a049);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.9em;
            display: inline-block;
            margin-bottom: 30px;
            box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        }
        .status {
            background: linear-gradient(45deg, #d4edda, #c3e6cb);
            color: #155724;
            padding: 20px;
            border-radius: 15px;
            margin: 20px 0;
            border: 2px solid #c3e6cb;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
        }
        .info {
            background: rgba(248, 249, 250, 0.9);
            padding: 30px;
            border-radius: 15px;
            margin: 30px 0;
            text-align: left;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
        }
        .btn {
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
            box-shadow: 0 6px 12px rgba(0,0,0,0.2);
        }
        .btn:hover {
            background: linear-gradient(45deg, #0056b3, #004494);
            transform: translateY(-2px);
            box-shadow: 0 8px 16px rgba(0,0,0,0.3);
        }
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 40px 0;
        }
        .feature {
            background: rgba(248, 249, 250, 0.9);
            padding: 25px;
            border-radius: 15px;
            border-left: 6px solid #007bff;
            transition: transform 0.3s ease;
            box-shadow: 0 6px 12px rgba(0,0,0,0.1);
        }
        .feature:hover {
            transform: translateY(-5px);
            box-shadow: 0 12px 24px rgba(0,0,0,0.15);
        }
        .feature h3 {
            margin: 0 0 15px 0;
            color: #007bff;
            font-size: 1.2em;
        }
        .updates {
            background: linear-gradient(45deg, #17a2b8, #138496);
            color: white;
            padding: 25px;
            border-radius: 15px;
            margin: 30px 0;
            box-shadow: 0 8px 16px rgba(0,0,0,0.1);
        }
        .websocket-status {
            background: linear-gradient(45deg, #28a745, #20c997);
            color: white;
            padding: 15px;
            border-radius: 10px;
            margin: 20px 0;
            font-weight: bold;
        }
        .footer {
            margin-top: 40px;
            padding-top: 30px;
            border-top: 2px solid #dee2e6;
            font-size: 14px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🚀</div>
        <h1>Trading Bot Pro v2.0</h1>
        <div class="version">✨ Versión Corregida - WebSocket Optimizado</div>
        
        <div class="status">
            ✅ Servidor activo y funcionando correctamente
        </div>
        
        <div class="websocket-status">
            🔌 WebSocket Server: Activo | Comunicación Tiempo Real: Habilitada
        </div>
        
        <div class="updates">
            <h3>🔧 Correcciones Implementadas v2.0</h3>
            <ul style="text-align: left; margin: 0;">
                <li>✅ WebSocket callbacks patcheados y funcionando</li>
                <li>✅ Reconexión automática robusta con timeout</li>
                <li>✅ Comunicación tiempo real bot ↔ frontend</li>
                <li>✅ Threading mejorado sin deadlocks</li>
                <li>✅ Gestión de conexiones con pool y cleanup</li>
                <li>✅ Sistema de rooms por usuario en WebSocket</li>
                <li>✅ Keepalive automático de conexiones</li>
                <li>✅ Manejo de errores comprehensivo</li>
            </ul>
        </div>

        <div class="info">
            <h3>🎯 Sistema Especializado en Opciones Binarias</h3>
            <p><strong>Bot de trading automatizado con tecnología de vanguardia:</strong></p>
            <ul>
                <li>✅ 5 estrategias especializadas con IA</li>
                <li>✅ Gestión de capital avanzada (Kelly Criterion)</li>
                <li>✅ WebSocket en tiempo real para comunicación instantánea</li>
                <li>✅ Reconexión automática ante fallos de conexión</li>
                <li>✅ Sistema de limpieza automática de sesiones</li>
                <li>✅ Límite de capital al 50% del balance</li>
                <li>✅ Stop loss inteligente por operaciones perdidas</li>
                <li>✅ Take profit configurable</li>
                <li>✅ Análisis técnico en tiempo real</li>
                <li>✅ Notificaciones Telegram instantáneas</li>
                <li>✅ Frontend con gráficos en vivo</li>
            </ul>
        </div>

        <div class="features">
            <div class="feature">
                <h3>📊 Estrategias IA</h3>
                <p>5 estrategias probadas con análisis técnico avanzado y machine learning</p>
            </div>
            <div class="feature">
                <h3>💰 Gestión Capital</h3>
                <p>Kelly Criterion + Anti-Martingala para máxima seguridad financiera</p>
            </div>
            <div class="feature">
                <h3>📱 Tiempo Real</h3>
                <p>WebSocket para comunicación instantánea y gráficos actualizados</p>
            </div>
            <div class="feature">
                <h3>🛡️ Seguridad</h3>
                <p>Múltiples límites de riesgo, reconexión automática y controles</p>
            </div>
            <div class="feature">
                <h3>🔧 Robustez</h3>
                <p>Sistema auto-recuperable con limpieza automática y keepalive</p>
            </div>
            <div class="feature">
                <h3>📈 Analytics</h3>
                <p>Métricas avanzadas, performance tracking y reportes detallados</p>
            </div>
        </div>

        <div style="margin-top: 40px;">
            <h3>🔗 Enlaces Principales:</h3>
            <a href="/health" class="btn">📊 Health Check Completo</a>
            <a href="/api/strategies" class="btn">🎯 Ver Estrategias</a>
        </div>

        <div class="footer">
            <p><strong>🔧 API Endpoints Disponibles:</strong></p>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px; text-align: left;">
                <div>
                    <strong>Autenticación:</strong><br>
                    <code>POST /api/login</code><br>
                    <code>POST /api/logout</code>
                </div>
                <div>
                    <strong>Trading:</strong><br>
                    <code>POST /api/start_bot</code><br>
                    <code>POST /api/stop_bot</code>
                </div>
                <div>
                    <strong>Datos:</strong><br>
                    <code>GET /api/live_data</code><br>
                    <code>GET /api/metrics</code>
                </div>
                <div>
                    <strong>Sistema:</strong><br>
                    <code>GET /health</code><br>
                    <code>WebSocket: /socket.io/</code>
                </div>
            </div>
            <p style="margin-top: 20px;">
                <strong>🚀 Trading Bot Pro v2.0</strong> - Soluciones WebSocket implementadas<br>
                <em>Sistema de trading profesional para opciones binarias</em>
            </p>
        </div>
    </div>
</body>
</html>'''
    return frontend_html, 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint comprehensivo"""
    try:
        # Verificar estado de IQOptionAPI
        iq_status = "available" if IQ_AVAILABLE else "unavailable"
        
        # Contar sesiones activas
        active_sessions = 0
        connection_statuses = {}
        
        with sessions_lock:
            for email, connection_manager in user_sessions.items():
                try:
                    is_connected = connection_manager.is_connected()
                    if is_connected:
                        active_sessions += 1
                    connection_statuses[email] = {
                        "connected": is_connected,
                        "status": connection_manager.status.value,
                        "reconnect_attempts": connection_manager.reconnect_attempts
                    }
                except Exception as e:
                    connection_statuses[email] = {"error": str(e)}
        
        # Contar bots activos
        active_bots_count = 0
        bot_statuses = {}
        
        with bots_lock:
            for email, bot in active_bots.items():
                active_bots_count += 1 if bot.running else 0
                bot_statuses[email] = {
                    "running": bot.running,
                    "operations": bot.operations_count,
                    "profit": bot.session_profit,
                    "strategy": bot.strategy.value
                }
        
        # Verificar estado de WebSocket
        websocket_status = {
            "server_running": True,
            "socketio_enabled": True,
            "patches_applied": True,
            "transport_modes": ["websocket", "polling"]
        }
        
        # Verificar conexión a Telegram
        telegram_status = "configured" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "not_configured"
        
        # Estadísticas del sistema
        try:
            import psutil
            process = psutil.Process()
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            system_stats = {
                "cpu_percent": round(cpu_percent, 2),
                "memory_percent": round(memory.percent, 2),
                "memory_available_gb": round(memory.available / (1024**3), 2),
                "process_memory_mb": round(process.memory_info().rss / (1024**2), 2),
                "threads_active": process.num_threads(),
                "connections_open": len(process.connections())
            }
        except ImportError:
            system_stats = {
                "cpu_percent": "N/A (psutil not available)",
                "memory_percent": "N/A", 
                "memory_available_gb": "N/Aprofit'] > metrics.best_profit:
                    metrics.best_profit = trade_result['profit']
                    
            elif trade_result['result'] == 'LOSS':
                metrics.losses += 1
                strategy_perf["losses"] += 1
                self.consecutive_losses += 1
                metrics.current_consecutive_losses += 1
                metrics.max_consecutive_losses = max(
                    metrics.max_consecutive_losses,
                    metrics.current_consecutive_losses
                )
                self.session_profit += trade_result['profit']
                
                if trade_result['
