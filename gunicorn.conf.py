# gunicorn.conf.py
import os

# Servidor
bind = f"0.0.0.0:{os.environ.get('PORT', 5000)}"
workers = 1  # IMPORTANTE: Solo 1 worker para WebSocket
worker_class = "eventlet"  # Necesario para SocketIO
worker_connections = 1000
timeout = 120
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Proceso
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (si lo necesitas en el futuro)
keyfile = None
certfile = None

# Desarrollo
reload = False
reload_engine = "auto"
reload_extra_files = []
spew = False

# Server mechanics
preload_app = True
sendfile = True
reuse_port = False
chdir = os.path.dirname(os.path.abspath(__file__))
raw_env = []

# Configuración específica para WebSocket
max_requests = 1000
max_requests_jitter = 50
