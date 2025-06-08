"""
Wrapper para corregir problemas de compatibilidad de IQOptionAPI con websocket-client
Este módulo debe importarse ANTES que iqoptionapi para aplicar los parches necesarios
"""

import sys
import logging
import warnings

# Suprimir warnings y logs problemáticos
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger('websocket').setLevel(logging.CRITICAL)
logging.getLogger('iqoptionapi.ws.client').setLevel(logging.CRITICAL)

def patch_iqoptionapi():
    """Aplica parches en tiempo de ejecución a IQOptionAPI"""
    try:
        # Importar los módulos después de que estén disponibles
        from iqoptionapi.ws.client import WebsocketClient
        
        # Guardar métodos originales si existen
        original_on_message = getattr(WebsocketClient, 'on_message', None)
        original_on_error = getattr(WebsocketClient, 'on_error', None)
        original_on_close = getattr(WebsocketClient, 'on_close', None)
        original_on_open = getattr(WebsocketClient, 'on_open', None)
        
        # Parche para on_message
        def patched_on_message(self, ws, message):
            """Versión parcheada de on_message que acepta ws como parámetro"""
            if hasattr(self, '_original_on_message_impl'):
                return self._original_on_message_impl(message)
            elif original_on_message:
                # Llamar método original solo con message
                return original_on_message(self, message)
            else:
                # Implementación básica
                return self.on_message_default(message)
        
        # Parche para on_error
        def patched_on_error(self, ws, error):
            """Versión parcheada de on_error"""
            if hasattr(self, '_original_on_error_impl'):
                return self._original_on_error_impl(error)
            elif original_on_error:
                return original_on_error(self, error)
            else:
                logging.error(f"WebSocket error: {error}")
        
        # Parche para on_close
        def patched_on_close(self, ws, close_status_code=None, close_msg=None):
            """Versión parcheada de on_close"""
            if hasattr(self, '_original_on_close_impl'):
                return self._original_on_close_impl()
            elif original_on_close:
                return original_on_close(self)
            else:
                logging.info("WebSocket connection closed")
        
        # Parche para on_open
        def patched_on_open(self, ws):
            """Versión parcheada de on_open"""
            if hasattr(self, '_original_on_open_impl'):
                return self._original_on_open_impl()
            elif original_on_open:
                return original_on_open(self)
            else:
                logging.info("WebSocket connection opened")
        
        # Aplicar parches
        if original_on_message:
            WebsocketClient._original_on_message_impl = original_on_message
        WebsocketClient.on_message = patched_on_message
        
        if original_on_error:
            WebsocketClient._original_on_error_impl = original_on_error
        WebsocketClient.on_error = patched_on_error
        
        if original_on_close:
            WebsocketClient._original_on_close_impl = original_on_close
        WebsocketClient.on_close = patched_on_close
        
        if original_on_open:
            WebsocketClient._original_on_open_impl = original_on_open
        WebsocketClient.on_open = patched_on_open
        
        # Método default para on_message si no existe
        if not hasattr(WebsocketClient, 'on_message_default'):
            def on_message_default(self, message):
                """Implementación default de on_message"""
                try:
                    if hasattr(self, 'socket_option_opened'):
                        self.socket_option_opened[1](message)
                except Exception as e:
                    logging.error(f"Error processing message: {e}")
                    
            WebsocketClient.on_message_default = on_message_default
        
        logging.info("✅ IQOptionAPI WebSocket parches aplicados correctamente")
        return True
        
    except ImportError:
        logging.warning("⚠️ IQOptionAPI no está disponible para parchear")
        return False
    except Exception as e:
        logging.error(f"❌ Error aplicando parches: {e}")
        return False

def safe_import_iqoption():
    """Importa IQOptionAPI de forma segura con parches aplicados"""
    try:
        # Primero intentar aplicar parches
        patch_iqoptionapi()
        
        # Luego importar
        from iqoptionapi.stable_api import IQ_Option
        
        logging.info("✅ IQOptionAPI importada correctamente con parches")
        return IQ_Option, True
        
    except Exception as e:
        logging.error(f"❌ Error importando IQOptionAPI: {e}")
        return None, False

# Crear clase wrapper que maneja automáticamente los errores
class SafeIQOption:
    """Wrapper seguro para IQ_Option que maneja errores de websocket"""
    
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self._iq_instance = None
        self._connected = False
        
        # Aplicar parches antes de crear instancia
        patch_iqoptionapi()
        
        try:
            from iqoptionapi.stable_api import IQ_Option
            self._iq_instance = IQ_Option(email, password)
        except Exception as e:
            logging.error(f"Error creando instancia IQ_Option: {e}")
            raise
    
    def connect(self):
        """Conecta con manejo de errores mejorado"""
        if not self._iq_instance:
            return False, "Instancia no creada"
        
        try:
            # Suprimir logs temporalmente
            websocket_logger = logging.getLogger('websocket')
            iqapi_logger = logging.getLogger('iqoptionapi.ws.client')
            
            original_websocket_level = websocket_logger.level
            original_iqapi_level = iqapi_logger.level
            
            websocket_logger.setLevel(logging.CRITICAL)
            iqapi_logger.setLevel(logging.CRITICAL)
            
            try:
                result = self._iq_instance.connect()
                self._connected = True if result[0] else False
                return result
            finally:
                # Restaurar niveles de log
                websocket_logger.setLevel(original_websocket_level)
                iqapi_logger.setLevel(original_iqapi_level)
                
        except Exception as e:
            logging.error(f"Error en conexión: {e}")
            return False, str(e)
    
    def check_connect(self):
        """Verifica conexión"""
        if not self._iq_instance:
            return False
        try:
            return self._iq_instance.check_connect()
        except:
            return False
    
    def __getattr__(self, name):
        """Delega todos los otros métodos a la instancia real"""
        if self._iq_instance:
            return getattr(self._iq_instance, name)
        else:
            raise AttributeError(f"Instancia IQ_Option no disponible: {name}")

# Auto-aplicar parches al importar este módulo
if 'iqoptionapi' not in sys.modules:
    # Solo aplicar parches si IQOptionAPI no está ya importada
    try:
        patch_iqoptionapi()
    except:
        pass
