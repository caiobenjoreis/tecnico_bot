"""
Configuração do Gunicorn para produção
"""
import multiprocessing
import os

# Bind
bind = f"0.0.0.0:{os.getenv('PORT', '10000')}"

# Workers
workers = int(os.getenv('GUNICORN_WORKERS', '2'))
worker_class = 'sync'
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Timeouts
timeout = 120
keepalive = 5
graceful_timeout = 30

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'bot_tecnico_web'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (se necessário no futuro)
keyfile = None
certfile = None

# Preload app
preload_app = False

# Restart workers
max_requests = 1000
max_requests_jitter = 50

def on_starting(server):
    """Chamado quando o servidor está iniciando"""
    print("🚀 Gunicorn está iniciando...")

def on_reload(server):
    """Chamado quando o servidor recarrega"""
    print("🔄 Gunicorn está recarregando...")

def when_ready(server):
    """Chamado quando o servidor está pronto"""
    print("✅ Gunicorn está pronto!")

def on_exit(server):
    """Chamado quando o servidor está encerrando"""
    print("👋 Gunicorn está encerrando...")
