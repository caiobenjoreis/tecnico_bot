from flask import Flask, jsonify
from threading import Thread
import os
import logging
from datetime import datetime

app = Flask('')

# Configurar logging
logger = logging.getLogger(__name__)

# Variáveis de estado
start_time = datetime.now()
health_status = {
    'bot_running': False,
    'database_connected': False,
    'last_update': None
}

@app.route('/')
def home():
    """Endpoint principal - health check básico"""
    return "✅ Bot Técnico está ativo!", 200

@app.route('/health')
def health():
    """Endpoint de health check detalhado"""
    uptime = (datetime.now() - start_time).total_seconds()
    
    return jsonify({
        'status': 'healthy' if health_status['bot_running'] else 'starting',
        'bot_running': health_status['bot_running'],
        'database_connected': health_status['database_connected'],
        'uptime_seconds': uptime,
        'last_update': health_status['last_update'],
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/metrics')
def metrics():
    """Endpoint de métricas básicas"""
    uptime = (datetime.now() - start_time).total_seconds()
    
    return jsonify({
        'uptime_seconds': uptime,
        'start_time': start_time.isoformat(),
        'current_time': datetime.now().isoformat()
    }), 200

def update_health_status(bot_running=None, database_connected=None):
    """Atualizar status de saúde do bot"""
    if bot_running is not None:
        health_status['bot_running'] = bot_running
    if database_connected is not None:
        health_status['database_connected'] = database_connected
    health_status['last_update'] = datetime.now().isoformat()

def run():
    """Executar servidor Flask"""
    port = int(os.environ.get("PORT", 10000))
    # Desabilitar logs de requisição do Flask em produção
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.WARNING)
    
    logger.info(f"🌐 Servidor web iniciado na porta {port}")
    app.run(host='0.0.0.0', port=port, threaded=True)

def keep_alive():
    """Iniciar servidor em thread separada"""
    t = Thread(target=run)
    t.daemon = True
    t.start()
    logger.info("✅ Keep-alive server iniciado")

