"""
Utilidades y funciones auxiliares
"""

import re
import hashlib
import hmac
from datetime import datetime, time
from typing import Tuple, Optional
import pytz

def validate_email(email: str) -> bool:
    """Valida formato de email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_amount(amount: float, balance: float) -> Tuple[bool, str]:
    """Valida el monto de operación"""
    if amount <= 0:
        return False, "El monto debe ser mayor a 0"
    
    if amount > balance * 0.5:
        return False, "El monto no puede exceder el 50% del balance"
    
    if amount < 1:
        return False, "El monto mínimo es $1"
    
    return True, "OK"

def is_market_open(symbol: str) -> bool:
    """Verifica si el mercado está abierto para un símbolo"""
    now = datetime.now(pytz.UTC)
    
    # Forex está abierto 24/5
    if '/' in symbol and '-OTC' not in symbol:
        # Cerrado desde viernes 21:00 UTC hasta domingo 21:00 UTC
        if now.weekday() == 4 and now.hour >= 21:  # Viernes
            return False
        elif now.weekday() == 5:  # Sábado
            return False
        elif now.weekday() == 6 and now.hour < 21:  # Domingo
            return False
    
    # OTC siempre está disponible
    if '-OTC' in symbol:
        return True
    
    # Para otros activos, verificar horario específico
    # Por ahora, asumir que están abiertos en horario de trading
    if now.weekday() < 5:  # Lunes a Viernes
        return True
    
    return False

def calculate_position_size(balance: float, risk_percentage: float, stop_loss: float = None) -> float:
    """Calcula el tamaño de posición basado en gestión de riesgo"""
    # Por defecto, usar el porcentaje de riesgo del balance
    position_size = balance * (risk_percentage / 100)
    
    # Si hay stop loss definido, ajustar según Kelly Criterion
    if stop_loss:
        # Simplificado para opciones binarias
        win_rate = 0.6  # Asumir 60% win rate
        reward_risk_ratio = 0.85  # Payout típico de opciones binarias
        
        # Kelly percentage
        kelly = (win_rate * reward_risk_ratio - (1 - win_rate)) / reward_risk_ratio
        kelly = max(0, min(kelly, 0.25))  # Limitar entre 0 y 25%
        
        position_size = balance * kelly
    
    return round(position_size, 2)

def generate_session_token(user_id: str, timestamp: str) -> str:
    """Genera un token de sesión seguro"""
    secret = "your-secret-key"  # En producción, usar variable de entorno
    message = f"{user_id}:{timestamp}"
    
    return hmac.new(
        secret.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

def format_currency(amount: float) -> str:
    """Formatea un monto como moneda"""
    return f"${amount:,.2f}"

def calculate_martingale_amount(base_amount: float, losses: int, multiplier: float, max_multiplier: float = 10) -> float:
    """Calcula el monto según Martingala modificada"""
    if losses == 0:
        return base_amount
    
    # Aplicar multiplicador con límite
    amount = base_amount * (multiplier ** losses)
    max_amount = base_amount * max_multiplier
    
    return min(amount, max_amount)

def get_time_until_market_open() -> Optional[str]:
    """Obtiene tiempo hasta que abra el mercado"""
    now = datetime.now(pytz.UTC)
    
    # Si es fin de semana
    if now.weekday() >= 5:
        # Calcular tiempo hasta domingo 21:00 UTC
        days_until_sunday = 6 - now.weekday()
        if days_until_sunday == 0 and now.hour >= 21:
            days_until_sunday = 7
        
        target = now.replace(hour=21, minute=0, second=0, microsecond=0)
        target = target + timedelta(days=days_until_sunday)
        
        delta = target - now
        hours = delta.total_seconds() // 3600
        minutes = (delta.total_seconds() % 3600) // 60
        
        return f"{int(hours)}h {int(minutes)}m"
    
    return None

def sanitize_symbol(symbol: str) -> str:
    """Sanitiza un símbolo para uso seguro"""
    # Remover caracteres especiales excepto / y -
    return re.sub(r'[^A-Z0-9/-]', '', symbol.upper())

def calculate_profit_factor(trades: list) -> float:
    """Calcula el factor de beneficio"""
    gross_profit = sum(t['profit'] for t in trades if t['profit'] > 0)
    gross_loss = abs(sum(t['profit'] for t in trades if t['profit'] < 0))
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0
    
    return gross_profit / gross_loss

def get_risk_color(risk_level: str) -> str:
    """Obtiene color hexadecimal para nivel de riesgo"""
    colors = {
        'very_low': '#10b981',   # Verde
        'low': '#22d3ee',        # Cyan
        'medium': '#f59e0b',     # Amarillo
        'high': '#ef4444',       # Rojo
        'very_high': '#ec4899'   # Rosa
    }
    return colors.get(risk_level, '#64748b')

def calculate_sharpe_ratio(returns: list, risk_free_rate: float = 0.02) -> float:
    """Calcula el ratio de Sharpe"""
    if not returns:
        return 0
    
    import numpy as np
    
    returns_array = np.array(returns)
    avg_return = np.mean(returns_array)
    std_return = np.std(returns_array)
    
    if std_return == 0:
        return 0
    
    return (avg_return - risk_free_rate) / std_return

def format_duration(seconds: int) -> str:
    """Formatea duración en formato legible"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
