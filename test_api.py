"""
Script de prueba para verificar el funcionamiento del backend
"""

import requests
import json
import time

# Configuración
BASE_URL = "http://localhost:5000"  # Cambiar a tu URL de Render cuando esté desplegado

def test_health():
    """Prueba el endpoint de health check"""
    print("Testing health check...")
    response = requests.get(f"{BASE_URL}/health")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print("-" * 50)

def test_strategies():
    """Prueba obtener estrategias"""
    print("Testing strategies endpoint...")
    response = requests.get(f"{BASE_URL}/api/strategies")
    print(f"Status: {response.status_code}")
    if response.status_code == 200:
        strategies = response.json()['strategies']
        print(f"Found {len(strategies)} strategies:")
        for strategy in strategies:
            print(f"  - {strategy['name']} (Risk: {strategy['risk_level']})")
    print("-" * 50)

def test_login(email: str, password: str):
    """Prueba el login"""
    print("Testing login...")
    data = {
        "email": email,
        "password": password
    }
    
    session = requests.Session()
    response = session.post(f"{BASE_URL}/api/login", json=data)
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        if result['success']:
            print(f"Login successful!")
            print(f"User: {result['user']['name']}")
            print(f"Balance: ${result['user']['balance']}")
            return session
        else:
            print(f"Login failed: {result['message']}")
    else:
        print(f"Error: {response.text}")
    
    print("-" * 50)
    return None

def test_symbols(session):
    """Prueba obtener símbolos"""
    print("Testing symbols endpoint...")
    response = session.get(f"{BASE_URL}/api/symbols")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        symbols = response.json()['symbols']
        print(f"Found {len(symbols)} symbols:")
        for symbol in symbols[:5]:  # Mostrar solo los primeros 5
            print(f"  - {symbol['name']} ({symbol['type']})")
    print("-" * 50)

def test_balance(session):
    """Prueba obtener balance"""
    print("Testing balance endpoint...")
    response = session.get(f"{BASE_URL}/api/balance")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"Balance: ${data['balance']}")
        print(f"Metrics: {data['metrics']}")
    print("-" * 50)

def test_optimal_amount(session, strategy: str = "conservative_rsi"):
    """Prueba calcular monto óptimo"""
    print("Testing optimal amount calculation...")
    data = {
        "strategy": strategy,
        "base_amount": 1
    }
    
    response = session.post(f"{BASE_URL}/api/optimal_amount", json=data)
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"Optimal amount: ${result['optimal_amount']}")
        print(f"Risk level: {result['risk_level']}")
    print("-" * 50)

def test_start_bot(session, symbol: str = "EURUSD", strategy: str = "conservative_rsi"):
    """Prueba iniciar el bot"""
    print("Testing bot start...")
    data = {
        "symbol": symbol,
        "amount": 1,
        "strategy": strategy,
        "account_type": "PRACTICE",
        "max_operations": 5,
        "max_loss_operations": 3
    }
    
    response = session.post(f"{BASE_URL}/api/start_bot", json=data)
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"Bot started successfully!")
        print(f"Strategy: {result['strategy_info']['name']}")
        return True
    else:
        print(f"Error: {response.json()}")
        return False
    print("-" * 50)

def test_bot_status(session):
    """Prueba obtener estado del bot"""
    print("Testing bot status...")
    response = session.get(f"{BASE_URL}/api/bot_status")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        status = response.json()
        print(f"Bot running: {status.get('running', False)}")
        if status.get('running'):
            print(f"Operations: {status['operations_count']}")
            print(f"Session profit: ${status['session_profit']}")
    print("-" * 50)

def test_live_data(session):
    """Prueba obtener datos en vivo"""
    print("Testing live data...")
    response = session.get(f"{BASE_URL}/api/live_data")
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        if data.get('candles'):
            print(f"Got {len(data['candles'])} candles")
            last_candle = data['candles'][-1]
            print(f"Last price: {last_candle['close']}")
        if data.get('indicators'):
            print(f"RSI: {data['indicators'].get('rsi', 'N/A')}")
    print("-" * 50)

def test_stop_bot(session):
    """Pru
