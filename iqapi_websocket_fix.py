"""
Solución definitiva para problemas de compatibilidad IQOptionAPI + websocket-client
Versión corregida que maneja correctamente todos los métodos
"""

import sys
import logging
import warnings
import inspect

# Suprimir todos los warnings problemáticos
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*websocket.*")

def create_compatible_websocket_client():
    """Crea una versión compatible de WebsocketClient"""
    
    def patch_websocket_methods():
        """Aplica parches a los métodos de WebsocketClient"""
        try:
            from iqoptionapi.ws.client import WebsocketClient
            
            # Solo parchear si no se ha hecho antes
            if hasattr(WebsocketClient, '_websocket_patched'):
                return True
            
            # Método on_message compatible
            def compatible_on_message(self, ws_or_message, message=None):
                """Método on_message que acepta 2 o 3 argumentos"""
                try:
                    # Si se llama con 3 argumentos (self, ws, message)
                    if message is not None:
                        actual_message = message
                    else:
                        # Si se llama con 2 argumentos (self, message)
                        actual_message = ws_or_message
                    
                    # Procesar el mensaje
                    if hasattr(self, 'socket_option_opened') and self.socket_option_opened:
                        try:
                            self.socket_option_opened[1](actual_message)
                        except Exception as e:
                            logging.debug(f"Error processing message: {e}")
                    
                except Exception as e:
                    logging.debug(f"Error in on_message: {e}")
            
            # Método on_error compatible
            def compatible_on_error(self, ws_or_error, error=None):
                """Método on_error que acepta 2 o 3 argumentos"""
                try:
                    actual_error = error if error is not None else ws_or_error
                    logging.debug(f"WebSocket error: {actual_error}")
                except Exception as e:
                    logging.debug(f"Error in on_error: {e}")
            
            # Método on_close compatible
            def compatible_on_close(self, ws=None, close_status_code=None, close_msg=None):
                """Método on_close que acepta argumentos variables"""
                try:
                    logging.debug("WebSocket connection closed")
                    if hasattr(self, 'socket_option_opened'):
                        self.socket_option_opened = None
                except Exception as e:
                    logging.debug(f"Error in on_close: {e}")
            
            # Método on_open compatible
            def compatible_on_open(self, ws=None):
                """Método on_open que acepta argumentos variables"""
                try:
                    logging.debug("WebSocket connection opened")
                except Exception as e:
                    logging.debug(f"Error in on_open: {e}")
            
            # Aplicar parches
            WebsocketClient.on_message = compatible_on_message
            WebsocketClient.on_error = compatible_on_error
            WebsocketClient.on_close = compatible_on_close
            WebsocketClient.on_open = compatible_on_open
            
            # Marcar como parcheado
            WebsocketClient._websocket_patched = True
            
            logging.info("✅ WebSocket compatibility patches applied successfully")
            return True
            
        except Exception as e:
            logging.warning(f"⚠️ Could not apply WebSocket patches: {e}")
            return False
    
    return patch_websocket_methods

# Crear función de parcheo
patch_websocket_methods = create_compatible_websocket_client()

class RobustIQOption:
    """Wrapper robusto para IQ_Option que maneja automáticamente errores de websocket"""
    
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self._iq_instance = None
        self._connected = False
        
        # Configurar logging para suprimir errores de websocket
        self._setup_logging()
        
        # Aplicar parches antes de crear instancia
        patch_websocket_methods()
        
        try:
            from iqoptionapi.stable_api import IQ_Option
            self._iq_instance = IQ_Option(email, password)
        except Exception as e:
            logging.error(f"Error creating IQ_Option instance: {e}")
            raise
    
    def _setup_logging(self):
        """Configura logging para suprimir mensajes problemáticos"""
        loggers_to_suppress = [
            'websocket',
            'iqoptionapi.ws.client',
            'iqoptionapi.ws',
            'iqoptionapi.api',
            'urllib3.connectionpool'
        ]
        
        for logger_name in loggers_to_suppress:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            
            # Remover handlers existentes que podrían causar problemas
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
    
    def connect(self):
        """Conecta con manejo robusto de errores"""
        if not self._iq_instance:
            return False, "Instance not available"
        
        try:
            # Suprimir logging temporalmente
            self._suppress_websocket_logging()
            
            try:
                result = self._iq_instance.connect()
                if isinstance(result, tuple) and len(result) >= 2:
                    self._connected = result[0]
                    return result
                else:
                    self._connected = bool(result)
                    return result, "Connected" if result else "Connection failed"
                    
            except Exception as e:
                logging.error(f"Connection error: {e}")
                return False, str(e)
            finally:
                # Restaurar logging después de la conexión
                self._restore_logging()
                
        except Exception as e:
            logging.error(f"Error during connection process: {e}")
            return False, str(e)
    
    def _suppress_websocket_logging(self):
        """Suprime temporalmente el logging problemático"""
        self._original_levels = {}
        
        loggers_to_suppress = [
            'websocket',
            'iqoptionapi.ws.client',
            'iqoptionapi.ws',
            'iqoptionapi'
        ]
        
        for logger_name in loggers_to_suppress:
            logger = logging.getLogger(logger_name)
            self._original_levels[logger_name] = logger.level
            logger.setLevel(logging.CRITICAL)
    
    def _restore_logging(self):
        """Restaura los niveles de logging originales"""
        if hasattr(self, '_original_levels'):
            for logger_name, original_level in self._original_levels.items():
                logger = logging.getLogger(logger_name)
                logger.setLevel(original_level)
    
    def check_connect(self):
        """Verifica la conexión"""
        if not self._iq_instance:
            return False
        try:
            return self._iq_instance.check_connect()
        except Exception:
            return False
    
    def __getattr__(self, name):
        """Delega métodos a la instancia real de IQ_Option"""
        if self._iq_instance and hasattr(self._iq_instance, name):
            attr = getattr(self._iq_instance, name)
            
            # Si es un método que puede causar problemas de websocket, envolverlo
            if callable(attr) and name in ['get_candles', 'buy', 'check_win_v3', 'get_balance']:
                def wrapped_method(*args, **kwargs):
                    try:
                        self._suppress_websocket_logging()
                        return attr(*args, **kwargs)
                    except Exception as e:
                        logging.debug(f"Error in {name}: {e}")
                        raise
                    finally:
                        self._restore_logging()
                return wrapped_method
            else:
                return attr
        else:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

def safe_import_iqoption():
    """Importa IQOptionAPI de forma segura aplicando parches"""
    try:
        # Aplicar parches primero
        patch_success = patch_websocket_methods()
        
        if patch_success:
            from iqoptionapi.stable_api import IQ_Option
            logging.info("✅ IQOptionAPI imported successfully with patches")
            return IQ_Option, True
        else:
            logging.warning("⚠️ Patches not applied, but trying to import anyway")
            from iqoptionapi.stable_api import IQ_Option
            return IQ_Option, True
            
    except Exception as e:
        logging.error(f"❌ Failed to import IQOptionAPI: {e}")
        return None, False

# Auto-aplicar parches al importar este módulo
try:
    patch_websocket_methods()
except Exception as e:
    logging.warning(f"Could not auto-apply patches: {e}")

# Función de conveniencia para obtener una instancia robusta
def create_robust_iqoption(email, password):
    """Crea una instancia robusta de IQ_Option"""
    return RobustIQOption(email, password)
