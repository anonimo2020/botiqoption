"""
Configuración y utilidades de seguridad
"""

import os
import secrets
from functools import wraps
from flask import request, jsonify, session
import hashlib
import time
from typing import Dict, Optional

# Rate limiting storage
request_counts: Dict[str, list] = {}

def require_auth(f):
    """Decorador para requerir autenticación"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            return jsonify({'error': 'No autorizado'}), 401
        return f(*args, **kwargs)
    return decorated_function

def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    """Decorador para limitar rate de requests"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Obtener IP del cliente
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            
            # Limpiar requests antiguos
            current_time = time.time()
            if client_ip in request_counts:
                request_counts[client_ip] = [
                    req_time for req_time in request_counts[client_ip]
                    if current_time - req_time < window_seconds
                ]
            
            # Verificar límite
            if client_ip not in request_counts:
                request_counts[client_ip] = []
            
            if len(request_counts[client_ip]) >= max_requests:
                return jsonify({
                    'error': 'Demasiadas solicitudes. Por favor intenta más tarde.'
                }), 429
            
            # Registrar request
            request_counts[client_ip].append(current_time)
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def validate_request_data(required_fields: list):
    """Decorador para validar datos del request"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            data = request.get_json()
            
            if not data:
                return jsonify({'error': 'No se proporcionaron datos'}), 400
            
            # Verificar campos requeridos
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                return jsonify({
                    'error': f'Campos requeridos faltantes: {", ".join(missing_fields)}'
                }), 400
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def generate_api_key() -> str:
    """Genera una API key segura"""
    return secrets.token_urlsafe(32)

def hash_password(password: str) -> str:
    """Hash de contraseña (no usado para IQ Option, solo para admin)"""
    salt = os.environ.get('PASSWORD_SALT', 'default-salt')
    return hashlib.sha256(f"{password}{salt}".encode()).hexdigest()

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verifica firma de webhook"""
    expected_signature = hashlib.sha256(
        f"{secret}{payload.decode()}".encode()
    ).hexdigest()
    
    return secrets.compare_digest(signature, expected_signature)

def sanitize_input(text: str, max_length: int = 255) -> str:
    """Sanitiza entrada de usuario"""
    # Remover caracteres de control
    text = ''.join(char for char in text if ord(char) >= 32)
    
    # Limitar longitud
    text = text[:max_length]
    
    # Escapar HTML
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    
    return text.strip()

def validate_trading_params(data: dict) -> tuple[bool, Optional[str]]:
    """Valida parámetros de trading"""
    # Validar símbolo
    symbol = data.get('symbol', '')
    if not symbol or len(symbol) > 20:
        return False, "Símbolo inválido"
    
    # Validar monto
    try:
        amount = float(data.get('amount', 0))
        if amount <= 0 or amount > 10000:
            return False, "Monto debe estar entre $0.01 y $10,000"
    except (ValueError, TypeError):
        return False, "Monto inválido"
    
    # Validar estrategia
    strategy = data.get('strategy', '')
    valid_strategies = [
        'conservative_rsi', 'macd_cross', 'bollinger_bounce',
        'multi_indicator', 'momentum_scalper'
    ]
    if strategy not in valid_strategies:
        return False, "Estrategia inválida"
    
    # Validar tipo de cuenta
    account_type = data.get('account_type', '')
    if account_type not in ['PRACTICE', 'REAL']:
        return False, "Tipo de cuenta inválido"
    
    # Validar límites
    try:
        max_operations = int(data.get('max_operations', 0))
        if max_operations < 0 or max_operations > 1000:
            return False, "Límite de operaciones inválido"
        
        max_loss = int(data.get('max_loss_operations', 5))
        if max_loss < 1 or max_loss > 20:
            return False, "Límite de pérdidas debe estar entre 1 y 20"
    except (ValueError, TypeError):
        return False, "Límites inválidos"
    
    return True, None

# Headers de seguridad
def add_security_headers(response):
    """Añade headers de seguridad a las respuestas"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    return response

# Configuración de sesión segura
def configure_secure_session(app):
    """Configura la sesión de forma segura"""
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=24),
        SESSION_COOKIE_NAME='iqbot_session',
        SESSION_COOKIE_PATH='/',
        SESSION_COOKIE_DOMAIN=None  # Se ajustará según el dominio
    )
