"""
Sistema de monitoreo y alertas para el bot
"""

import logging
import requests
import json
from datetime import datetime, timedelta
from typing import Dict, Optional
import threading
import time

logger = logging.getLogger(__name__)

class BotMonitor:
    def __init__(self, telegram_token: str, telegram_chat_id: str):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.monitoring_active = False
        self.alerts_sent = {}
        self.metrics = {
            'total_operations': 0,
            'successful_operations': 0,
            'failed_operations': 0,
            'total_profit': 0,
            'uptime_start': datetime.now(),
            'errors': []
        }
    
    def start_monitoring(self):
        """Inicia el monitoreo del sistema"""
        self.monitoring_active = True
        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()
        logger.info("Sistema de monitoreo iniciado")
    
    def stop_monitoring(self):
        """Detiene el monitoreo"""
        self.monitoring_active = False
        logger.info("Sistema de monitoreo detenido")
    
    def _monitor_loop(self):
        """Loop principal de monitoreo"""
        while self.monitoring_active:
            try:
                # Verificar métricas cada 5 minutos
                self._check_system_health()
                time.sleep(300)
            except Exception as e:
                logger.error(f"Error en monitoreo: {str(e)}")
    
    def _check_system_health(self):
        """Verifica la salud del sistema"""
        # Verificar tasa de éxito
        if self.metrics['total_operations'] > 10:
            success_rate = (self.metrics['successful_operations'] / 
                          self.metrics['total_operations']) * 100
            
            if success_rate < 40:
                self._send_alert(
                    'low_success_rate',
                    f"⚠️ Tasa de éxito baja: {success_rate:.1f}%",
                    cooldown_hours=1
                )
        
        # Verificar errores recientes
        recent_errors = [e for e in self.metrics['errors'] 
                        if e['timestamp'] > datetime.now() - timedelta(hours=1)]
        
        if len(recent_errors) > 5:
            self._send_alert(
                'high_error_rate',
                f"🚨 Alto número de errores: {len(recent_errors)} en la última hora",
                cooldown_hours=1
            )
    
    def record_operation(self, success: bool, profit: float):
        """Registra una operación"""
        self.metrics['total_operations'] += 1
        
        if success:
            self.metrics['successful_operations'] += 1
        else:
            self.metrics['failed_operations'] += 1
        
        self.metrics['total_profit'] += profit
        
        # Alertar si hay muchas pérdidas consecutivas
        if not success:
            self._check_consecutive_losses()
    
    def record_error(self, error_type: str, error_message: str):
        """Registra un error"""
        self.metrics['errors'].append({
            'type': error_type,
            'message': error_message,
            'timestamp': datetime.now()
        })
        
        # Mantener solo los últimos 100 errores
        if len(self.metrics['errors']) > 100:
            self.metrics['errors'] = self.metrics['errors'][-100:]
    
    def _check_consecutive_losses(self):
        """Verifica pérdidas consecutivas recientes"""
        # Esta es una versión simplificada
        # En producción, deberías trackear las operaciones individuales
        loss_rate = (self.metrics['failed_operations'] / 
                    max(1, self.metrics['total_operations'])) * 100
        
        if loss_rate > 70 and self.metrics['total_operations'] > 5:
            self._send_alert(
                'high_loss_rate',
                f"🔴 Alta tasa de pérdidas: {loss_rate:.1f}%",
                cooldown_hours=2
            )
    
    def _send_alert(self, alert_type: str, message: str, cooldown_hours: int = 1):
        """Envía una alerta con cooldown"""
        # Verificar cooldown
        if alert_type in self.alerts_sent:
            last_sent = self.alerts_sent[alert_type]
            if datetime.now() - last_sent < timedelta(hours=cooldown_hours):
                return
        
        # Enviar alerta
        self.send_telegram_message(message)
        self.alerts_sent[alert_type] = datetime.now()
    
    def send_telegram_message(self, message: str):
        """Envía mensaje a Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            data = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            requests.post(url, data=data)
        except Exception as e:
            logger.error(f"Error enviando mensaje Telegram: {str(e)}")
    
    def get_status_report(self) -> str:
        """Genera reporte de estado"""
        uptime = datetime.now() - self.metrics['uptime_start']
        hours = uptime.total_seconds() / 3600
        
        success_rate = 0
        if self.metrics['total_operations'] > 0:
            success_rate = (self.metrics['successful_operations'] / 
                          self.metrics['total_operations']) * 100
        
        report = f"""
📊 <b>Reporte de Estado del Bot</b>

⏱ Tiempo activo: {hours:.1f} horas
📈 Operaciones totales: {self.metrics['total_operations']}
✅ Exitosas: {self.metrics['successful_operations']}
❌ Fallidas: {self.metrics['failed_operations']}
💰 Profit total: ${self.metrics['total_profit']:.2f}
📊 Tasa de éxito: {success_rate:.1f}%
🔧 Errores recientes: {len(self.metrics['errors'])}
"""
        return report
    
    def send_daily_report(self):
        """Envía reporte diario"""
        report = self.get_status_report()
        self.send_telegram_message(report)

# Funciones para integración con el bot principal

def create_monitor(telegram_token: str, telegram_chat_id: str) -> BotMonitor:
    """Crea una instancia del monitor"""
    monitor = BotMonitor(telegram_token, telegram_chat_id)
    monitor.start_monitoring()
    return monitor

# Monitor global
bot_monitor: Optional[BotMonitor] = None

def init_monitoring(telegram_token: str, telegram_chat_id: str):
    """Inicializa el sistema de monitoreo"""
    global bot_monitor
    bot_monitor = create_monitor(telegram_token, telegram_chat_id)
    
    # Programar reporte diario
    def daily_report():
        while True:
            time.sleep(86400)  # 24 horas
            if bot_monitor:
                bot_monitor.send_daily_report()
    
    threading.Thread(target=daily_report, daemon=True).start()
    
    return bot_monitor

def get_monitor() -> Optional[BotMonitor]:
    """Obtiene la instancia del monitor"""
    return bot_monitor
