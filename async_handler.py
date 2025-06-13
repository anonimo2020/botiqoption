"""
Manejador de operaciones asíncronas para el bot
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
import logging

logger = logging.getLogger(__name__)

class AsyncHandler:
    def __init__(self):
        self.loop = None
        self.thread = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        self._start_event_loop()
    
    def _start_event_loop(self):
        """Inicia el event loop en un thread separado"""
        def run_loop():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
        
        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()
        
        # Esperar a que el loop esté listo
        while self.loop is None:
            threading.Event().wait(0.01)
    
    def run_coroutine(self, coro):
        """Ejecuta una coroutine en el event loop"""
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future
    
    def create_task(self, coro):
        """Crea una tarea asíncrona"""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)
    
    def shutdown(self):
        """Cierra el event loop y el executor"""
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
        if self.thread:
            self.thread.join(timeout=5)
        self.executor.shutdown(wait=True)

# Instancia global
async_handler = AsyncHandler()

def get_async_handler():
    """Obtiene la instancia del manejador asíncrono"""
    return async_handler
