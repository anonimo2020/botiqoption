"""
Gestión de base de datos para almacenar estadísticas y configuraciones
"""

import redis
import json
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
    
    def save_trade(self, user_id: str, trade_data: dict):
        """Guarda información de una operación"""
        try:
            # Clave para trades del usuario
            key = f"trades:{user_id}"
            
            # Añadir timestamp si no existe
            if 'timestamp' not in trade_data:
                trade_data['timestamp'] = datetime.now().isoformat()
            
            # Guardar en lista (últimos 1000 trades)
            self.redis.lpush(key, json.dumps(trade_data))
            self.redis.ltrim(key, 0, 999)
            
            # Actualizar estadísticas
            self._update_user_stats(user_id, trade_data)
            
        except Exception as e:
            logger.error(f"Error guardando trade: {str(e)}")
    
    def _update_user_stats(self, user_id: str, trade_data: dict):
        """Actualiza estadísticas del usuario"""
        stats_key = f"stats:{user_id}"
        
        # Obtener estadísticas actuales
        stats = self.get_user_stats(user_id)
        
        # Actualizar contadores
        stats['total_trades'] += 1
        
        if trade_data.get('result', 0) > 0:
            stats['wins'] += 1
        else:
            stats['losses'] += 1
        
        stats['total_profit'] += trade_data.get('profit', 0)
        
        # Actualizar por estrategia
        strategy = trade_data.get('strategy', 'unknown')
        if strategy not in stats['strategy_performance']:
            stats['strategy_performance'][strategy] = {
                'trades': 0,
                'wins': 0,
                'profit': 0
            }
        
        stats['strategy_performance'][strategy]['trades'] += 1
        if trade_data.get('result', 0) > 0:
            stats['strategy_performance'][strategy]['wins'] += 1
        stats['strategy_performance'][strategy]['profit'] += trade_data.get('profit', 0)
        
        # Calcular win rate
        if stats['total_trades'] > 0:
            stats['win_rate'] = round((stats['wins'] / stats['total_trades']) * 100, 2)
        
        # Guardar estadísticas actualizadas
        self.redis.set(stats_key, json.dumps(stats))
    
    def get_user_stats(self, user_id: str) -> dict:
        """Obtiene estadísticas del usuario"""
        stats_key = f"stats:{user_id}"
        stats_data = self.redis.get(stats_key)
        
        if stats_data:
            return json.loads(stats_data)
        
        # Estadísticas por defecto
        return {
            'total_trades': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0,
            'total_profit': 0,
            'strategy_performance': {},
            'last_updated': datetime.now().isoformat()
        }
    
    def get_recent_trades(self, user_id: str, limit: int = 50) -> List[dict]:
        """Obtiene las operaciones recientes del usuario"""
        key = f"trades:{user_id}"
        trades_data = self.redis.lrange(key, 0, limit - 1)
        
        trades = []
        for trade_json in trades_data:
            try:
                trades.append(json.loads(trade_json))
            except:
                pass
        
        return trades
    
    def save_bot_config(self, user_id: str, config: dict):
        """Guarda la configuración del bot del usuario"""
        key = f"bot_config:{user_id}"
        config['last_updated'] = datetime.now().isoformat()
        self.redis.set(key, json.dumps(config))
    
    def get_bot_config(self, user_id: str) -> Optional[dict]:
        """Obtiene la configuración del bot del usuario"""
        key = f"bot_config:{user_id}"
        config_data = self.redis.get(key)
        
        if config_data:
            return json.loads(config_data)
        
        return None
    
    def get_leaderboard(self, period: str = 'all', limit: int = 10) -> List[dict]:
        """Obtiene el ranking de usuarios"""
        # TODO: Implementar leaderboard por períodos
        # Por ahora, obtener todos los usuarios y ordenar por profit
        
        users = []
        for key in self.redis.scan_iter("stats:*"):
            try:
                stats = json.loads(self.redis.get(key))
                user_id = key.decode().split(':')[1]
                users.append({
                    'user_id': user_id,
                    'total_profit': stats['total_profit'],
                    'win_rate': stats['win_rate'],
                    'total_trades': stats['total_trades']
                })
            except:
                pass
        
        # Ordenar por profit
        users.sort(key=lambda x: x['total_profit'], reverse=True)
        
        return users[:limit]
    
    def save_market_data(self, symbol: str, data: dict):
        """Guarda datos de mercado para análisis"""
        key = f"market:{symbol}"
        data['timestamp'] = datetime.now().isoformat()
        
        # Guardar con expiración de 1 hora
        self.redis.setex(key, 3600, json.dumps(data))
    
    def get_market_data(self, symbol: str) -> Optional[dict]:
        """Obtiene datos de mercado guardados"""
        key = f"market:{symbol}"
        data = self.redis.get(key)
        
        if data:
            return json.loads(data)
        
        return None
    
    def increment_daily_operations(self, user_id: str) -> int:
        """Incrementa y retorna el contador de operaciones diarias"""
        today = datetime.now().strftime('%Y-%m-%d')
        key = f"daily_ops:{user_id}:{today}"
        
        # Incrementar contador
        count = self.redis.incr(key)
        
        # Establecer expiración a medianoche
        self.redis.expire(key, 86400)
        
        return count
    
    def get_daily_operations(self, user_id: str) -> int:
        """Obtiene el número de operaciones del día"""
        today = datetime.now().strftime('%Y-%m-%d')
        key = f"daily_ops:{user_id}:{today}"
        
        count = self.redis.get(key)
        return int(count) if count else 0

# Instancia global
db_manager = None

def init_database(redis_url: str):
    """Inicializa el gestor de base de datos"""
    global db_manager
    db_manager = DatabaseManager(redis_url)
    return db_manager

def get_database() -> DatabaseManager:
    """Obtiene la instancia del gestor de base de datos"""
    return db_manager
