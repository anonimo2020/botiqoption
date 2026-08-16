# gunicorn_config.py
# Configuración para Render con Flask-SocketIO en async_mode='threading' + Gunicorn gthread

import os

# Bind
bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"

# Workers
workers = 1  # 1 worker (estado en memoria + estabilidad)

# Worker class - GTHREAD
worker_class = "gthread"
threads = 8

# Timeouts
timeout = 180
graceful_timeout = 30
keepalive = 5

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Preload
preload_app = False

# Límites de memoria
max_requests = 500
max_requests_jitter = 50

# Socket
backlog = 2048
