"""
WSGI entry point para Gunicorn (gthread) con Flask-SocketIO en async_mode=threading
"""

from main import app  # importa la app (y SocketIO queda inicializado en main.py)

# Gunicorn usará "wsgi:app"
