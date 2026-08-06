import os
import logging
import warnings
from pathlib import Path

# Suprimir aviso esperado do PTB sobre per_message=False com CallbackQueryHandler
warnings.filterwarnings("ignore", message=".*per_message=False.*", category=UserWarning)

# Carregar variáveis do arquivo .env ANTES de importar outros módulos
try:
    from dotenv import load_dotenv
    env_path = Path('.') / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass  # Se não tiver dotenv, assume que as variáveis já estão no ambiente

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters

# Importar configurações e módulos
from config import *
from database import db
from keep_alive import keep_alive

# Importar handlers
from handlers import (
    start, ajuda, cancelar, meu_id,
    receber_nome, receber_sobrenome, receber_regiao,
    receber_sa, receber_gpon, receber_tipo, receber_serial, receber_serial_mesh, receber_foto, finalizar, receber_print_autofill, receber_serial_por_foto, receber_serial_mesh_por_foto,
    button_callback, consultar, comando_consultar, comando_reparo, comando_producao,
    comando_mensal, comando_semanal, comando_hoje, receber_data_inicio, receber_data_fim,
    receber_tipo_mascara, receber_foto_mascara, verificar_troca_ont,
    receber_obs_batimento, receber_tipo_pendencia, receber_obs_pendencia,
    receber_motivo_cancelamento, receber_cidade_repasse, receber_operadora_repasse, receber_obs_repasse
)
from admin_handlers import (
    admin_panel, admin_callback_handler, admin_broadcast_handler, confirmar_broadcast,
    admin_poll_handler, confirmar_enquete, admin_access_search_handler,
    receber_id_tecnico_ajuste, receber_data_ajuste
)

# Configuração de Logging Aprimorado
try:
    import colorlog
    handler = colorlog.StreamHandler()
    handler.setFormatter(colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    ))
    logger = colorlog.getLogger(__name__)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
except ImportError:
    # Fallback para logging padrão se colorlog não estiver disponível
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO,
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(__name__)

# Reduzir nível de log de bibliotecas externas
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

def main():
    # Obter token
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    if not TOKEN:
        # Tentar ler de arquivo (para compatibilidade com código antigo)
        try:
            with open("TELEGRAM_TOKEN", "r") as f:
                TOKEN = f.read().strip()
        except:
            pass
            
    if not TOKEN:
        logger.error("❌ TELEGRAM_TOKEN não encontrado!")
        logger.error("Configure a variável de ambiente TELEGRAM_TOKEN")
        return
    
    # Validar formato do token
    if len(TOKEN) < 20:
        logger.error("❌ TELEGRAM_TOKEN parece inválido (muito curto)")
        logger.error(f"Token recebido: {TOKEN[:10]}... (truncado)")
        return
    
    # Validar formato básico: deve conter ':'
    if ':' not in TOKEN:
        logger.error("❌ TELEGRAM_TOKEN com formato inválido")
        logger.error("Formato esperado: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
        return

    # Inicializar App
    app = Application.builder().token(TOKEN).build()

    # Definir comandos do bot
    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start", "Menu principal"),
            BotCommand("ajuda", "Ajuda"),
            BotCommand("cancelar", "Cancelar operação"),
            BotCommand("producao", "Ver produção"),
            BotCommand("mensal", "Relatório mensal"),
            BotCommand("semanal", "Relatório semanal"),
            BotCommand("hoje", "Relatório de hoje"),
            BotCommand("consultar", "Consultar instalação"),
            BotCommand("reparo", "Registrar reparo"),
            BotCommand("admin", "Painel Admin")
        ])
        # Verificar banco de dados
        from keep_alive import update_health_status
        health = await db.check_health()
        if health:
            logger.info("✅ Conexão com Supabase OK!")
            update_health_status(database_connected=True)
        else:
            logger.warning("❌ Falha na conexão com Supabase!")
            update_health_status(database_connected=False)
            
        # Notificar Admin que o bot iniciou
        try:
            if ADMIN_IDS:
                admin_id = ADMIN_IDS[0]
                await application.bot.send_message(
                    chat_id=admin_id,
                    text=f"🚀 *Bot Iniciado!*\n\nStatus DB: {'✅' if health else '❌'}",
                    parse_mode='Markdown'
                )
                logger.info(f"📤 Mensagem de inicialização enviada para Admin ({admin_id})")
        except Exception as e:
            logger.error(f"❌ Falha ao enviar mensagem de inicialização: {e}")

    app.post_init = post_init

    # Configurar ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('producao', comando_producao),
            CommandHandler('consultar', comando_consultar),
            CommandHandler('reparo', comando_reparo),
            CallbackQueryHandler(admin_callback_handler, pattern='^(admin_broadcast|admin_poll|admin_fix_days)$'),
            CallbackQueryHandler(button_callback)
        ],
        states={
            # Cadastro Inicial
            AGUARDANDO_NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
            AGUARDANDO_SOBRENOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_sobrenome)],
            AGUARDANDO_REGIAO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_regiao)],
            
            # Fluxo de Registro
            AGUARDANDO_SA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_sa),
                MessageHandler(filters.PHOTO, receber_print_autofill)
            ],
            AGUARDANDO_GPON: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_gpon)],
            AGUARDANDO_TIPO: [CallbackQueryHandler(receber_tipo)],
            AGUARDANDO_SERIAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_serial),
                MessageHandler(filters.PHOTO, receber_serial_por_foto)
            ],
            AGUARDANDO_SERIAL_MESH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_serial_mesh),
                MessageHandler(filters.PHOTO, receber_serial_mesh_por_foto)
            ],
            AGUARDANDO_TROCA_ONT: [CallbackQueryHandler(verificar_troca_ont, pattern='^(trocou_ont_sim|trocou_ont_nao)$')],
            AGUARDANDO_FOTOS: [
                MessageHandler(filters.PHOTO, receber_foto),
                CommandHandler('finalizar', finalizar),
                CallbackQueryHandler(button_callback, pattern='^(retry_save|confirmar_sa_dup|cancelar_registro)$')
            ],
            
            # Consultas
            AGUARDANDO_CONSULTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, consultar)],
            
            # Relatório por Período
            AGUARDANDO_DATA_INICIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data_inicio)],
            AGUARDANDO_DATA_FIM: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data_fim)],
            
            # Admin Broadcast
            AGUARDANDO_BROADCAST: [
                MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.AUDIO | filters.VOICE, admin_broadcast_handler)
            ],
            AGUARDANDO_CONFIRMACAO_BROADCAST: [CallbackQueryHandler(confirmar_broadcast)],
            
            # Admin Enquete
            AGUARDANDO_ENQUETE: [MessageHandler(filters.ALL, admin_poll_handler)],
            AGUARDANDO_CONFIRMACAO_ENQUETE: [CallbackQueryHandler(confirmar_enquete)],
            
            # Máscaras
            AGUARDANDO_TIPO_MASCARA: [CallbackQueryHandler(receber_tipo_mascara)],
            AGUARDANDO_FOTO_MASCARA: [
                MessageHandler(filters.PHOTO, receber_foto_mascara),
                CallbackQueryHandler(receber_foto_mascara) # Para o botão de pular
            ],
            AGUARDANDO_OBS_BATIMENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_obs_batimento)],
            AGUARDANDO_TIPO_PENDENCIA: [CallbackQueryHandler(receber_tipo_pendencia)],
            AGUARDANDO_OBS_PENDENCIA: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_obs_pendencia)],
            AGUARDANDO_MOTIVO_CANCELAMENTO: [CallbackQueryHandler(receber_motivo_cancelamento)],
            AGUARDANDO_CIDADE_REPASSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_cidade_repasse)],
            AGUARDANDO_OPERADORA_REPASSE: [CallbackQueryHandler(receber_operadora_repasse)],
            AGUARDANDO_OBS_REPASSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_obs_repasse)],
            
            # Admin Busca User
            AGUARDANDO_BUSCA_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_access_search_handler)],

            # Admin Ajuste Dias
            AGUARDANDO_ID_TECNICO_AJUSTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_id_tecnico_ajuste)],
            AGUARDANDO_DATA_AJUSTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_data_ajuste)]
        },
        fallbacks=[
            CommandHandler('cancelar', cancelar)
        ],
        per_message=False,
        per_chat=True,
        per_user=True,
        allow_reentry=True,
        conversation_timeout=300  # 5 minutos de timeout
    )

    # Adicionar handlers
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(CommandHandler('meuid', meu_id))
    app.add_handler(CommandHandler('ajuda', ajuda))
    app.add_handler(CommandHandler('mensal', comando_mensal))
    app.add_handler(CommandHandler('semanal', comando_semanal))
    app.add_handler(CommandHandler('hoje', comando_hoje))
    app.add_handler(CommandHandler('reparo', comando_reparo))
    
    # Handler para callbacks de admin (DEVE vir ANTES do ConversationHandler)
    # Excluímos admin_broadcast e admin_poll para que sejam processados pelo ConversationHandler
    app.add_handler(CallbackQueryHandler(admin_callback_handler, pattern='^(admin_(?!broadcast|poll|fix_days)|access_|au_)'))
    
    # Conversation Handler (deve vir por último para pegar os callbacks genéricos se não for admin)
    app.add_handler(conv_handler)

    # Iniciar servidor web (Render health check)
    keep_alive()

    logger.info("="*60)
    logger.info("🤖 BOT TÉCNICO INICIADO COM SUCESSO!")
    logger.info("="*60)
    logger.info(f"📊 Modo: Produção (Render)")
    logger.info(f"🔧 ConversationHandler: Otimizado")
    logger.info(f"🌐 Servidor web: Ativo")
    logger.info("="*60)
    
    from telegram.error import Conflict, NetworkError
    from keep_alive import update_health_status
    
    try:
        # Atualizar status antes de iniciar polling
        update_health_status(bot_running=True)
        
        logger.info("🔄 Iniciando polling...")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    except Conflict:
        logger.error("="*60)
        logger.error("❌ ERRO CRÍTICO: Conflito de Instâncias Detectado!")
        logger.error("Outra instância deste bot já está rodando.")
        logger.error("Encerre a outra instância para que esta possa funcionar.")
        logger.error("="*60)
        update_health_status(bot_running=False)
    except NetworkError as e:
        logger.error(f"❌ Erro de rede: {e}")
        logger.warning("🔄 Tentando reconectar...")
        update_health_status(bot_running=False)
    except KeyboardInterrupt:
        logger.info("\n👋 Bot encerrado pelo usuário")
        update_health_status(bot_running=False)
    except Exception as e:
        logger.error("="*60)
        logger.error(f"❌ Erro fatal: {e}")
        logger.error("="*60)
        update_health_status(bot_running=False)
        import traceback
        logger.error(traceback.format_exc())

if __name__ == '__main__':
    main()
