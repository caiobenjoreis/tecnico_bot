import os
import logging
from zoneinfo import ZoneInfo

# Configurar logger
logger = logging.getLogger(__name__)

# Configurações de Fuso Horário
TZ = ZoneInfo("America/Sao_Paulo")

# Configurações do Supabase com validação
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_KEY)

if not USE_SUPABASE:
    logger.warning("⚠️ Supabase não configurado! Algumas funcionalidades estarão limitadas.")

# Configurações Groq com validação
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
USE_GROQ = bool(GROQ_API_KEY)

if not USE_GROQ:
    logger.warning("⚠️ Groq API não configurada! OCR automático não funcionará.")

# IDs de Administradores - Agora vem do .env
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "1797158471")
ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(",") if id.strip().isdigit()]

if not ADMIN_IDS:
    logger.error("❌ ADMIN_IDS não configurado corretamente!")
    ADMIN_IDS = [1797158471]  # Fallback

# Estados da Conversa (ConversationHandler)
(
    AGUARDANDO_SA, 
    AGUARDANDO_GPON, 
    AGUARDANDO_TIPO, 
    AGUARDANDO_SERIAL, 
    AGUARDANDO_SERIAL_MESH, 
    AGUARDANDO_FOTOS, 
    AGUARDANDO_DATA_INICIO, 
    AGUARDANDO_DATA_FIM, 
    AGUARDANDO_NOME, 
    AGUARDANDO_SOBRENOME, 
    AGUARDANDO_REGIAO, 
    AGUARDANDO_CONSULTA, 
    AGUARDANDO_BROADCAST, 
    AGUARDANDO_CONFIRMACAO_BROADCAST,
    AGUARDANDO_ENQUETE,
    AGUARDANDO_CONFIRMACAO_ENQUETE,
    AGUARDANDO_TIPO_MASCARA,
    AGUARDANDO_FOTO_MASCARA,
    AGUARDANDO_TROCA_ONT,
    AGUARDANDO_BUSCA_USER,
    AGUARDANDO_ID_TECNICO_AJUSTE,
    AGUARDANDO_DATA_AJUSTE,
    AGUARDANDO_TIPO_PENDENCIA,
    AGUARDANDO_OBS_PENDENCIA,
    AGUARDANDO_MOTIVO_CANCELAMENTO,
    AGUARDANDO_CIDADE_REPASSE,
    AGUARDANDO_OPERADORA_REPASSE,
    AGUARDANDO_OBS_REPASSE,
    AGUARDANDO_OBS_BATIMENTO
) = range(29)

# Tabelas de Pontos e Valores
PONTOS_SERVICO = {
    'defeito_banda_larga': 1.43,
    'defeito_linha': 1.43,
    'defeito_tv': 1.43,
    'instalacao': 2.28,
    'instalacao_tv': 3.58,
    'instalacao_mesh': 2.91,
    'instalacao_fttr': 5.57,
    'mudanca_endereco': 2.37,
    'retirada': 1.06,
    'servicos': 1.50,
    'servico': 1.50
}

TABELA_FAIXAS = [
    {'min': 164.0, 'max': float('inf'), 'faixa': 'A', 'valor': 3.20, 'valor_turbo': 8.00},
    {'min': 159.0, 'max': 163.99, 'faixa': 'B', 'valor': 2.40, 'valor_turbo': 6.00},
    {'min': 148.0, 'max': 158.99, 'faixa': 'C', 'valor': 1.60, 'valor_turbo': 4.00},
    {'min': 137.0, 'max': 147.99, 'faixa': 'D', 'valor': 1.00, 'valor_turbo': 2.50},
    {'min': 126.0, 'max': 136.99, 'faixa': 'E', 'valor': 0.80, 'valor_turbo': 2.25},
    {'min': 120.0, 'max': 125.99, 'faixa': 'F', 'valor': 0.70, 'valor_turbo': 2.00},
    {'min': 115.0, 'max': 119.99, 'faixa': 'G', 'valor': 0.70, 'valor_turbo': 1.75},
    {'min': 109.0, 'max': 114.99, 'faixa': 'H', 'valor': 0.60, 'valor_turbo': 1.50},
    {'min': 0.0,   'max': 108.99, 'faixa': 'I', 'valor': 0.00, 'valor_turbo': 0.00}
]
