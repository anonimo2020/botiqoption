#!/usr/bin/env python3
"""
Script de depuración para problemas de login con IQ Option
Úsalo para verificar que las credenciales funcionan correctamente
"""

import sys
import logging
import json
import time

# Configurar logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_direct_iqoption_connection(email, password):
    """Prueba conexión directa con IQ Option"""
    print("\n" + "="*50)
    print("TEST 1: Conexión directa con IQOptionAPI")
    print("="*50)
    
    try:
        # Intentar importar y aplicar parches
        try:
            from iqapi_websocket_fix import SafeIQOption, patch_iqoptionapi
            print("✅ Módulo de parches encontrado")
            patch_iqoptionapi()
            print("✅ Parches aplicados")
            api = SafeIQOption(email, password)
            print("✅ Usando SafeIQOption con parches")
        except Exception as e:
            print(f"⚠️ No se pudo usar SafeIQOption: {e}")
            from iqoptionapi.stable_api import IQ_Option
            api = IQ_Option(email, password)
            print("✅ Usando IQ_Option estándar")
        
        print(f"\n📧 Email: {email}")
        print("🔐 Conectando...")
        
        # Conectar
        check, reason = api.connect()
        
        print(f"\n📊 Resultado de conexión:")
        print(f"   - Éxito: {check}")
        print(f"   - Razón: {reason}")
        print(f"   - Tipo de razón: {type(reason)}")
        
        if not check:
            # Intentar parsear el error
            print("\n❌ Error de conexión. Analizando...")
            
            if isinstance(reason, str):
                print(f"   - Mensaje raw: {reason}")
                
                # Intentar parsear como JSON
                try:
                    error_data = json.loads(reason)
                    print(f"   - Código: {error_data.get('code', 'N/A')}")
                    print(f"   - Mensaje: {error_data.get('message', 'N/A')}")
                except:
                    print("   - No es JSON válido")
            
            return False, reason
        
        print("\n✅ Conexión exitosa!")
        
        # Obtener información adicional
        print("\n📋 Obteniendo información del usuario...")
        
        # Balance
        try:
            balance = api.get_balance()
            print(f"   - Balance: ${balance}")
        except Exception as e:
            print(f"   - Error obteniendo balance: {e}")
        
        # Perfil
        try:
            time.sleep(1)  # Dar tiempo a la API
            profile = api.get_profile_ansyc()
            print(f"   - Tipo de perfil: {type(profile)}")
            
            if isinstance(profile, dict):
                print(f"   - User ID: {profile.get('user_id', 'N/A')}")
                print(f"   - Claves disponibles: {list(profile.keys())[:5]}...")
            else:
                print(f"   - Perfil no es dict: {profile}")
        except Exception as e:
            print(f"   - Error obteniendo perfil: {e}")
        
        # SSID
        try:
            if hasattr(api.api, 'ssid'):
                print(f"   - SSID: {api.api.ssid[:20]}...")
        except:
            pass
        
        return True, api
        
    except Exception as e:
        print(f"\n❌ Error general: {e}")
        import traceback
        traceback.print_exc()
        return False, str(e)

def test_backend_connection(base_url, email, password):
    """Prueba conexión a través del backend"""
    print("\n" + "="*50)
    print("TEST 2: Conexión a través del backend")
    print("="*50)
    
    try:
        import requests
        
        print(f"🌐 Backend URL: {base_url}")
        print(f"📧 Email: {email}")
        
        # Primero verificar health
        print("\n🏥 Verificando health del backend...")
        health_url = f"{base_url}/health"
        try:
            response = requests.get(health_url, timeout=10)
            print(f"   - Status: {response.status_code}")
            print(f"   - Response: {response.json()}")
        except Exception as e:
            print(f"   - ❌ Error: {e}")
            return False
        
        # Intentar login
        print("\n🔐 Intentando login...")
        login_url = f"{base_url}/api/login"
        data = {
            "email": email,
            "password": password
        }
        
        session = requests.Session()
        response = session.post(
            login_url, 
            json=data,
            headers={
                'Content-Type': 'application/json',
                'Origin': 'https://iqoptionbot.ct.ws'
            },
            timeout=30
        )
        
        print(f"\n📊 Resultado del login:")
        print(f"   - Status: {response.status_code}")
        print(f"   - Headers: {dict(response.headers)}")
        
        try:
            result = response.json()
            print(f"   - Response: {json.dumps(result, indent=2)}")
            
            if result.get('success'):
                print("\n✅ Login exitoso en el backend!")
                print(f"   - User ID: {result['user']['id']}")
                print(f"   - Balance: ${result['user']['balance']}")
            else:
                print(f"\n❌ Login fallido: {result.get('message', 'Error desconocido')}")
                
        except Exception as e:
            print(f"   - Error parseando respuesta: {e}")
            print(f"   - Respuesta raw: {response.text}")
        
        return response.status_code == 200
        
    except Exception as e:
        print(f"\n❌ Error conectando al backend: {e}")
        return False

def main():
    print("\n🔧 IQ Option Login Debugger")
    print("="*50)
    
    # Verificar argumentos
    if len(sys.argv) < 3:
        print("Uso: python debug_login.py <email> <password> [backend_url]")
        print("Ejemplo: python debug_login.py user@email.com password123 https://iqoption-bot.onrender.com")
        sys.exit(1)
    
    email = sys.argv[1]
    password = sys.argv[2]
    backend_url = sys.argv[3] if len(sys.argv) > 3 else "http://localhost:5000"
    
    # Test 1: Conexión directa
    success, result = test_direct_iqoption_connection(email, password)
    
    # Test 2: Conexión backend (solo si el directo funciona)
    if success:
        test_backend_connection(backend_url, email, password)
    else:
        print("\n⚠️ Saltando test de backend debido a fallo en conexión directa")
    
    print("\n" + "="*50)
    print("🏁 Tests completados")
    print("="*50)

if __name__ == "__main__":
    main()
