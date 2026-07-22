#!/usr/bin/env python3
"""
Script de inicialização do Bot Técnico
Gerencia tanto o bot do Telegram quanto o servidor web
"""
import os
import sys
import logging
from multiprocessing import Process
import signal
from pathlib import Path

# Carregar variáveis de ambiente (garantir que .env seja lido na raiz)
try:
    from dotenv import load_dotenv
    env_path = Path('.') / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass # Assume variables are already in environment

# Configurar logging básico
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def run_bot():
    """Executar o bot do Telegram"""
    logger.info("🤖 Iniciando Bot do Telegram...")
    try:
        # Importar e executar o bot
        import tecnico_bot
        tecnico_bot.main()
    except Exception as e:
        logger.error(f"❌ Erro ao executar bot: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)

def run_web_server():
    """Executar servidor web com Gunicorn (se disponível) ou Flask"""
    logger.info("🌐 Iniciando servidor web...")
    
    # Verificar se Gunicorn está disponível
    try:
        import gunicorn.app.base
        
        class StandaloneApplication(gunicorn.app.base.BaseApplication):
            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super().__init__()

            def load_config(self):
                config = {key: value for key, value in self.options.items()
                         if key in self.cfg.settings and value is not None}
                for key, value in config.items():
                    self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        from keep_alive import app
        
        options = {
            'bind': f"0.0.0.0:{os.getenv('PORT', '10000')}",
            'workers': int(os.getenv('GUNICORN_WORKERS', '2')),
            'worker_class': 'sync',
            'timeout': 120,
            'loglevel': 'info',
            'accesslog': '-',
            'errorlog': '-',
        }
        
        logger.info("✅ Usando Gunicorn como servidor WSGI")
        StandaloneApplication(app, options).run()
        
    except ImportError:
        # Fallback para Flask development server
        logger.warning("⚠️  Gunicorn não disponível, usando Flask dev server")
        from keep_alive import run
        run()

def signal_handler(sig, frame):
    """Handler para sinais de encerramento"""
    logger.info("\n👋 Recebido sinal de encerramento...")
    sys.exit(0)

if __name__ == '__main__':
    # Registrar handler de sinais
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("="*60)
    logger.info("🚀 INICIANDO BOT TÉCNICO")
    logger.info("="*60)
    
    # Verificar modo de execução
    mode = os.getenv('RUN_MODE', 'bot').lower()
    
    if mode == 'web':
        # Apenas servidor web (para testes)
        logger.info("📊 Modo: Apenas Servidor Web")
        run_web_server()
    elif mode == 'bot':
        # Apenas bot (servidor web é iniciado internamente)
        logger.info("📊 Modo: Bot + Servidor Web Integrado")
        run_bot()
    else:
        logger.error(f"❌ Modo desconhecido: {mode}")
        logger.error("Use RUN_MODE=bot ou RUN_MODE=web")
        sys.exit(1)
