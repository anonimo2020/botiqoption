"""
Gestor de sesiones persistentes para IQ Option API
Mantiene las conexiones activas y las reutiliza
"""

import redis
import pickle
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta
import threading
import time
from iqoptionapi.stable_api import IQ_Option

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, redis_url: str):
        self.redis_client = redis.from_url(redis_url)
        self.local_cache: Dict[str, IQ_Option] = {}
        self.lock = threading.Lock()
        
        # Iniciar thread de limpieza
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()
    
    def get_api(self, user_id: str, email: str = None, password: str = None) -> Optional[IQ_Option]:
        """
        Obtiene una conexión API activa para el usuario
        """
        with self.lock:
            # Verificar caché local primero
            if user_id in self.local_cache:
                api = self.local_cache[user_id]
                if self._is_connection_alive(api):
                    return api
                else:
                    del self.local_cache[user_id]
            
            # Intentar recuperar de Redis
            session_key = f"iq_session:{user_id}"
            session_data = self.redis_client.get(session_key)
            
            if session_data:
                try:
                    session_info = pickle.loads(session_data)
                    api = self._restore_session(session_info)
                    if api:
                        self.local_cache[user_id] = api
                        return api
                except Exception as e:
                    logger.error(f"Error restaurando sesión: {str(e)}")
            
            # Si tenemos credenciales, crear nueva conexión
            if email and password:
                api = self._create_new_session(user_id, email, password)
                if api:
                    self.local_cache[user_id] = api
                    return api
            
            return None
    
    def save_session(self, user_id: str, api: IQ_Option, email: str):
        """
        Guarda información de sesión en Redis
        """
        try:
            session_info = {
                'email': email,
                'ssid': api.api.ssid,
                'created_at': datetime.now().isoformat(),
                'user_id': user_id
            }
            
            session_key = f"iq_session:{user_id}"
            # Guardar por 24 horas
            self.redis_client.setex(
                session_key,
                timedelta(hours=24),
                pickle.dumps(session_info)
            )
            
            logger.info(f"Sesión guardada para usuario {user_id}")
            
        except Exception as e:
            logger.error(f"Error guardando sesión: {str(e)}")
    
    def remove_session(self, user_id: str):
        """
        Elimina una sesión
        """
        with self.lock:
            # Eliminar de caché local
            if user_id in self.local_cache:
                try:
                    self.local_cache[user_id].api.logout()
                except:
                    pass
                del self.local_cache[user_id]
            
            # Eliminar de Redis
            session_key = f"iq_session:{user_id}"
            self.redis_client.delete(session_key)
    
    def _create_new_session(self, user_id: str, email: str, password: str) -> Optional[IQ_Option]:
        """
        Crea una nueva sesión con IQ Option
        """
        try:
            api = IQ_Option(email, password)
            check, reason = api.connect()
            
            if check:
                self.save_session(user_id, api, email)
                return api
            else:
                logger.error(f"Error conectando: {reason}")
                return None
                
        except Exception as e:
            logger.error(f"Error creando sesión: {str(e)}")
            return None
    
    def _restore_session(self, session_info: dict) -> Optional[IQ_Option]:
        """
        Intenta restaurar una sesión existente
        """
        try:
            # IQ Option no permite restaurar sesiones directamente con SSID
            # Necesitaríamos las credenciales originales
            # Por ahora, retornamos None para forzar re-login
            return None
            
        except Exception as e:
            logger.error(f"Error restaurando sesión: {str(e)}")
            return None
    
    def _is_connection_alive(self, api: IQ_Option) -> bool:
        """
        Verifica si una conexión está activa
        """
        try:
            # Intentar una operación simple
            api.get_balance()
            return True
        except:
            return False
    
    def _cleanup_loop(self):
        """
        Loop de limpieza de conexiones inactivas
        """
        while True:
            try:
                time.sleep(300)  # Cada 5 minutos
                
                with self.lock:
                    inactive = []
                    for user_id, api in self.local_cache.items():
                        if not self._is_connection_alive(api):
                            inactive.append(user_id)
                    
                    for user_id in inactive:
                        logger.info(f"Limpiando sesión inactiva: {user_id}")
                        del self.local_cache[user_id]
                        
            except Exception as e:
                logger.error(f"Error en limpieza: {str(e)}")

# Instancia global
session_manager = None

def init_session_manager(redis_url: str):
    """Inicializa el gestor de sesiones"""
    global session_manager
    session_manager = SessionManager(redis_url)
    return session_manager

def get_session_manager() -> SessionManager:
    """Obtiene la instancia del gestor de sesiones"""
    return session_manager
