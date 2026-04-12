"""
Archivo compatible con el main.py original
Proporciona las clases y funciones que busca el main.py actual
"""

import sys
import logging
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*websocket.*")

def patch_iqoptionapi():
    """Aplica parches a IQOptionAPI para compatibilidad con websocket"""
    try:
        from iqoptionapi.ws.client import WebsocketClient
        
        if hasattr(WebsocketClient, '_hotfix_patched'):
            return True
        
        # Métodos seguros que manejan argumentos variables
        def safe_on_message(self, ws_or_message, message=None):
            try:
                actual_message = message if message is not None else ws_or_message
                if hasattr(self, 'socket_option_opened') and self.socket_option_opened:
                    self.socket_option_opened[1](actual_message)
            except Exception:
                pass
        
        def safe_on_error(self, ws_or_error, error=None):
            # Silenciar todos los errores de websocket
            pass
        
        def safe_on_close(self, ws=None, close_status_code=None, close_msg=None):
            try:
                if hasattr(self, 'socket_option_opened'):
                    self.socket_option_opened = None
            except Exception:
                pass
        
        def safe_on_open(self, ws=None):
            try:
                logging.debug("WebSocket opened")
            except Exception:
                pass
        
        # Aplicar todos los parches
        WebsocketClient.on_message = safe_on_message
        WebsocketClient.on_error = safe_on_error
        WebsocketClient.on_close = safe_on_close
        WebsocketClient.on_open = safe_on_open
        WebsocketClient._hotfix_patched = True
        
        logging.info("✅ WebSocket compatibility patches applied")
        return True
        
    except Exception as e:
        logging.warning(f"⚠️ Could not apply WebSocket patches: {e}")
        return False

class SafeIQOption:
    """Wrapper seguro para IQ_Option que maneja errores de websocket"""
    
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self._iq_instance = None
        self._connected = False
        
        # Configurar logging para suprimir websocket
        self._setup_logging()
        
        # Aplicar parches antes de crear instancia
        patch_iqoptionapi()
        
        try:
            from iqoptionapi.stable_api import IQ_Option
            self._iq_instance = IQ_Option(email, password)
        except Exception as e:
            logging.error(f"Error creating IQ_Option: {e}")
            raise
    
    def _setup_logging(self):
        """Suprimir logs problemáticos"""
        problematic_loggers = [
            'websocket',
            'iqoptionapi.ws.client', 
            'iqoptionapi.ws',
            'iqoptionapi.api',
            'urllib3.connectionpool'
        ]
        
        for logger_name in problematic_loggers:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            logger.propagate = False
    
    def connect(self):
        """Conecta suprimiendo logs de websocket"""
        if not self._iq_instance:
            return False, "Instance not available"
        
        try:
            # Suprimir logs durante conexión
            self._suppress_logs()
            
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
                # Mantener logs suprimidos permanentemente para websocket
                pass
                
        except Exception as e:
            logging.error(f"Error in connection process: {e}")
            return False, str(e)
    
    def _suppress_logs(self):
        """Suprime logs problemáticos permanentemente"""
        loggers_to_suppress = [
            'websocket',
            'iqoptionapi.ws.client',
            'iqoptionapi.ws', 
            'iqoptionapi'
        ]
        
        for logger_name in loggers_to_suppress:
            logger = logging.getLogger(logger_name)
            logger.setLevel(logging.CRITICAL)
            logger.propagate = False
            
            # Remover handlers que pueden causar problemas
            for handler in logger.handlers[:]:
                try:
                    logger.removeHandler(handler)
                except:
                    pass
    
    def check_connect(self):
        """Verifica conexión"""
        if not self._iq_instance:
            return False
        try:
            return self._iq_instance.check_connect()
        except Exception:
            return False
    
    def __getattr__(self, name):
        """Delega métodos a la instancia real"""
        if self._iq_instance and hasattr(self._iq_instance, name):
            attr = getattr(self._iq_instance, name)
            
            # Para métodos que pueden generar logs de websocket, envolverlos
            if callable(attr) and name in ['get_candles', 'buy', 'check_win_v3', 'get_balance', 'change_balance']:
                def wrapped_method(*args, **kwargs):
                    try:
                        self._suppress_logs()
                        return attr(*args, **kwargs)
                    except Exception as e:
                        if "websocket" not in str(e).lower():
                            logging.debug(f"Error in {name}: {e}")
                        raise
                return wrapped_method
            else:
                return attr
        else:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

def safe_import_iqoption():
    """Importa IQOptionAPI de forma segura"""
    try:
        # Aplicar parches primero
        patch_success = patch_iqoptionapi()
        
        from iqoptionapi.stable_api import IQ_Option
        logging.info("✅ IQOptionAPI imported successfully")
        return IQ_Option, True
            
    except Exception as e:
        logging.error(f"❌ Failed to import IQOptionAPI: {e}")
        return None, False

# Auto-aplicar parches al importar
try:
    patch_iqoptionapi()
    logging.info("✅ Auto-patches applied on import")
except Exception as e:
    logging.warning(f"Auto-patch warning: {e}")
