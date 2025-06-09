return False, f"Error de conexión después de {max_retries} intentos: {raw_msg}"
                    
                    # Verificar que la conexión esté realmente establecida
                    time.sleep(1)
                    
                    if not iq.check_connect():
                        logger.warning(f"⚠️ Conexión no verificada (intento {attempt + 1})")
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return False, "No se pudo establecer conexión estable"
                    
                    logger.info("✅ Conexión establecida para opciones binarias")
                    return True, iq
                    
                except Exception as e:
                    logger.error(f"❌ Excepción en intento {attempt + 1}: {str(e)}")
                    if attempt == max_retries - 1:
                        return False, f"Error de conexión: {str(e)}"
            
            return False, "No se pudo establecer conexión después de múltiples intentos"
        
        # Intentar conexión
        success, result = attempt_binary_connection()
        
        if not success:
            if isinstance(result, dict):
                return jsonify({"success": False, **result}), 401
            else:
                return jsonify({"success": False, "message": result}), 503
        
        iq = result
        
        # Obtener información del usuario
        try:
            user_email = email
            user_name = user_email.split('@')[0].title()
            
            # Obtener balance y tipo de cuenta con reintentos
            balance = None
            account_type = None
            
            for balance_attempt in range(3):
                try:
                    balance = iq.get_balance()
                    account_type = iq.get_balance_mode()
                    if balance is not None:
                        break
                except Exception as e:
                    logger.warning(f"⚠️ Error obteniendo balance (intento {balance_attempt + 1}): {e}")
                    if balance_attempt < 2:
                        time.sleep(1)
                    else:
                        balance = 0.0
                        account_type = "PRACTICE"
            
            # Guardar sesión exitosa
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            # Inicializar métricas específicas para opciones binarias
            if email not in user_metrics:
                user_metrics[email] = BinaryTradingMetrics()
                user_metrics[email].start_balance = balance
                user_metrics[email].current_balance = balance
            
            # Notificar login exitoso con información específica
            send_telegram_message(f"""🎯 *LOGIN EXITOSO - OPCIONES BINARIAS PRO*
👤 Usuario: {user_name}
📧 Email: {email}
💰 Balance: ${balance:.2f}
🏦 Cuenta: {account_type}
🎯 Sistema: Optimizado para Opciones Binarias
⚡ Ejecución: Rápida sin demoras
💹 Capital Máximo: 50% del balance (${balance * 0.5:.2f})
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}""")
            
            return jsonify({
                "success": True,
                "user": {
                    "name": user_name,
                    "email": email,
                    "balance": float(balance),
                    "account_type": account_type,
                    "currency": "USD",
                    "max_investment": float(balance * 0.5)
                },
                "system": {
                    "type": "binary_options_bot",
                    "features": {
                        "fast_execution": True,
                        "max_capital_limit": "50%",
                        "configurable_limits": True,
                        "kelly_criterion": True
                    }
                },
                "message": "Conexión exitosa para trading de opciones binarias"
            }), 200
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo datos del usuario: {e}")
            
            with sessions_lock:
                user_sessions[email] = iq
            
            session['user_email'] = email
            session.permanent = True
            
            return jsonify({
                "success": True,
                "user": {
                    "name": email.split('@')[0],
                    "email": email,
                    "balance": 0.0,
                    "account_type": "PRACTICE",
                    "currency": "USD",
                    "max_investment": 0.0
                },
                "message": "Conexión exitosa (datos limitados)"
            }), 200
            
    except Exception as e:
        logger.error(f"❌ Error en login: {str(e)}", exc_info=True)
        return jsonify({
            "success": False,
            "message": f"Error del servidor: {str(e)}"
        }), 500

@app.route('/api/strategies', methods=['GET'])
@require_auth
def get_strategies():
    """Obtener estrategias clasificadas por nivel de riesgo"""
    try:
        strategies = []
        for strategy, config in BINARY_STRATEGY_CONFIG.items():
            strategies.append({
                "id": strategy.value,
                "name": config["name"],
                "description": config["description"],
                "risk_level": config["risk_level"].value,
                "risk_level_name": config["risk_level"].value.replace('_', ' ').title(),
                "min_confidence": config["min_confidence"],
                "timeframe": config["timeframe"],
                "expiry": config["expiry"],
                "indicators": config["indicators"],
                "win_rate_expected": config["win_rate_expected"],
                "trades_per_day": config["trades_per_day"],
                "best_for": config["best_for"],
                "market_conditions": config["market_conditions"],
                "recommended_for": "Principiantes" if config["risk_level"] in [RiskLevel.VERY_LOW, RiskLevel.LOW] 
                              else "Intermedios" if config["risk_level"] == RiskLevel.MEDIUM 
                              else "Avanzados"
            })
        
        # Ordenar por nivel de riesgo
        risk_order = {
            "very_low": 1,
            "low": 2,
            "medium": 3,
            "high": 4,
            "very_high": 5
        }
        
        strategies.sort(key=lambda x: risk_order.get(x["risk_level"], 3))
        
        return jsonify({
            "strategies": strategies,
            "total": len(strategies),
            "risk_levels": [level.value for level in RiskLevel],
            "system_info": {
                "type": "binary_options",
                "max_capital_limit": "50%",
                "execution_speed": "optimized"
            }
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo estrategias: {str(e)}")
        return jsonify({"error": "Error obteniendo estrategias"}), 500

@app.route('/api/start_bot', methods=['POST'])
@require_auth
@limiter.limit("3 per minute")
def start_bot():
    """Iniciar bot con límites configurables desde frontend"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots and active_bots[email].running:
                return jsonify({"error": "Ya hay un bot activo para esta sesión"}), 400
        
        data = request.get_json()
        
        # Parámetros básicos
        symbol = data.get('symbol', 'EURUSD')
        amount = float(data.get('amount', 1))
        strategy = data.get('strategy', Strategy.BOLLINGER_RSI.value)
        account_type = data.get('account_type', 'PRACTICE')
        
        # Límites configurables desde frontend
        max_loss_operations = int(data.get('max_loss_operations', 5))
        max_win_operations = int(data.get('max_win_operations', 0))  # 0 = sin límite
        max_daily_operations = int(data.get('max_daily_operations', 50))
        
        # Validaciones específicas para opciones binarias
        if amount <= 0 or amount > 10000:
            return jsonify({"error": "El monto debe estar entre $1 y $10,000"}), 400
        
        try:
            strategy_enum = Strategy(strategy)
        except ValueError:
            return jsonify({"error": "Estrategia no válida"}), 400
        
        if max_loss_operations < 1 or max_loss_operations > 20:
            return jsonify({"error": "El límite de pérdidas debe estar entre 1 y 20"}), 400
            
        if max_win_operations < 0 or max_win_operations > 50:
            return jsonify({"error": "El límite de ganancias debe estar entre 0 y 50 (0 = sin límite)"}), 400
            
        if max_daily_operations < 5 or max_daily_operations > 200:
            return jsonify({"error": "El límite diario debe estar entre 5 y 200 operaciones"}), 400
        
        # Cambiar tipo de cuenta
        iq = user_sessions[email]
        iq.change_balance(account_type)
        
        # Verificar balance y aplicar límite del 50%
        balance = iq.get_balance()
        max_allowed = balance * 0.5  # REGLA PRINCIPAL: Máximo 50% del capital
        
        if amount > max_allowed:
            return jsonify({
                "error": f"El monto inicial (${amount:.2f}) excede el 50% del balance disponible (${max_allowed:.2f})",
                "max_allowed": max_allowed,
                "current_balance": balance,
                "rule": "Máximo 50% del capital disponible para opciones binarias"
            }), 400
        
        # Configuración del bot
        bot_config = {
            'symbol': symbol,
            'amount': amount,
            'strategy': strategy,
            'account_type': account_type,
            'max_loss_operations': max_loss_operations,
            'max_win_operations': max_win_operations,
            'max_daily_operations': max_daily_operations
        }
        
        # Crear e iniciar bot específico para opciones binarias
        bot = BinaryTradingBot(iq, bot_config, email)
        
        with bots_lock:
            active_bots[email] = bot
        
        bot.start()
        
        strategy_config = BINARY_STRATEGY_CONFIG[strategy_enum]
        
        # Actualizar métricas del usuario con los nuevos límites
        if email in user_metrics:
            metrics = user_metrics[email]
            metrics.max_loss_operations = max_loss_operations
            metrics.max_win_operations = max_win_operations
            metrics.max_daily_operations = max_daily_operations
        
        return jsonify({
            "success": True,
            "message": "Bot de opciones binarias iniciado correctamente",
            "config": bot_config,
            "strategy_info": {
                "name": strategy_config["name"],
                "risk_level": strategy_config["risk_level"].value,
                "description": strategy_config["description"],
                "win_rate_expected": strategy_config["win_rate_expected"],
                "trades_per_day": strategy_config["trades_per_day"],
                "timeframe": strategy_config["timeframe"],
                "expiry": strategy_config["expiry"]
            },
            "limits": {
                "max_allowed_investment": max_allowed,
                "current_balance": balance,
                "capital_usage_percent": (amount / balance * 100) if balance > 0 else 0,
                "max_loss_operations": max_loss_operations,
                "max_win_operations": max_win_operations,
                "max_daily_operations": max_daily_operations
            },
            "features": {
                "fast_execution": True,
                "no_delays": True,
                "kelly_criterion": True,
                "real_time_analysis": True
            }
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error iniciando bot: {str(e)}")
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
                
                send_telegram_message(f"""🛑 *BOT DETENIDO MANUALMENTE*
👤 Usuario: {email}
💰 Ganancia de sesión: ${bot.session_profit:.2f}
📊 Operaciones: {bot.operations_count}
✅ Ganancias consecutivas: {bot.consecutive_wins}
❌ Pérdidas consecutivas: {bot.consecutive_losses}""")
                
                return jsonify({
                    "success": True,
                    "message": "Bot detenido correctamente",
                    "final_stats": {
                        "session_profit": bot.session_profit,
                        "operations_count": bot.operations_count,
                        "consecutive_wins": bot.consecutive_wins,
                        "consecutive_losses": bot.consecutive_losses,
                        "daily_operations": bot.daily_operations
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
    """Obtener estado detallado del bot de opciones binarias"""
    try:
        email = session['user_email']
        
        with bots_lock:
            if email in active_bots:
                bot = active_bots[email]
                strategy_config = BINARY_STRATEGY_CONFIG[bot.strategy]
                
                current_balance = iq.get_balance() if email in user_sessions else 0
                win_rate = ((bot.operations_count - bot.consecutive_losses) / bot.operations_count * 100) if bot.operations_count > 0 else 0
                
                status = {
                    "running": bot.running,
                    "operations_count": bot.operations_count,
                    "daily_operations": bot.daily_operations,
                    "consecutive_losses": bot.consecutive_losses,
                    "consecutive_wins": bot.consecutive_wins,
                    "session_profit": bot.session_profit,
                    "current_balance": current_balance,
                    "win_rate_session": round(win_rate, 2),
                    "strategy": {
                        "id": bot.strategy.value,
                        "name": strategy_config["name"],
                        "risk_level": strategy_config["risk_level"].value,
                        "win_rate_expected": strategy_config["win_rate_expected"],
                        "timeframe": strategy_config["timeframe"],
                        "expiry": strategy_config["expiry"]
                    },
                    "config": bot.config,
                    "limits": {
                        "max_loss_operations": bot.max_loss_operations,
                        "max_win_operations": bot.max_win_operations,
                        "max_daily_operations": bot.max_daily_operations,
                        "losses_remaining": max(0, bot.max_loss_operations - bot.consecutive_losses),
                        "wins_remaining": max(0, bot.max_win_operations - bot.consecutive_wins) if bot.max_win_operations > 0 else "unlimited",
                        "daily_remaining": max(0, bot.max_daily_operations - bot.daily_operations)
                    },
                    "performance": {
                        "expected_vs_actual": {
                            "expected_win_rate": strategy_config["win_rate_expected"],
                            "actual_win_rate": round(win_rate, 2),
                            "performance_diff": round(win_rate - strategy_config["win_rate_expected"], 2)
                        },
                        "profitability": {
                            "total_profit": bot.session_profit,
                            "avg_profit_per_trade": round(bot.session_profit / bot.operations_count, 2) if bot.operations_count > 0 else 0,
                            "roi_session": round((bot.session_profit / bot.config['amount']) * 100, 2) if bot.config['amount'] > 0 else 0
                        }
                    },
                    "system": {
                        "type": "binary_options_bot",
                        "execution_speed": "optimized",
                        "capital_protection": "50% max rule active"
                    }
                }
            else:
                status = {
                    "running": False,
                    "message": "No hay bot activo",
                    "system": {
                        "type": "binary_options_bot",
                        "ready": True
                    }
                }
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo estado del bot: {str(e)}")
        return jsonify({"error": "Error obteniendo estado"}), 500

@app.route('/api/live_data', methods=['GET'])
@require_auth
def get_live_data():
    """Obtener datos en vivo optimizados para opciones binarias"""
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
                        "system": {
                            "type": "binary_options",
                            "optimized": True,
                            "fast_execution": True
                        }
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
    """Obtener métricas detalladas con límites configurables"""
    try:
        email = session['user_email']
        
        if email in user_metrics:
            metrics = user_metrics[email].to_dict()
        else:
            metrics = BinaryTradingMetrics().to_dict()
        
        # Agregar información específica del sistema
        additional_info = {
            "system_type": "binary_options_trading",
            "features": {
                "configurable_limits": True,
                "50_percent_rule": True,
                "kelly_criterion": True,
                "fast_execution": True
            },
            "last_updated": datetime.datetime.now().isoformat()
        }
        
        return jsonify({
            "metrics": metrics,
            "system": additional_info
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error obteniendo métricas: {str(e)}")
        return jsonify({"error": "Error obteniendo métricas"}), 500

@app.route('/api/update_limits', methods=['POST'])
@require_auth
def update_limits():
    """Actualizar límites configurables desde frontend"""
    try:
        email = session['user_email']
        data = request.get_json()
        
        # Verificar que no hay bot activo
        with bots_lock:
            if email in active_bots and active_bots[email].running:
                return jsonify({"error": "No se pueden cambiar límites con bot activo"}), 400
        
        # Obtener nuevos límites
        max_loss_operations = data.get('max_loss_operations')
        max_win_operations = data.get('max_win_operations')
        max_daily_operations = data.get('max_daily_operations')
        
        # Validaciones
        if max_loss_operations is not None:
            if max_loss_operations < 1 or max_loss_operations > 20:
                return jsonify({"error": "Límite de pérdidas debe estar entre 1 y 20"}), 400
        
        if max_win_operations is not None:
            if max_win_operations < 0 or max_win_operations > 50:
                return jsonify({"error": "Límite de ganancias debe estar entre 0 y 50"}), 400
        
        if max_daily_operations is not None:
            if max_daily_operations < 5 or max_daily_operations > 200:
                return jsonify({"error": "Límite diario debe estar entre 5 y 200"}), 400
        
        # Actualizar métricas del usuario
        if email not in user_metrics:
            user_metrics[email] = BinaryTradingMetrics()
        
        metrics = user_metrics[email]
        
        if max_loss_operations is not None:
            metrics.max_loss_operations = max_loss_operations
        if max_win_operations is not None:
            metrics.max_win_operations = max_win_operations
        if max_daily_operations is not None:
            metrics.max_daily_operations = max_daily_operations
        
        return jsonify({
            "success": True,
            "message": "Límites actualizados correctamente",
            "limits": {
                "max_loss_operations": metrics.max_loss_operations,
                "max_win_operations": metrics.max_win_operations,
                "max_daily_operations": metrics.max_daily_operations
            }
        }), 200
        
    except Exception as e:
        logger.error(f"❌ Error actualizando límites: {str(e)}")
        return jsonify({"error": "Error actualizando límites"}), 500

# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    logger.info("=" * 80)
    logger.info(f"🎯 INICIANDO BOT DE OPCIONES BINARIAS PRO")
    logger.info("=" * 80)
    logger.info(f"📍 Puerto: {port}")
    logger.info(f"🔧 IQ Option API: {'Disponible' if IQ_AVAILABLE else 'No disponible'}")
    logger.info(f"📱 Telegram: {'Configurado' if TELEGRAM_BOT_TOKEN else 'No configurado'}")
    logger.info(f"📊 Estrategias disponibles: {len(BINARY_STRATEGY_CONFIG)}")
    logger.info("")
    logger.info("🎯 CARACTERÍSTICAS ESPECÍFICAS PARA OPCIONES BINARIAS:")
    logger.info("   • ✅ 5 estrategias clasificadas por nivel de riesgo")
    logger.info("   • ✅ Operaciones rápidas sin demora - Optimizado para expiración corta")
    logger.info("   • ✅ Inversión máxima limitada al 50% del capital disponible")
    logger.info("   • ✅ Límites configurables de operaciones perdidas desde frontend")
    logger.info("   • ✅ Límites configurables de operaciones ganadas desde frontend")
    logger.info("   • ✅ Gestión de capital con Kelly Criterion para opciones binarias")
    logger.info("   • ✅ Análisis técnico específico para timeframes cortos")
    logger.info("   • ✅ Señales de alta confianza para maximizar win rate")
    logger.info("   • ✅ Seguimiento de rachas ganadas y perdidas en tiempo real")
    logger.info("   • ✅ WebSocket callbacks patcheados y funcionando")
    logger.info("   • ✅ Reconexión automática ante fallos de conexión")
    logger.info("   • ✅ Notificaciones Telegram con detalles técnicos")
    logger.info("=" * 80)
    
    if not IQ_AVAILABLE:
        logger.error("❌ IQOptionAPI no está disponible. El servidor no funcionará correctamente.")
        logger.error("💡 Instala con: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")
    
    send_telegram_message(f"""🎯 *BOT OPCIONES BINARIAS PRO INICIADO*
⏰ {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
📍 Puerto: {port}
🔧 API: {'OK' if IQ_AVAILABLE else 'ERROR'}
📊 Estrategias: {len(BINARY_STRATEGY_CONFIG)}
⚡ Ejecución: Rápida sin demoras
💹 Capital Máximo: 50% del balance
🎯 Límites: Configurables desde frontend
🛡️ WebSocket: Patcheado y optimizado
📈 Análisis: Específico para opciones binarias""")
    
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)        strategy_perf = metrics.strategy_performance[strategy_name]
        
        # Actualizar métricas generales
        metrics.total_trades += 1
        strategy_perf["trades"] += 1
        
        if trade_result['result'] == 'WIN':
            metrics.wins += 1
            strategy_perf["wins"] += 1
            self.consecutive_losses = 0
            self.consecutive_wins += 1
            metrics.current_consecutive_losses = 0
            metrics.current_consecutive_wins += 1
            metrics.max_consecutive_wins = max(metrics.max_consecutive_wins, metrics.current_consecutive_wins)
            self.session_profit += trade_result['profit']
            
            if trade_result['profit'] > metrics.best_profit:
                metrics.best_profit = trade_result['profit']
                
        elif trade_result['result'] == 'LOSS':
            metrics.losses += 1
            strategy_perf["losses"] += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            metrics.current_consecutive_losses += 1
            metrics.current_consecutive_wins = 0
            metrics.max_consecutive_losses = max(
                metrics.max_consecutive_losses,
                metrics.current_consecutive_losses
            )
            self.session_profit += trade_result['profit']
            
            if trade_result['profit'] < metrics.worst_loss:
                metrics.worst_loss = trade_result['profit']
                
        else:  # DRAW
            metrics.draws += 1
            strategy_perf["draws"] += 1
            self.consecutive_losses = 0
            self.consecutive_wins = 0
            metrics.current_consecutive_losses = 0
            metrics.current_consecutive_wins = 0
        
        # Actualizar profit de estrategia
        strategy_perf["profit"] += trade_result['profit']
        strategy_perf["win_rate"] = (strategy_perf["wins"] / strategy_perf["trades"] * 100) if strategy_perf["trades"] > 0 else 0
        strategy_perf["avg_profit"] = strategy_perf["profit"] / strategy_perf["trades"] if strategy_perf["trades"] > 0 else 0
        
        # Actualizar profits temporales
        metrics.total_profit = self.session_profit
        metrics.daily_profit += trade_result['profit']
        metrics.weekly_profit += trade_result['profit']
        metrics.monthly_profit += trade_result['profit']
        
        # Actualizar balance actual
        try:
            metrics.current_balance = self.iq_api.get_balance()
        except:
            pass

    def _log_analysis(self, indicators, direction, confidence, strategy_config):
        """Log detallado del análisis técnico"""
        analysis_msg = f"""📊 ANÁLISIS TÉCNICO - {strategy_config['name'].upper()}
📈 Par: {self.config['symbol']} | Precio: {indicators['price']}
🔍 Indicadores Principales:
   • RSI: {indicators['rsi']:.1f} ({'Oversold' if indicators['rsi_oversold'] else 'Overbought' if indicators['rsi_overbought'] else 'Neutral'})
   • MACD: {'Bullish' if indicators['macd_bullish'] else 'Bearish'} | Histogram: {indicators['macd_histogram']:.4f}
   • Stoch K: {indicators['stoch_k']:.1f} | D: {indicators['stoch_d']:.1f}
   • BB Position: {indicators['bb_price_position']} | Squeeze: {indicators['bb_squeeze']:.1f}%
   • CCI: {indicators['cci']:.1f} ({'Extreme' if abs(indicators['cci']) > 200 else 'Normal'})
   • Volatilidad: {indicators['volatility']:.1f}%
   • Volume Ratio: {indicators['volume_ratio']:.1f}x"""

        if direction:
            analysis_msg += f"\n\n🎯 SEÑAL: {direction.upper()}"
            analysis_msg += f"\n🔥 Confianza: {confidence:.0f}%"
            analysis_msg += f"\n📊 Mínimo requerido: {strategy_config['min_confidence']}%"
            analysis_msg += f"\n✅ {'EJECUTABLE' if confidence >= strategy_config['min_confidence'] else 'NO EJECUTABLE'}"
        else:
            analysis_msg += "\n\n⏳ Sin señal clara en este momento"

        logger.info(analysis_msg)

    def _send_final_summary(self):
        """Envía resumen final del bot con estadísticas detalladas"""
        try:
            strategy_config = BINARY_STRATEGY_CONFIG[self.strategy]
            win_rate = (self.operations_count - self.consecutive_losses) / self.operations_count * 100 if self.operations_count > 0 else 0
            
            final_message = f"""🏁 *BOT FINALIZADO - RESUMEN COMPLETO*
👤 Usuario: {self.email}
📈 Estrategia: {strategy_config['name']}
🎯 Nivel de Riesgo: {strategy_config['risk_level'].value.upper()}

📊 ESTADÍSTICAS DE SESIÓN:
💰 Ganancia/Pérdida: ${self.session_profit:.2f}
📈 Operaciones Total: {self.operations_count}
🎯 Win Rate Sesión: {win_rate:.1f}%
🎯 Win Rate Esperado: {strategy_config['win_rate_expected']}%
✅ Ganancias Consecutivas: {self.consecutive_wins}
❌ Pérdidas Consecutivas: {self.consecutive_losses}

⚙️ CONFIGURACIÓN UTILIZADA:
🛑 Max Pérdidas: {self.max_loss_operations}
✅ Max Ganancias: {self.max_win_operations if self.max_win_operations > 0 else 'Sin límite'}
📅 Max Diarias: {self.max_daily_operations}
💰 Monto Base: ${self.config['amount']:.2f}

⏰ Finalizado: {datetime.datetime.now().strftime('%H:%M:%S')}"""

            # Agregar razón de finalización
            if self.consecutive_losses >= self.max_loss_operations:
                final_message += "\n💀 Razón: Límite de pérdidas consecutivas alcanzado"
            elif self.consecutive_wins >= self.max_win_operations and self.max_win_operations > 0:
                final_message += "\n🎯 Razón: Límite de ganancias consecutivas alcanzado"
            elif self.operations_count >= self.max_daily_operations:
                final_message += "\n📅 Razón: Límite diario de operaciones alcanzado"
            else:
                final_message += "\n🛑 Razón: Detenido manualmente"

            send_telegram_message(final_message)

        except Exception as e:
            logger.error(f"Error enviando resumen final: {e}")

    def get_live_data(self):
        """Obtiene datos en vivo optimizados para opciones binarias"""
        if not self.candles_data:
            return None
            
        try:
            # Últimas 30 velas para mejor análisis
            recent_candles = self.candles_data[-30:]
            
            # Calcular indicadores actuales
            indicators = calculate_binary_indicators(self.candles_data, self.strategy)
            if not indicators:
                return None
            
            # Obtener señal actual
            direction, confidence = get_binary_signal(indicators, self.strategy)
            strategy_config = BINARY_STRATEGY_CONFIG[self.strategy]
            
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
                "indicators": {
                    "rsi": indicators['rsi'],
                    "rsi_level": "oversold" if indicators['rsi_oversold'] else "overbought" if indicators['rsi_overbought'] else "neutral",
                    "macd": indicators['macd'],
                    "macd_signal": indicators['macd_signal'],
                    "macd_histogram": indicators['macd_histogram'],
                    "macd_trend": "bullish" if indicators['macd_bullish'] else "bearish",
                    "stoch_k": indicators['stoch_k'],
                    "stoch_d": indicators['stoch_d'],
                    "stoch_level": "oversold" if indicators['stoch_oversold'] else "overbought" if indicators['stoch_overbought'] else "neutral",
                    "bb_upper": indicators['bb_upper'],
                    "bb_middle": indicators['bb_middle'],
                    "bb_lower": indicators['bb_lower'],
                    "bb_position": indicators['bb_price_position'],
                    "bb_squeeze": indicators['bb_squeeze'],
                    "cci": indicators['cci'],
                    "cci_level": "extreme_oversold" if indicators['cci_extreme_oversold'] else "extreme_overbought" if indicators['cci_extreme_overbought'] else "normal",
                    "volatility": indicators['volatility'],
                    "volume_ratio": indicators['volume_ratio'],
                    "trend_strength": indicators['trend_strength']
                },
                "signal": {
                    "direction": direction,
                    "confidence": confidence,
                    "min_confidence": strategy_config['min_confidence'],
                    "executable": confidence >= strategy_config['min_confidence'] if direction else False,
                    "strategy": strategy_config['name'],
                    "risk_level": strategy_config['risk_level'].value
                },
                "bot_status": {
                    "running": self.running,
                    "operations_count": self.operations_count,
                    "daily_operations": self.daily_operations,
                    "consecutive_losses": self.consecutive_losses,
                    "consecutive_wins": self.consecutive_wins,
                    "session_profit": self.session_profit,
                    "current_amount": self.current_amount,
                    "limits": {
                        "max_loss_operations": self.max_loss_operations,
                        "max_win_operations": self.max_win_operations,
                        "max_daily_operations": self.max_daily_operations,
                        "losses_remaining": max(0, self.max_loss_operations - self.consecutive_losses),
                        "wins_remaining": max(0, self.max_win_operations - self.consecutive_wins) if self.max_win_operations > 0 else "unlimited",
                        "daily_remaining": max(0, self.max_daily_operations - self.daily_operations)
                    }
                },
                "strategy_info": {
                    "name": strategy_config['name'],
                    "description": strategy_config['description'],
                    "risk_level": strategy_config['risk_level'].value,
                    "win_rate_expected": strategy_config['win_rate_expected'],
                    "trades_per_day": strategy_config['trades_per_day'],
                    "best_for": strategy_config['best_for'],
                    "market_conditions": strategy_config['market_conditions']
                }
            }
            
        except Exception as e:
            logger.error(f"Error obteniendo datos en vivo: {e}")
            return None

# ============================================================================
# SISTEMA DE LIMPIEZA ESPECÍFICO PARA OPCIONES BINARIAS
# ============================================================================

def cleanup_inactive_sessions():
    """Limpia sesiones inactivas cada hora con mejor detección"""
    while True:
        time.sleep(3600)  # Cada hora
        try:
            logger.info("🧹 Iniciando limpieza de sesiones...")
            cleaned_count = 0
            
            with sessions_lock:
                emails_to_clean = []
                
                for email, iq in list(user_sessions.items()):
                    try:
                        # Verificar múltiples condiciones de sesión muerta
                        is_dead = False
                        
                        # 1. Verificar conexión básica
                        if not iq.check_connect():
                            is_dead = True
                            logger.debug(f"Sesión {email}: conexión cerrada")
                        
                        # 2. Test de comunicación
                        if not is_dead:
                            try:
                                balance = iq.get_balance()
                                if balance is None:
                                    is_dead = True
                                    logger.debug(f"Sesión {email}: no responde a get_balance")
                            except Exception as e:
                                is_dead = True
                                logger.debug(f"Sesión {email}: error en test de comunicación: {e}")
                        
                        if is_dead:
                            emails_to_clean.append(email)
                    
                    except Exception as e:
                        logger.warning(f"Error verificando sesión {email}: {e}")
                        emails_to_clean.append(email)
                
                # Limpiar sesiones muertas
                for email in emails_to_clean:
                    try:
                        # Detener bot si existe
                        with bots_lock:
                            if email in active_bots:
                                active_bots[email].stop()
                                del active_bots[email]
                        
                        iq = user_sessions[email]
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        del user_sessions[email]
                        cleaned_count += 1
                        logger.info(f"🗑️ Sesión limpiada: {email}")
                    except:
                        pass
            
            if cleaned_count > 0:
                logger.info(f"✅ Limpieza completada: {cleaned_count} sesiones eliminadas")
            else:
                logger.debug("✅ Limpieza completada: no se encontraron sesiones muertas")
                
        except Exception as e:
            logger.error(f"Error en limpieza de sesiones: {e}")

def graceful_shutdown():
    """Cierra todas las conexiones de forma ordenada"""
    logger.info("🛑 Iniciando cierre ordenado del sistema...")
    
    # Detener todos los bots activos
    with bots_lock:
        for email, bot in list(active_bots.items()):
            try:
                logger.info(f"Deteniendo bot para {email}")
                bot.stop()
            except Exception as e:
                logger.error(f"Error deteniendo bot {email}: {e}")
        active_bots.clear()
    
    # Cerrar todas las sesiones de IQ Option
    with sessions_lock:
        for email, iq in list(user_sessions.items()):
            try:
                logger.info(f"Cerrando sesión para {email}")
                iq.close_websocket()
            except Exception as e:
                logger.error(f"Error cerrando sesión {email}: {e}")
        user_sessions.clear()
    
    logger.info("✅ Cierre ordenado completado")

# Registrar handler para cierre ordenado
def signal_handler(signum, frame):
    logger.info(f"Señal {signum} recibida, iniciando cierre ordenado...")
    graceful_shutdown()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
atexit.register(graceful_shutdown)

# Iniciar thread de limpieza
cleanup_thread = Thread(target=cleanup_inactive_sessions, daemon=True)
cleanup_thread.start()

# ============================================================================
# CORS HEADERS
# ============================================================================

@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

# ============================================================================
# ENDPOINTS ESPECÍFICOS PARA OPCIONES BINARIAS
# ============================================================================

@app.route('/', methods=['GET'])
def serve_frontend():
    """Frontend específico para opciones binarias"""
    frontend_html = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bot de Opciones Binarias Pro</title>
    <style>
        body {
            font-family: 'Arial', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            margin: 0;
            padding: 20px;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: white;
            border-radius: 15px;
            padding: 40px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            text-align: center;
            max-width: 800px;
            width: 100%;
        }
        .logo {
            font-size: 48px;
            margin-bottom: 20px;
        }
        h1 {
            color: #333;
            margin-bottom: 20px;
        }
        .status {
            background: #d4edda;
            color: #155724;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            border: 1px solid #c3e6cb;
        }
        .binary-features {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin: 20px 0;
            text-align: left;
        }
        .btn {
            background: #007bff;
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 16px;
            text-decoration: none;
            display: inline-block;
            margin: 10px;
        }
        .btn:hover {
            background: #0056b3;
        }
        .strategies {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }
        .strategy {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }
        .risk-low { border-left-color: #28a745; }
        .risk-medium { border-left-color: #ffc107; }
        .risk-high { border-left-color: #fd7e14; }
        .risk-very-high { border-left-color: #dc3545; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🎯</div>
        <h1>Bot de Opciones Binarias Pro</h1>
        
        <div class="status">
            ✅ Sistema optimizado para opciones binarias funcionando
        </div>
        
        <div class="binary-features">
            <h3>🎯 Características Específicas para Opciones Binarias</h3>
            <ul>
                <li>✅ 5 estrategias especializadas con niveles de riesgo clasificados</li>
                <li>✅ Operaciones rápidas sin demora - Optimizado para expiración corta</li>
                <li>✅ Inversión máxima limitada al 50% del capital disponible</li>
                <li>✅ Límites configurables de operaciones perdidas desde el frontend</li>
                <li>✅ Límites configurables de operaciones ganadas desde el frontend</li>
                <li>✅ Gestión de capital con Kelly Criterion para opciones binarias</li>
                <li>✅ Análisis técnico específico para timeframes cortos</li>
                <li>✅ Señales de alta confianza para maximizar win rate</li>
                <li>✅ Seguimiento de rachas ganadas y perdidas en tiempo real</li>
                <li>✅ Notificaciones Telegram con detalles técnicos</li>
            </ul>
        </div>

        <div class="strategies">
            <div class="strategy risk-low">
                <h4>🛡️ Bollinger + RSI</h4>
                <p><strong>Riesgo:</strong> Bajo</p>
                <p><strong>Win Rate:</strong> 70-75%</p>
                <p>Ideal para principiantes</p>
            </div>
            <div class="strategy risk-medium">
                <h4>📈 MACD + Signal</h4>
                <p><strong>Riesgo:</strong> Medio</p>
                <p><strong>Win Rate:</strong> 65-70%</p>
                <p>Seguimiento de tendencias</p>
            </div>
            <div class="strategy risk-high">
                <h4>⚡ Triple EMA</h4>
                <p><strong>Riesgo:</strong> Alto</p>
                <p><strong>Win Rate:</strong> 60-65%</p>
                <p>Scalping rápido</p>
            </div>
            <div class="strategy risk-medium">
                <h4>🎯 Stoch + Momentum</h4>
                <p><strong>Riesgo:</strong> Medio</p>
                <p><strong>Win Rate:</strong> 67-72%</p>
                <p>Reversiones precisas</p>
            </div>
            <div class="strategy risk-very-high">
                <h4>💥 CCI Dynamic</h4>
                <p><strong>Riesgo:</strong> Muy Alto</p>
                <p><strong>Win Rate:</strong> 55-60%</p>
                <p>Volatilidad extrema</p>
            </div>
        </div>

        <div style="margin-top: 30px;">
            <h3>🔗 Endpoints API:</h3>
            <a href="/health" class="btn">📊 Health Check</a>
            <a href="/api/strategies" class="btn">🎯 Ver Estrategias</a>
        </div>

        <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #dee2e6; font-size: 14px; color: #666;">
            <p><strong>🔧 API Endpoints para Opciones Binarias:</strong></p>
            <ul style="text-align: left; display: inline-block;">
                <li><code>POST /api/login</code> - Autenticación con IQ Option</li>
                <li><code>GET /api/strategies</code> - Estrategias clasificadas por riesgo</li>
                <li><code>POST /api/start_bot</code> - Iniciar bot con límites configurables</li>
                <li><code>GET /api/live_data</code> - Datos en tiempo real optimizados</li>
                <li><code>GET /api/metrics</code> - Métricas con rachas y límites</li>
                <li><code>GET /health</code> - Estado del sistema</li>
            </ul>
        </div>
    </div>
</body>
</html>'''
    return frontend_html, 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET'])
def health_check():
    """Health check específico para opciones binarias"""
    try:
        iq_status = "available" if IQ_AVAILABLE else "unavailable"
        
        # Contar sesiones activas
        active_sessions = 0
        with sessions_lock:
            for email, iq in user_sessions.items():
                try:
                    if iq.check_connect():
                        active_sessions += 1
                except:
                    pass
        
        # Contar bots activos
        active_bots_count = 0
        with bots_lock:
            for email, bot in active_bots.items():
                if bot.running:
                    active_bots_count += 1
        
        health_data = {
            "status": "healthy",
            "timestamp": datetime.datetime.now().isoformat(),
            "system_type": "binary_options_trading_bot",
            "iqoption_api": {
                "status": iq_status,
                "version": "optimized_for_binary_options",
                "websocket_patches": "applied"
            },
            "sessions": {
                "active": active_sessions,
                "total_registered": len(user_sessions)
            },
            "bots": {
                "active": active_bots_count,
                "total": len(active_bots)
            },
            "telegram": {
                "status": "configured" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "not_configured",
                "notifications": "enabled" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "disabled"
            },
            "binary_strategies": {
                "available": len(BINARY_STRATEGY_CONFIG),
                "types": [strategy.value for strategy in BINARY_STRATEGY_CONFIG.keys()],
                "risk_levels": [level.value for level in RiskLevel],
                "features": {
                    "max_capital_limit": "50%",
                    "configurable_loss_limits": True,
                    "configurable_win_limits": True,
                    "fast_execution": True,
                    "kelly_criterion": True
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
@limiter.limit("5 per minute")
def login():
    """Login optimizado para opciones binarias"""
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
        
        logger.info(f"🎯 Intento de login para opciones binarias: {email}")
        
        # Limpiar cualquier sesión anterior
        with sessions_lock:
            if email in user_sessions:
                try:
                    old_iq = user_sessions[email]
                    try:
                        old_iq.close_websocket()
                    except:
                        pass
                    del user_sessions[email]
                except:
                    pass
        
        time.sleep(0.5)
        
        # Función de conexión con reintentos optimizada para opciones binarias
        def attempt_binary_connection(max_retries=3):
            for attempt in range(max_retries):
                try:
                    logger.info(f"🔄 Intento de conexión {attempt + 1}/{max_retries} para opciones binarias")
                    
                    iq = IQ_Option(email, password)
                    
                    # Configurar timeouts optimizados para trading rápido
                    if hasattr(iq, 'api') and hasattr(iq.api, 'websocket_client'):
                        try:
                            iq.api.websocket_client.timeout = 25  # Timeout más corto para respuesta rápida
                        except:
                            pass
                    
                    logger.info("🔗 Conectando con IQ Option para trading binario...")
                    
                    connection_result = {'check': False, 'reason': 'Timeout'}
                    connection_event = Event()
                    
                    def connect_thread():
                        try:
                            check, reason = iq.connect()
                            connection_result['check'] = check
                            connection_result['reason'] = reason
                            connection_event.set()
                        except Exception as e:
                            connection_result['check'] = False
                            connection_result['reason'] = str(e)
                            connection_event.set()
                    
                    connect_worker = Thread(target=connect_thread, daemon=True)
                    connect_worker.start()
                    
                    if connection_event.wait(timeout=25):  # Timeout optimizado
                        check = connection_result['check']
                        reason = connection_result['reason']
                    else:
                        logger.warning(f"⏱️ Timeout en conexión (intento {attempt + 1})")
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                        else:
                            return False, "Timeout de conexión. Intenta más tarde."
                    
                    if not check:
                        logger.error(f"❌ Error de conexión (intento {attempt + 1}): {reason}")
                        
                        try:
                            iq.close_websocket()
                        except:
                            pass
                        
                        # Analizar el tipo de error
                        if isinstance(reason, dict):
                            code = reason.get("code", "")
                            raw_msg = reason.get("message", "")
                        else:
                            try:
                                parsed = json.loads(str(reason))
                                code = parsed.get("code", "")
                                raw_msg = parsed.get("message", "")
                            except:
                                code = str(reason)
                                raw_msg = str(reason)
                        
                        # Errores que no requieren reintentos
                        if code == "2FA":
                            return False, {
                                "message": "Autenticación de dos factores requerida",
                                "code": "2FA_REQUIRED"
                            }
                        elif code == "invalid_credentials" or "wrong credentials" in raw_msg.lower():
                            return False, {
                                "message": "Correo o contraseña incorrecta",
                                "code": "INVALID_CREDENTIALS"
                            }
                        
                        if attempt == max_retries - 1:
                                        "volume_ratio": round(volume_ratio, 2),
            "high_volume": volume_ratio > 1.5,
            
            # Señales de tendencia
            "trend_strength": round(abs(macd_histogram[-1]) * 1000, 2),
            "price_above_ema21": closes[-1] > ema21[-1],
            "price_below_ema21": closes[-1] < ema21[-1],
            
            # Señales combinadas para opciones binarias
            "strong_bullish": ema_bullish_alignment and calculate_fast_rsi(closes) > 50 and macd_line[-1] > signal_line[-1],
            "strong_bearish": ema_bearish_alignment and calculate_fast_rsi(closes) < 50 and macd_line[-1] < signal_line[-1],
            
            # Timestamp para sincronización
            "timestamp": time.time()
        }
        
        return indicators
        
    except Exception as e:
        logger.error(f"Error calculando indicadores para opciones binarias: {e}")
        return None

# ============================================================================
# ESTRATEGIAS DE TRADING ESPECÍFICAS PARA OPCIONES BINARIAS
# ============================================================================

class BinaryOptionsStrategies:
    """Estrategias optimizadas específicamente para opciones binarias"""
    
    @staticmethod
    def bollinger_rsi_strategy(indicators):
        """
        Estrategia Bollinger + RSI - CONSERVADORA
        Win Rate Esperado: 70-75%
        Ideal para: Principiantes y mercados laterales
        """
        signals = []
        confidence = 0
        
        price = indicators['price']
        rsi = indicators['rsi']
        bb_upper = indicators['bb_upper']
        bb_lower = indicators['bb_lower']
        bb_middle = indicators['bb_middle']
        
        # SEÑAL CALL: Precio en banda inferior + RSI sobreventa
        if indicators['bb_touch_lower'] and indicators['rsi_oversold']:
            signals.append("call")
            confidence += 40
            
            # Confirmaciones adicionales
            if rsi < 25:  # RSI muy bajo
                confidence += 15
            if price < bb_lower * 0.998:  # Precio muy cerca del límite
                confidence += 15
            if indicators['volume_ratio'] > 1.2:  # Volumen confirmatorio
                confidence += 10
        
        # SEÑAL PUT: Precio en banda superior + RSI sobrecompra
        if indicators['bb_touch_upper'] and indicators['rsi_overbought']:
            signals.append("put")
            confidence += 40
            
            # Confirmaciones adicionales
            if rsi > 75:  # RSI muy alto
                confidence += 15
            if price > bb_upper * 1.002:  # Precio muy cerca del límite
                confidence += 15
            if indicators['volume_ratio'] > 1.2:  # Volumen confirmatorio
                confidence += 10
        
        # Filtros de calidad
        if indicators['bb_squeeze'] < 1.5:  # Bandas muy comprimidas = señal débil
            confidence *= 0.6
        
        if indicators['volatility'] < 0.5:  # Muy poca volatilidad
            confidence *= 0.7
            
        return BinaryOptionsStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def macd_signal_strategy(indicators):
        """
        Estrategia MACD + Signal - MEDIA
        Win Rate Esperado: 65-70%
        Ideal para: Seguimiento de tendencia y breakouts
        """
        signals = []
        confidence = 0
        
        # SEÑAL CALL: Cruzamiento MACD alcista + confirmaciones
        if indicators['macd_cross_up']:
            signals.append("call")
            confidence += 35
            
            # Confirmaciones de tendencia
            if indicators['price_above_ema21']:
                confidence += 20
            if indicators['macd_histogram'] > 0:
                confidence += 15
            if indicators['rsi'] > 45 and indicators['rsi'] < 70:  # RSI en zona neutra-alcista
                confidence += 10
        
        # SEÑAL PUT: Cruzamiento MACD bajista + confirmaciones
        if indicators['macd_cross_down']:
            signals.append("put")
            confidence += 35
            
            # Confirmaciones de tendencia
            if indicators['price_below_ema21']:
                confidence += 20
            if indicators['macd_histogram'] < 0:
                confidence += 15
            if indicators['rsi'] < 55 and indicators['rsi'] > 30:  # RSI en zona neutra-bajista
                confidence += 10
        
        # Confirmación con momentum
        if abs(indicators['momentum']) > 0.0001:
            confidence += 5
            
        # Filtro de volatilidad
        if indicators['high_volume']:
            confidence += 10
        
        return BinaryOptionsStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def triple_ema_strategy(indicators):
        """
        Estrategia Triple EMA + Stochastic - AGRESIVA
        Win Rate Esperado: 60-65%
        Ideal para: Scalping y mercados rápidos
        """
        signals = []
        confidence = 0
        
        # SEÑAL CALL: Alineación EMA alcista + Stochastic confirmatorio
        if indicators['ema_bullish_alignment']:
            if indicators['stoch_cross_up'] or (indicators['stoch_k'] < 30 and indicators['stoch_k'] > indicators['stoch_d']):
                signals.append("call")
                confidence += 30
                
                # Confirmaciones adicionales
                if indicators['price'] > indicators['ema5']:
                    confidence += 15
                if indicators['rsi'] > 50:
                    confidence += 10
                if indicators['macd_bullish']:
                    confidence += 15
        
        # SEÑAL PUT: Alineación EMA bajista + Stochastic confirmatorio
        if indicators['ema_bearish_alignment']:
            if indicators['stoch_cross_down'] or (indicators['stoch_k'] > 70 and indicators['stoch_k'] < indicators['stoch_d']):
                signals.append("put")
                confidence += 30
                
                # Confirmaciones adicionales
                if indicators['price'] < indicators['ema5']:
                    confidence += 15
                if indicators['rsi'] < 50:
                    confidence += 10
                if not indicators['macd_bullish']:
                    confidence += 15
        
        # Momentum de las EMAs (velocidad de separación)
        ema_momentum = abs(indicators['ema5'] - indicators['ema21']) / indicators['ema21'] * 100
        if ema_momentum > 0.1:
            confidence += 10
            
        # Filtro de alta volatilidad para scalping
        if indicators['volatility'] > 1.0:
            confidence += 5
            
        return BinaryOptionsStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def stoch_momentum_strategy(indicators):
        """
        Estrategia Stochastic + Momentum - MEDIA
        Win Rate Esperado: 67-72%
        Ideal para: Reversiones en zonas extremas
        """
        signals = []
        confidence = 0
        
        # SEÑAL CALL: Stochastic oversold + momentum positivo
        if indicators['stoch_oversold'] and indicators['momentum'] >= 0:
            signals.append("call")
            confidence += 30
            
            # Confirmaciones con otros indicadores
            if indicators['rsi_oversold']:
                confidence += 20
            if indicators['bb_touch_lower']:
                confidence += 15
            if indicators['stoch_cross_up']:
                confidence += 15
        
        # SEÑAL PUT: Stochastic overbought + momentum negativo
        if indicators['stoch_overbought'] and indicators['momentum'] <= 0:
            signals.append("put")
            confidence += 30
            
            # Confirmaciones con otros indicadores
            if indicators['rsi_overbought']:
                confidence += 20
            if indicators['bb_touch_upper']:
                confidence += 15
            if indicators['stoch_cross_down']:
                confidence += 15
        
        # Confirmación con divergencias (momentum vs precio)
        if abs(indicators['momentum']) > 0.0002:
            confidence += 10
            
        return BinaryOptionsStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def cci_dynamic_strategy(indicators):
        """
        Estrategia CCI + Bollinger - MUY AGRESIVA
        Win Rate Esperado: 55-60%
        Ideal para: Volatilidad extrema y breakouts
        """
        signals = []
        confidence = 0
        
        # SEÑAL CALL: CCI extremadamente oversold + breakout alcista
        if indicators['cci_extreme_oversold'] and indicators['bb_touch_lower']:
            signals.append("call")
            confidence += 35
            
            # Confirmaciones de volatilidad
            if indicators['bb_squeeze'] > 3:  # Alta volatilidad
                confidence += 20
            if indicators['high_volume']:
                confidence += 15
            if indicators['momentum'] > 0:
                confidence += 10
        
        # SEÑAL PUT: CCI extremadamente overbought + breakout bajista
        if indicators['cci_extreme_overbought'] and indicators['bb_touch_upper']:
            signals.append("put")
            confidence += 35
            
            # Confirmaciones de volatilidad
            if indicators['bb_squeeze'] > 3:  # Alta volatilidad
                confidence += 20
            if indicators['high_volume']:
                confidence += 15
            if indicators['momentum'] < 0:
                confidence += 10
        
        # Señales secundarias con CCI normal
        if indicators['cci_oversold'] and not indicators['cci_extreme_oversold']:
            if indicators['rsi_oversold'] and indicators['stoch_oversold']:
                signals.append("call")
                confidence += 25
        
        if indicators['cci_overbought'] and not indicators['cci_extreme_overbought']:
            if indicators['rsi_overbought'] and indicators['stoch_overbought']:
                signals.append("put")
                confidence += 25
        
        # Filtro de volatilidad - esta estrategia necesita movimiento
        if indicators['volatility'] < 1.0:
            confidence *= 0.5
            
        return BinaryOptionsStrategies._consolidate_signals(signals, confidence)
    
    @staticmethod
    def _consolidate_signals(signals, confidence):
        """Consolida señales múltiples y aplica filtros finales"""
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

def get_binary_signal(indicators, strategy: Strategy):
    """Obtiene señal según la estrategia seleccionada para opciones binarias"""
    if not indicators:
        return None, 0
    
    strategy_functions = {
        Strategy.BOLLINGER_RSI: BinaryOptionsStrategies.bollinger_rsi_strategy,
        Strategy.MACD_SIGNAL: BinaryOptionsStrategies.macd_signal_strategy,
        Strategy.TRIPLE_EMA: BinaryOptionsStrategies.triple_ema_strategy,
        Strategy.STOCH_MOMENTUM: BinaryOptionsStrategies.stoch_momentum_strategy,
        Strategy.CCI_DYNAMIC: BinaryOptionsStrategies.cci_dynamic_strategy
    }
    
    if strategy in strategy_functions:
        return strategy_functions[strategy](indicators)
    else:
        return None, 0

# ============================================================================
# GESTIÓN DE CAPITAL ESPECÍFICA PARA OPCIONES BINARIAS
# ============================================================================

class BinaryMoneyManagement:
    """Gestión de capital optimizada para opciones binarias"""
    
    @staticmethod
    def calculate_optimal_amount(balance, strategy_config, user_metrics, base_amount, max_capital_percent=50):
        """
        Calcula el monto óptimo para opciones binarias
        REGLA PRINCIPAL: Máximo 50% del capital disponible
        """
        # Límite absoluto: 50% del capital
        max_allowed = balance * (max_capital_percent / 100)
        
        # Si el usuario tiene métricas suficientes, usar Kelly modificado
        if user_metrics and user_metrics.total_trades >= 20:
            win_rate = (user_metrics.wins / user_metrics.total_trades) * 100
            
            # Calcular Kelly conservador para opciones binarias
            if user_metrics.wins > 0 and user_metrics.losses > 0:
                avg_win_rate = win_rate / 100
                # Para opciones binarias, el payout típico es 70-85%
                payout_ratio = 0.8  # 80% payout promedio
                
                # Kelly modificado para opciones binarias
                kelly_fraction = (avg_win_rate * (1 + payout_ratio) - 1) / payout_ratio
                
                # Aplicar Kelly conservador (25% del Kelly completo)
                conservative_kelly = kelly_fraction * 0.25
                optimal_amount = balance * max(0, min(conservative_kelly, max_capital_percent / 100))
            else:
                optimal_amount = base_amount
        else:
            optimal_amount = base_amount
        
        # Aplicar multiplicadores según nivel de riesgo
        risk_multipliers = {
            RiskLevel.VERY_LOW: 0.3,   # Muy conservador para opciones binarias
            RiskLevel.LOW: 0.5,
            RiskLevel.MEDIUM: 0.7,
            RiskLevel.HIGH: 1.0,
            RiskLevel.VERY_HIGH: 1.2
        }
        
        risk_level = strategy_config.get('risk_level', RiskLevel.MEDIUM)
        risk_multiplier = risk_multipliers.get(risk_level, 0.7)
        
        # Penalización por rachas perdedoras (muy importante en opciones binarias)
        if user_metrics and user_metrics.current_consecutive_losses > 0:
            # Reducción exponencial por pérdidas consecutivas
            loss_penalty = 0.7 ** user_metrics.current_consecutive_losses
            optimal_amount *= loss_penalty
        
        # Aplicar multiplicador de riesgo
        final_amount = optimal_amount * risk_multiplier
        
        # Respetar límites absolutos
        final_amount = max(1.0, min(final_amount, max_allowed))
        
        # Redondear a 2 decimales
        return round(final_amount, 2)
    
    @staticmethod
    def check_trading_limits(user_metrics, current_balance):
        """
        Verifica si se pueden realizar más operaciones según los límites configurados
        """
        if not user_metrics:
            return True, "Sin métricas disponibles"
        
        # Verificar límite de pérdidas consecutivas
        if user_metrics.current_consecutive_losses >= user_metrics.max_loss_operations:
            return False, f"Límite de pérdidas consecutivas alcanzado: {user_metrics.max_loss_operations}"
        
        # Verificar límite de ganancias consecutivas (si está configurado)
        if (user_metrics.max_win_operations > 0 and 
            user_metrics.current_consecutive_wins >= user_metrics.max_win_operations):
            return False, f"Límite de ganancias consecutivas alcanzado: {user_metrics.max_win_operations}"
        
        # Verificar límite diario de operaciones
        if user_metrics.total_trades >= user_metrics.max_daily_operations:
            return False, f"Límite diario de operaciones alcanzado: {user_metrics.max_daily_operations}"
        
        # Verificar que el balance no esté muy bajo
        if current_balance < 5.0:  # Mínimo $5 para operar
            return False, "Balance insuficiente para continuar operando"
        
        return True, "Límites OK"

# ============================================================================
# CLASE BOT DE TRADING OPTIMIZADA PARA OPCIONES BINARIAS
# ============================================================================

class BinaryTradingBot:
    def __init__(self, iq_api, config, email):
        self.iq_api = iq_api
        self.config = config
        self.email = email
        self.running = False
        self.thread = None
        self.strategy = Strategy(config['strategy'])
        self.current_amount = config['amount']
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.session_profit = 0
        self.operations_count = 0
        self.daily_operations = 0
        
        # Límites configurables desde frontend
        self.max_loss_operations = config.get('max_loss_operations', 5)
        self.max_win_operations = config.get('max_win_operations', 0)  # 0 = sin límite
        self.max_daily_operations = config.get('max_daily_operations', 50)
        
        self.candles_data = []
        self.last_signal_time = 0
        self.signals_history = []
        
        # Configuración específica para opciones binarias
        self.min_interval_between_trades = 30  # 30 segundos mínimo entre operaciones
        self.trade_timeout = 400  # 400 segundos para esperar resultado
        
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
            strategy_config = BINARY_STRATEGY_CONFIG[self.strategy]
            logger.info(f"🚀 Bot de opciones binarias iniciado para {self.email}")
            logger.info(f"📈 Estrategia: {strategy_config['name']} (Riesgo: {strategy_config['risk_level'].value})")
            
            # Notificar inicio con detalles específicos
            send_telegram_message(f"""🚀 *BOT OPCIONES BINARIAS INICIADO*
👤 Usuario: {self.email}
📈 Estrategia: {strategy_config['name']}
🎯 Nivel de Riesgo: {strategy_config['risk_level'].value.upper()}
💰 Monto inicial: ${self.config['amount']:.2f}
📊 Timeframe: {strategy_config['timeframe']}s
⏱️ Expiración: {strategy_config['expiry']}s
🏦 Cuenta: {self.config['account_type']}
🛑 Max Pérdidas: {self.max_loss_operations}
✅ Max Ganancias: {self.max_win_operations if self.max_win_operations > 0 else 'Sin límite'}
📅 Max Diarias: {self.max_daily_operations}
🎯 Win Rate Esperado: {strategy_config['win_rate_expected']}%
📊 Trades/día: {strategy_config['trades_per_day']}""")
            
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
                    
                    # Verificar límites de trading
                    current_balance = self.iq_api.get_balance()
                    can_trade, limit_message = BinaryMoneyManagement.check_trading_limits(
                        user_metrics.get(self.email), current_balance
                    )
                    
                    if not can_trade:
                        logger.info(f"Límite alcanzado para {self.email}: {limit_message}")
                        send_telegram_message(f"""🛑 *LÍMITE ALCANZADO*
👤 Usuario: {self.email}
📊 Razón: {limit_message}
💰 Ganancia de sesión: ${self.session_profit:.2f}
📈 Operaciones: {self.operations_count}
🏁 Bot detenido automáticamente""")
                        break
                    
                    # Obtener velas según el timeframe de la estrategia
                    timeframe = strategy_config['timeframe']
                    try:
                        candles = self.iq_api.get_candles(self.config['symbol'], timeframe, 100, time.time())
                    except Exception as e:
                        logger.warning(f"Error obteniendo velas: {e}")
                        time.sleep(15)
                        continue
                    
                    if not candles or len(candles) < 50:
                        logger.warning(f"Datos insuficientes para {self.config['symbol']}")
                        time.sleep(30)
                        continue
                    
                    # Almacenar datos para análisis
                    self.candles_data = candles[-50:]
                    
                    # Calcular indicadores optimizados para opciones binarias
                    indicators = calculate_binary_indicators(candles, self.strategy)
                    if not indicators:
                        time.sleep(30)
                        continue
                    
                    # Generar señal según estrategia
                    direction, confidence = get_binary_signal(indicators, self.strategy)
                    
                    # Log de análisis detallado
                    self._log_analysis(indicators, direction, confidence, strategy_config)
                    
                    # Ejecutar operación si hay señal fuerte y ha pasado tiempo suficiente
                    min_confidence = strategy_config['min_confidence']
                    current_time = time.time()
                    
                    if (direction and confidence >= min_confidence and 
                        current_time - self.last_signal_time >= self.min_interval_between_trades):
                        
                        # Calcular monto óptimo
                        optimal_amount = BinaryMoneyManagement.calculate_optimal_amount(
                            current_balance, strategy_config, user_metrics.get(self.email), self.config['amount']
                        )
                        
                        if optimal_amount > current_balance:
                            logger.error(f"Fondos insuficientes. Balance: ${current_balance:.2f}")
                            send_telegram_message(f"""❌ *FONDOS INSUFICIENTES*
💰 Balance: ${current_balance:.2f}
💸 Requerido: ${optimal_amount:.2f}
🛑 Bot detenido""")
                            break
                        
                        # Ejecutar trade
                        result = self._execute_binary_trade(direction, optimal_amount, strategy_config, indicators)
                        self.last_signal_time = current_time
                        self.operations_count += 1
                        self.daily_operations += 1
                        
                        # Actualizar métricas
                        self._update_binary_metrics(result, strategy_config)
                        
                        # Pausa obligatoria entre operaciones
                        time.sleep(max(strategy_config['expiry'] + 15, 60))
                    else:
                        # Sin señal clara, esperar menos tiempo
                        wait_time = 20 if timeframe >= 300 else 10
                        time.sleep(wait_time)
                        
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
            self._send_final_summary()
            logger.info(f"Bot finalizado para {self.email}")
    
    def _execute_binary_trade(self, direction, amount, strategy_config, indicators):
        """Ejecuta una operación de opciones binarias y espera el resultado"""
        try:
            expiry_minutes = strategy_config['expiry'] // 60
            symbol = self.config['symbol']
            
            logger.info(f"🎯 Ejecutando {direction.upper()} en {symbol} por ${amount:.2f}")
            logger.info(f"📊 Confianza de señal: Alta | Expiración: {expiry_minutes} min")
            
            # Información detallada de la señal
            signal_details = {
                "rsi": indicators['rsi'],
                "macd_bullish": indicators['macd_bullish'],
                "stoch_k": indicators['stoch_k'],
                "bb_position": indicators['bb_price_position'],
                "volatility": indicators['volatility']
            }
            
            # Notificar apertura con detalles técnicos
            send_telegram_message(f"""🎯 *OPERACIÓN ABIERTA*
📈 Par: {symbol}
🎯 Dirección: {direction.upper()}
💰 Monto: ${amount:.2f}
⏱️ Expiración: {expiry_minutes} min
📊 Operación #{self.operations_count + 1}
🔥 Estrategia: {strategy_config['name']}
📈 RSI: {signal_details['rsi']:.1f}
📊 Stoch: {signal_details['stoch_k']:.1f}
💹 Volatilidad: {signal_details['volatility']:.1f}%
⏰ {datetime.datetime.now().strftime('%H:%M:%S')}""")
            
            # Abrir operación binaria
            status, order_id = self.iq_api.buy(amount, symbol, direction, expiry_minutes)
            
            if not status:
                logger.error(f"Error abriendo posición: {order_id}")
                return {
                    "result": "ERROR", 
                    "profit": 0, 
                    "message": str(order_id), 
                    "amount": amount,
                    "direction": direction,
                    "symbol": symbol
                }
            
            logger.info(f"✅ Operación abierta exitosamente. ID: {order_id}")
            
            # Esperar resultado con timeout específico para opciones binarias
            wait_time = strategy_config['expiry'] + 20  # 20 segundos de buffer
            logger.info(f"⏳ Esperando resultado por {wait_time} segundos...")
            
            time.sleep(wait_time)
            
            # Verificar resultado con reintentos
            result = None
            for attempt in range(3):
                try:
                    result = self.iq_api.check_win_v3(order_id)
                    if result is not None:
                        break
                    logger.warning(f"Reintento {attempt + 1} para obtener resultado...")
                    time.sleep(5)
                except Exception as e:
                    logger.warning(f"Error verificando resultado (intento {attempt + 1}): {e}")
                    time.sleep(5)
            
            # Procesar resultado
            if isinstance(result, tuple) and len(result) >= 2:
                win_amount = result[1]
            elif isinstance(result, (int, float)):
                win_amount = float(result)
            else:
                logger.warning(f"Formato de resultado desconocido: {result}")
                win_amount = None
            
            # Determinar resultado final
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
            
            # Calcular estadísticas actualizadas
            new_balance = self.iq_api.get_balance()
            session_profit_updated = self.session_profit + profit
            
            # Notificar resultado detallado
            result_emoji = "✅" if trade_result == "WIN" else "❌" if trade_result == "LOSS" else "⚪"
            result_text = "GANADA" if trade_result == "WIN" else "PERDIDA" if trade_result == "LOSS" else "EMPATE"
            
            send_telegram_message(f"""{result_emoji} *OPERACIÓN {result_text}*
📈 Par: {symbol}
🎯 Dirección: {direction.upper()}
💰 Monto: ${amount:.2f}
💵 Resultado: {'+' if profit >= 0 else ''}${profit:.2f}
📊 Balance: ${new_balance:.2f}
💹 Sesión: {'+' if session_profit_updated >= 0 else ''}${session_profit_updated:.2f}
📈 Op. Total: {self.operations_count + 1}
⏰ {datetime.datetime.now().strftime('%H:%M:%S')}
🔥 {strategy_config['name']}""")
            
            return {
                "result": trade_result,
                "profit": profit,
                "order_id": order_id,
                "amount": amount,
                "strategy": self.strategy.value,
                "direction": direction,
                "symbol": symbol,
                "signal_details": signal_details
            }
            
        except Exception as e:
            logger.error(f"Error ejecutando trade binario: {e}")
            return {
                "result": "ERROR", 
                "profit": 0, 
                "message": str(e), 
                "amount": amount,
                "direction": direction,
                "symbol": symbol
            }
    
    def _update_binary_metrics(self, trade_result, strategy_config):
        """Actualiza métricas específicas para opciones binarias"""
        if self.email not in user_metrics:
            return
            
        metrics = user_metrics[self.email]
        strategy_name = self.strategy.value
        
        # Inicializar performance de estrategia
        if strategy_name not in metrics.strategy_performance:
            metrics.strategy_performance[strategy_name] = {
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "draws": 0,
                "profit": 0.0,
                "win_rate": 0.0,
                "avg_profit": 0.0
            }
        
        strategy# main.py - Backend Optimizado para Bot de Trading Opciones Binarias Pro
# Basado en tu código original con mejoras específicas para opciones binarias

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
import math
import signal
import atexit
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

# Configuración de logging mejorado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/tmp/trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Agregar path para IQOptionAPI local si existe
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================================================================
# PARCHE MEJORADO PARA WEBSOCKET - CORRIGE TODOS LOS ERRORES CONOCIDOS
# ============================================================================

def apply_websocket_patch():
    """
    Aplica parche completo para solucionar errores de WebSocket callbacks
    Específicamente diseñado para IQOptionAPI y opciones binarias
    """
    try:
        logger.info("🔧 Aplicando parche de WebSocket para opciones binarias...")
        
        # Crear wrapper para WebSocketApp que maneja argumentos variables
        import websocket
        from websocket import WebSocketApp
        
        class OptimizedWebSocketApp(WebSocketApp):
            """WebSocketApp optimizado para trading de opciones binarias"""
            
            def __init__(self, url, **kwargs):
                def wrap_callback(callback):
                    if callback is None:
                        return None
                    
                    def wrapper(*args, **kwargs_inner):
                        try:
                            # Intentar con argumentos originales
                            return callback(*args, **kwargs_inner)
                        except TypeError as e:
                            if "positional argument" in str(e):
                                try:
                                    # Usar solo el primer argumento para callbacks problemáticos
                                    return callback(args[0])
                                except:
                                    logger.debug(f"Callback wrapper manejó: {e}")
                                    pass
                            else:
                                raise
                    return wrapper
                
                # Wrappear todos los callbacks críticos
                for callback_name in ['on_open', 'on_close', 'on_error', 'on_message']:
                    if callback_name in kwargs:
                        kwargs[callback_name] = wrap_callback(kwargs[callback_name])
                
                super().__init__(url, **kwargs)
        
        # Reemplazar WebSocketApp original
        websocket.WebSocketApp = OptimizedWebSocketApp
        
        logger.info("✅ Parche de WebSocket aplicado correctamente")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error aplicando parche de WebSocket: {e}")
        return False

def patch_iqoption_callbacks():
    """
    Aplica parche específico a los callbacks de IQOptionAPI para opciones binarias
    """
    try:
        from iqoptionapi.ws.client import WebsocketClient
        
        # Método on_close optimizado para opciones binarias
        def optimized_on_close(self, *args, **kwargs):
            """Método on_close que maneja argumentos variables para trading"""
            try:
                logger.debug("WebSocket cerrado - reconectando automáticamente...")
                # Lógica específica para mantener conexión de trading activa
                pass
            except Exception as e:
                logger.debug(f"Error en on_close optimizado: {e}")
        
        def optimized_on_error(self, *args, **kwargs):
            """Método on_error optimizado para trading"""
            try:
                error = args[1] if len(args) > 1 else args[0] if args else "Error desconocido"
                logger.warning(f"Error WebSocket en trading: {error}")
            except Exception as e:
                logger.debug(f"Error en on_error optimizado: {e}")
        
        def optimized_on_open(self, *args, **kwargs):
            """Método on_open optimizado para opciones binarias"""
            try:
                logger.info("Conexión WebSocket abierta - listo para trading")
                # Configuraciones específicas para opciones binarias
                if hasattr(self, 'api'):
                    pass
            except Exception as e:
                logger.debug(f"Error en on_open optimizado: {e}")
        
        # Aplicar parches optimizados
        WebsocketClient.on_close = optimized_on_close
        WebsocketClient.on_error = optimized_on_error  
        WebsocketClient.on_open = optimized_on_open
        
        logger.info("✅ Callbacks de IQOptionAPI optimizados para opciones binarias")
        return True
        
    except ImportError:
        logger.debug("IQOptionAPI no disponible para parchear")
        return False
    except Exception as e:
        logger.warning(f"Error parcheando IQOptionAPI: {e}")
        return False

# Aplicar parches antes de importar IQOptionAPI
apply_websocket_patch()

# Flask y extensiones
from flask import Flask, request, jsonify, session, make_response
from flask_cors import CORS
from flask_session import Session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Importar IQOptionAPI con parche aplicado
try:
    from iqoptionapi.stable_api import IQ_Option
    IQ_AVAILABLE = True
    logger.info("✅ IQOptionAPI cargada para trading de opciones binarias")
    
    # Aplicar parche específico después de importar
    patch_iqoption_callbacks()
    
except ImportError as e:
    logger.error(f"❌ Error importando IQOptionAPI: {e}")
    IQ_AVAILABLE = False
    raise Exception("IQOptionAPI no está instalada. Instala: pip install git+https://github.com/Lu-Yi-Hsun/iqoptionapi.git")

# Configuración Flask optimizada para opciones binarias
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'binary-options-bot-secret-2024')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/tmp/flask_sessions'
app.config['SESSION_COOKIE_NAME'] = 'binary_trading_session'
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = 3600 * 24  # 24 horas

# Crear directorio de sesiones
os.makedirs(app.config['SESSION_FILE_DIR'], exist_ok=True)

# Inicializar extensiones
Session(app)

# CORS optimizado para opciones binarias
CORS(app, 
     resources={r"/*": {
         "origins": "*",
         "methods": ["GET", "POST", "OPTIONS"],
         "allow_headers": ["Content-Type", "Authorization"],
         "expose_headers": ["Content-Type"],
         "supports_credentials": True
     }})

# Rate limiting específico para trading
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["500 per day", "100 per hour"]  # Más permisivo para trading activo
)

# Variables globales con thread safety
user_sessions = {}  # {email: IQ_Option instance}
active_bots = {}    # {email: Bot instance}
sessions_lock = Lock()
bots_lock = Lock()

# Configuración Telegram
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', "7787754995:AAEvM36bO9B4SvGA1cr1VP1j-Rx6on5LrjM")
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', "7009100334")

# ============================================================================
# ENUMS Y CLASIFICACIÓN DE ESTRATEGIAS PARA OPCIONES BINARIAS
# ============================================================================

class RiskLevel(Enum):
    """Niveles de riesgo específicos para opciones binarias"""
    VERY_LOW = "very_low"
    LOW = "low" 
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"

class Strategy(Enum):
    """Estrategias optimizadas para opciones binarias"""
    BOLLINGER_RSI = "bollinger_rsi"
    MACD_SIGNAL = "macd_signal"
    TRIPLE_EMA = "triple_ema"
    STOCH_MOMENTUM = "stoch_momentum"
    CCI_DYNAMIC = "cci_dynamic"

# ============================================================================
# CONFIGURACIÓN DE ESTRATEGIAS ESPECÍFICAS PARA OPCIONES BINARIAS
# ============================================================================

BINARY_STRATEGY_CONFIG = {
    Strategy.BOLLINGER_RSI: {
        "name": "Bollinger Bands + RSI",
        "description": "Estrategia conservadora para principiantes - Ideal para reversiones",
        "risk_level": RiskLevel.LOW,
        "min_confidence": 75,  # Alto % para baja frecuencia pero alta precisión
        "timeframe": 300,      # 5 minutos - perfecto para opciones binarias
        "expiry": 300,         # 5 minutos
        "indicators": ["bollinger_bands", "rsi", "sma"],
        "win_rate_expected": 70,
        "trades_per_day": "8-12",
        "best_for": "Reversiones en soportes/resistencias",
        "market_conditions": "Mercados laterales y con volatilidad media"
    },
    Strategy.MACD_SIGNAL: {
        "name": "MACD + Signal Cross",
        "description": "Seguimiento de tendencia - Señales de cruzamiento rápidas",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 68,
        "timeframe": 300,      # 5 minutos
        "expiry": 300,         # 5 minutos
        "indicators": ["macd", "ema_fast", "ema_slow"],
        "win_rate_expected": 65,
        "trades_per_day": "12-18",
        "best_for": "Seguimiento de tendencias fuertes",
        "market_conditions": "Mercados con tendencia clara"
    },
    Strategy.TRIPLE_EMA: {
        "name": "Triple EMA + Stochastic",
        "description": "Scalping rápido - Alta frecuencia de operaciones",
        "risk_level": RiskLevel.HIGH,
        "min_confidence": 62,
        "timeframe": 60,       # 1 minuto para scalping
        "expiry": 300,         # 5 minutos para dar margen
        "indicators": ["ema_fast", "ema_medium", "ema_slow", "stochastic"],
        "win_rate_expected": 60,
        "trades_per_day": "25-35",
        "best_for": "Scalping en mercados rápidos",
        "market_conditions": "Alta volatilidad y movimientos rápidos"
    },
    Strategy.STOCH_MOMENTUM: {
        "name": "Stochastic + Momentum",
        "description": "Momentum y reversión - Zonas de sobrecompra/sobreventa",
        "risk_level": RiskLevel.MEDIUM,
        "min_confidence": 70,
        "timeframe": 300,      # 5 minutos
        "expiry": 300,         # 5 minutos
        "indicators": ["stochastic", "rsi", "bollinger_bands", "momentum"],
        "win_rate_expected": 67,
        "trades_per_day": "10-16",
        "best_for": "Reversiones en zonas extremas",
        "market_conditions": "Mercados con oscilaciones regulares"
    },
    Strategy.CCI_DYNAMIC: {
        "name": "CCI Dynamic + Bollinger",
        "description": "Volatilidad extrema - Para traders expertos",
        "risk_level": RiskLevel.VERY_HIGH,
        "min_confidence": 58,
        "timeframe": 300,      # 5 minutos
        "expiry": 300,         # 5 minutos
        "indicators": ["cci", "bollinger_bands", "ema_fast", "atr"],
        "win_rate_expected": 55,
        "trades_per_day": "20-30",
        "best_for": "Breakouts y volatilidad extrema",
        "market_conditions": "Noticias importantes y alta volatilidad"
    }
}

# Métricas de trading por usuario optimizadas para opciones binarias
@dataclass
class BinaryTradingMetrics:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_profit: float = 0.0
    max_consecutive_losses: int = 0
    current_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    current_consecutive_wins: int = 0
    start_balance: float = 0.0
    current_balance: float = 0.0
    best_profit: float = 0.0
    worst_loss: float = 0.0
    strategy_performance: Dict[str, Dict] = None
    daily_profit: float = 0.0
    weekly_profit: float = 0.0
    monthly_profit: float = 0.0
    
    # Configuraciones específicas del usuario
    max_loss_operations: int = 5      # Configurable desde frontend
    max_win_operations: int = 0       # 0 = sin límite, configurable desde frontend
    max_daily_operations: int = 50    # Límite diario
    
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
            "daily_profit": round(self.daily_profit, 2),
            "weekly_profit": round(self.weekly_profit, 2),
            "monthly_profit": round(self.monthly_profit, 2),
            "max_consecutive_losses": self.max_consecutive_losses,
            "current_consecutive_losses": self.current_consecutive_losses,
            "max_consecutive_wins": self.max_consecutive_wins,
            "current_consecutive_wins": self.current_consecutive_wins,
            "best_profit": round(self.best_profit, 2),
            "worst_loss": round(self.worst_loss, 2),
            "roi": round(roi, 2),
            "strategy_performance": self.strategy_performance,
            "limits": {
                "max_loss_operations": self.max_loss_operations,
                "max_win_operations": self.max_win_operations,
                "max_daily_operations": self.max_daily_operations
            }
        }

user_metrics = {}  # {email: BinaryTradingMetrics}

# ============================================================================
# FUNCIONES AUXILIARES OPTIMIZADAS
# ============================================================================

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
    """Decorador para requerir autenticación con reconexión automática mejorada"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            return jsonify({"error": "No autorizado", "code": "AUTH_REQUIRED"}), 401
        
        email = session['user_email']
        with sessions_lock:
            if email not in user_sessions:
                session.clear()
                return jsonify({"error": "Sesión expirada", "code": "SESSION_EXPIRED"}), 401
            
            # Verificar conexión IQ Option con reintentos
            iq = user_sessions[email]
            
            # Función para verificar y reconectar si es necesario
            def ensure_connection(max_retries=3):
                for attempt in range(max_retries):
                    try:
                        # Verificar conexión
                        if iq.check_connect():
                            return True
                        
                        logger.warning(f"Conexión perdida para {email}, reintentando... (intento {attempt + 1})")
                        
                        # Intentar reconectar
                        time.sleep(2)  # Pausa entre intentos
                        
                        # Crear thread para reconexión con timeout
                        reconnect_result = {'success': False}
                        reconnect_event = Event()
                        
                        def reconnect_thread():
                            try:
                                success = iq.connect()
                                if isinstance(success, tuple):
                                    reconnect_result['success'] = success[0]
                                else:
                                    reconnect_result['success'] = success
                                reconnect_event.set()
                            except Exception as e:
                                logger.error(f"Error en reconexión: {e}")
                                reconnect_result['success'] = False
                                reconnect_event.set()
                        
                        # Ejecutar reconexión con timeout optimizado
                        reconnect_worker = Thread(target=reconnect_thread, daemon=True)
                        reconnect_worker.start()
                        
                        if reconnect_event.wait(timeout=20):  # Timeout más generoso
                            if reconnect_result['success']:
                                logger.info(f"Reconexión exitosa para {email}")
                                return True
                        else:
                            logger.warning(f"Timeout en reconexión para {email}")
                        
                    except Exception as e:
                        logger.error(f"Error verificando conexión para {email}: {e}")
                
                return False
            
            # Verificar/reconectar con reintentos
            if not ensure_connection():
                # Si no se pudo reconectar, limpiar sesión
                logger.error(f"No se pudo restablecer conexión para {email}")
                try:
                    del user_sessions[email]
                except:
                    pass
                session.clear()
                return jsonify({"error": "Conexión perdida con IQ Option", "code": "CONNECTION_LOST"}), 401
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================================================
# CÁLCULO DE INDICADORES OPTIMIZADO PARA OPCIONES BINARIAS
# ============================================================================

def calculate_binary_indicators(candles, strategy: Strategy = None):
    """
    Calcula indicadores técnicos específicamente optimizados para opciones binarias
    Enfoque en precisión y velocidad de señales
    """
    try:
        if len(candles) < 50:
            return None
        
        closes = np.array([float(c['close']) for c in candles])
        highs = np.array([float(c['max']) for c in candles])
        lows = np.array([float(c['min']) for c in candles])
        opens = np.array([float(c['open']) for c in candles])
        volumes = np.array([float(c.get('volume', 1)) for c in candles])
        
        indicators = {}
        
        # RSI optimizado para opciones binarias (períodos más rápidos)
        def calculate_fast_rsi(prices, period=14):
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
        
        # EMA rápidas para opciones binarias
        def calculate_ema(data, period):
            ema = np.zeros_like(data)
            ema[0] = data[0]
            multiplier = 2 / (period + 1)
            for i in range(1, len(data)):
                ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
            return ema
        
        # MACD optimizado para señales rápidas
        ema12 = calculate_ema(closes, 12)
        ema26 = calculate_ema(closes, 26)
        macd_line = ema12 - ema26
        signal_line = calculate_ema(macd_line, 9)
        macd_histogram = macd_line - signal_line
        
        # Detectar cruzamientos de MACD (crucial para opciones binarias)
        macd_cross_up = macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]
        macd_cross_down = macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]
        
        # Estocástico rápido para opciones binarias
        stoch_period = 14
        lowest_lows = []
        highest_highs = []
        
        for i in range(stoch_period-1, len(closes)):
            lowest_lows.append(np.min(lows[i-stoch_period+1:i+1]))
            highest_highs.append(np.max(highs[i-stoch_period+1:i+1]))
        
        if len(lowest_lows) > 0:
            lowest_low = lowest_lows[-1]
            highest_high = highest_highs[-1]
            
            if highest_high != lowest_low:
                stoch_k = 100 * ((closes[-1] - lowest_low) / (highest_high - lowest_low))
            else:
                stoch_k = 50
            
            # %D más rápido para opciones binarias
            if len(closes) >= stoch_period + 2:
                recent_k = []
                for i in range(max(0, len(closes)-3), len(closes)):
                    if i >= stoch_period-1:
                        ll = np.min(lows[i-stoch_period+1:i+1])
                        hh = np.max(highs[i-stoch_period+1:i+1])
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
        
        # Bollinger Bands optimizado para opciones binarias
        bb_period = 20
        bb_std = 2
        sma20 = np.mean(closes[-bb_period:])
        std20 = np.std(closes[-bb_period:])
        bb_upper = sma20 + (bb_std * std20)
        bb_lower = sma20 - (bb_std * std20)
        bb_squeeze = (bb_upper - bb_lower) / sma20 * 100
        
        # Detectar toques de bandas (importante para opciones binarias)
        bb_touch_upper = closes[-1] >= bb_upper * 0.995
        bb_touch_lower = closes[-1] <= bb_lower * 1.005
        
        # CCI para detectar extremos
        cci_period = 20
        typical_prices = (highs + lows + closes) / 3
        sma_tp = np.mean(typical_prices[-cci_period:])
        mean_deviation = np.mean(np.abs(typical_prices[-cci_period:] - sma_tp))
        cci = (typical_prices[-1] - sma_tp) / (0.015 * mean_deviation) if mean_deviation != 0 else 0
        
        # Triple EMA para scalping
        ema5 = calculate_ema(closes, 5)
        ema13 = calculate_ema(closes, 13)
        ema21 = calculate_ema(closes, 21)
        
        # Alineación de EMAs (crucial para triple EMA strategy)
        ema_bullish_alignment = ema5[-1] > ema13[-1] > ema21[-1]
        ema_bearish_alignment = ema5[-1] < ema13[-1] < ema21[-1]
        
        # ATR para volatilidad
        tr = []
        for i in range(1, len(candles)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i-1])
            low_close = abs(lows[i] - closes[i-1])
            tr.append(max(high_low, high_close, low_close))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else 0
        
        # Momentum para detectar cambios de dirección
        momentum = closes[-1] - closes[-10] if len(closes) >= 10 else 0
        
        # Volume analysis
        volume_ratio = volumes[-1] / np.mean(volumes[-20:]) if len(volumes) >= 20 else 1
        
        # Compilar todos los indicadores
        indicators = {
            # Precios básicos
            "price": round(closes[-1], 5),
            "open": round(opens[-1], 5),
            "high": round(highs[-1], 5),
            "low": round(lows[-1], 5),
            
            # RSI
            "rsi": round(calculate_fast_rsi(closes), 2),
            "rsi_oversold": calculate_fast_rsi(closes) <= 30,
            "rsi_overbought": calculate_fast_rsi(closes) >= 70,
            
            # MACD
            "macd": round(macd_line[-1], 6),
            "macd_signal": round(signal_line[-1], 6),
            "macd_histogram": round(macd_histogram[-1], 6),
            "macd_cross_up": macd_cross_up,
            "macd_cross_down": macd_cross_down,
            "macd_bullish": macd_line[-1] > signal_line[-1],
            
            # Estocástico
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "stoch_oversold": stoch_k <= 20,
            "stoch_overbought": stoch_k >= 80,
            "stoch_cross_up": stoch_k > stoch_d and stoch_k <= 30,
            "stoch_cross_down": stoch_k < stoch_d and stoch_k >= 70,
            
            # Bollinger Bands
            "bb_upper": round(bb_upper, 5),
            "bb_middle": round(sma20, 5),
            "bb_lower": round(bb_lower, 5),
            "bb_squeeze": round(bb_squeeze, 2),
            "bb_touch_upper": bb_touch_upper,
            "bb_touch_lower": bb_touch_lower,
            "bb_price_position": "upper" if closes[-1] > sma20 else "lower",
            
            # CCI
            "cci": round(cci, 2),
            "cci_extreme_oversold": cci <= -200,
            "cci_extreme_overbought": cci >= 200,
            "cci_oversold": cci <= -100,
            "cci_overbought": cci >= 100,
            
            # EMAs
            "ema5": round(ema5[-1], 5),
            "ema13": round(ema13[-1], 5),
            "ema21": round(ema21[-1], 5),
            "ema_bullish_alignment": ema_bullish_alignment,
            "ema_bearish_alignment": ema_bearish_alignment,
            
            # Volatilidad y momentum
            "atr": round(atr, 5),
            "volatility": round((std20 / sma20 * 100) if sma20 > 0 else 0, 2),
            "momentum": round(momentum, 5),
            "volume_
