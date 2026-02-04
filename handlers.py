from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants, InputMediaPhoto
from telegram.ext import ContextTypes, ConversationHandler
from typing import Tuple, Optional, List, Dict, Any
from config import *
from database import db
from datetime import datetime
from reports import gerar_texto_producao, gerar_ranking_texto, gerar_resumo_progresso
from utils import ciclo_atual, escape_markdown, extrair_campos_por_imagem, extrair_campos_por_imagens, extrair_campo_especifico, is_valid_serial, calcular_pontos
import io
import os
import logging

logger = logging.getLogger(__name__)

# ==================== CATEGORIZAÇÃO DE TIPOS ====================
# Tipos que são SEMPRE reparos
TIPOS_REPARO = ['defeito_banda_larga', 'defeito_linha', 'defeito_tv', 'retirada']

# Tipos que são SEMPRE instalações
TIPOS_INSTALACAO = ['instalacao', 'instalacao_tv', 'instalacao_mesh', 'instalacao_fttr']

# Tipos que podem ser ambos (depende do contexto)
TIPOS_AMBIGUOS = ['mudanca_endereco', 'servicos', 'servico']

# ==================== HELPER FUNCTIONS ====================

async def verificar_acesso_usuario(user_id: int) -> Tuple[bool, str]:
    """
    Verifica se o usuário tem acesso ao bot.
    Retorna (tem_acesso, mensagem_erro)
    """
    db_user = await db.get_user(str(user_id))
    
    if db_user and db_user.get('status') == 'bloqueado':
        return False, '⛔ *Acesso Bloqueado*\n\nSeu acesso foi suspenso. Entre em contato com o administrador.'
    
    if db_user and db_user.get('status') == 'pendente':
        return False, '⏳ *Cadastro em Análise*\n\nSeu cadastro está aguardando aprovação do administrador.'
    
    return True, ''

# ==================== FLUXO DE INSTALAÇÃO/REPARO ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    # Verificar status do usuário antes de processar qualquer ação
    # Exceto para callbacks admin que têm sua própria verificação
    if not query.data.startswith(('admin_', 'broadcast_', 'access_')):
        user_id = query.from_user.id
        db_user = await db.get_user(str(user_id))
        
        if db_user and db_user.get('status') == 'bloqueado':
            await query.answer('⛔ Seu acesso está bloqueado. Contate o administrador.', show_alert=True)
            return ConversationHandler.END
            
        if db_user and db_user.get('status') == 'pendente':
            await query.answer('⏳ Seu cadastro está aguardando aprovação.', show_alert=True)
            return ConversationHandler.END
    
    await query.answer()
    
    if query.data == 'registrar':
        context.user_data['modo_registro'] = 'instalacao'
        logger.info(f"Usuário {query.from_user.id} iniciou INSTALAÇÃO")
        await query.edit_message_text(
            '📝 *Nova Instalação* [Etapa 1/5]\n\n'
            'Digite o *número da SA*:\n'
            '💡 Exemplo: 12345678\n\n'
            '_(Digite /cancelar para voltar ao menu)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SA
    
    elif query.data == 'registrar_reparo':
        context.user_data['modo_registro'] = 'reparo'
        logger.info(f"Usuário {query.from_user.id} iniciou REPARO")
        await query.edit_message_text(
            '🛠️ *Novo Reparo* [Etapa 1/5]\n\n'
            'Digite o *número da SA*:\n'
            '💡 Exemplo: 12345678\n\n'
            '_(Digite /cancelar para voltar ao menu)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SA
        
    elif query.data == 'consultar':
        await query.edit_message_text(
            '🔎 *Consultar Instalação*\n\n'
            'Digite o *número da SA*, *GPON* ou *Serial do Modem*:\n\n'
            '💡 Exemplos:\n'
            '• SA: 12345678\n'
            '• GPON: ABCD1234\n'
            '• Serial: ZTEGC8...',
            parse_mode='Markdown'
        )
        return AGUARDANDO_CONSULTA
        
    elif query.data == 'minhas':
        user_id = query.from_user.id
        insts = await db.get_installations({'tecnico_id': user_id}, limit=10)
        
        if not insts:
            await query.edit_message_text('📂 Você ainda não registrou nenhuma instalação.')
            return None
            
        msg = f'📂 *Suas Últimas Instalações*\n\n'
        for i, inst in enumerate(insts, 1):
            msg += f'{i}. SA: `{inst.get("sa")}` | GPON: `{inst.get("gpon")}`\n'
            msg += f'   Data: {inst.get("data")}\n\n'
            
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None

    elif query.data == 'consulta_producao':
        user_id = query.from_user.id
        username = query.from_user.username or query.from_user.first_name
        inicio_dt, fim_dt = ciclo_atual()
        
        # Filtrar por data no Python pois o banco tem string
        insts = await db.get_installations({'tecnico_id': user_id, 'data_inicio': inicio_dt, 'data_fim': fim_dt})
        
        if not insts:
            msg = f'❌ Nenhuma instalação entre {inicio_dt.strftime("%d/%m/%Y")} e {fim_dt.strftime("%d/%m/%Y")}.'
            await query.edit_message_text(msg, parse_mode='Markdown')
            return None
            
        msg = gerar_texto_producao(insts, inicio_dt, fim_dt, username)
        
        # Adicionar botão "Ver Detalhes"
        keyboard = [[InlineKeyboardButton("📄 Ver Detalhes", callback_data='detalhes_producao')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(msg, parse_mode='Markdown', reply_markup=reply_markup)
        return None
    
    elif query.data == 'detalhes_producao':
        user_id = query.from_user.id
        inicio_dt, fim_dt = ciclo_atual()
        
        insts = await db.get_installations({'tecnico_id': user_id, 'data_inicio': inicio_dt, 'data_fim': fim_dt})
        
        if not insts:
            await query.answer("Nenhuma instalação encontrada.", show_alert=True)
            return None
        
        # Gerar lista detalhada
        msg = f"📄 *Detalhes do Ciclo ({inicio_dt.strftime('%d/%m')} - {fim_dt.strftime('%d/%m')})*\n\n"
        
        # Ordenar por data (mais recente primeiro)
        insts_sorted = sorted(insts, key=lambda x: datetime.strptime(x['data'], '%d/%m/%Y %H:%M'), reverse=True)
        
        # Limitar exibição para evitar erro de tamanho de mensagem
        MAX_ITEMS = 30
        exibidos = insts_sorted[:MAX_ITEMS]
        
        for inst in exibidos:
            tipo = inst.get('tipo', 'Instalação')
            from config import PONTOS_SERVICO
            pontos = PONTOS_SERVICO.get(tipo.lower(), 0)
            msg += f"📅 {inst['data']} | {pontos} pts\n"
            msg += f"🔧 {tipo} | SA: {inst['sa']}\n"
            msg += f"───\n"
            
        if len(insts_sorted) > MAX_ITEMS:
            msg += f"\n... e mais {len(insts_sorted) - MAX_ITEMS} registros.\n───────────────\n"
        
        # Truncar se muito longo
        if len(msg) > 4000:
            msg = msg[:4000] + "\n\n(Lista truncada devido ao tamanho...)"
        
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None
    
    elif query.data == 'voltar':
        # Importar aqui para evitar ciclo se start estiver em outro lugar, mas start está em handlers?
        # Não, start está em handlers.py. Precisamos definir exibir_menu_principal ou importar start.
        # O original chamava start(update, context).
        # Vamos chamar start diretamente se estiver neste arquivo.
        await start(update, context)
        return None

    elif query.data == 'relatorios':
        keyboard = [
            [InlineKeyboardButton("📅 Relatório Mensal", callback_data='rel_mensal')],
            [InlineKeyboardButton("📊 Relatório Semanal", callback_data='rel_semanal')],
            [InlineKeyboardButton("📈 Relatório Hoje", callback_data='rel_hoje')],
            [InlineKeyboardButton("📆 Relatório por Período", callback_data='rel_periodo')],
            [InlineKeyboardButton("🏆 Ranking Técnicos", callback_data='rel_ranking')],
            [InlineKeyboardButton("🔙 Voltar", callback_data='voltar')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('📊 *Relatórios Disponíveis*', reply_markup=reply_markup, parse_mode='Markdown')
        return None
        
    elif query.data == 'rel_mensal':
        from reports import gerar_relatorio_mensal
        insts = await db.get_installations(limit=5000)
        msg = gerar_relatorio_mensal(insts)
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None
        
    elif query.data == 'rel_semanal':
        from reports import gerar_relatorio_semanal
        insts = await db.get_installations(limit=5000)
        msg = gerar_relatorio_semanal(insts)
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None
        
    elif query.data == 'rel_hoje':
        from reports import gerar_relatorio_hoje
        insts = await db.get_installations(limit=5000)
        msg = gerar_relatorio_hoje(insts)
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None
        
    elif query.data == 'rel_periodo':
        await query.edit_message_text(
            '📆 *Relatório por Período*\n\nEnvie a *data inicial* no formato `dd/mm/aaaa`:',
            parse_mode='Markdown'
        )
        return AGUARDANDO_DATA_INICIO
        
    elif query.data == 'rel_ranking':
        # Ranking pega tudo (cuidado com performance futura)
        insts = await db.get_installations(limit=5000)
        user_id = query.from_user.id
        is_admin = user_id in ADMIN_IDS
        msg = gerar_ranking_texto(insts, is_admin=is_admin)
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None
        
    elif query.data == 'mascaras':
        keyboard = [
            [InlineKeyboardButton("🎭 Batimento CDOE", callback_data='mask_batimento')],
            [InlineKeyboardButton("🎭 Pendência", callback_data='mask_pendencia')],
            [InlineKeyboardButton("🎭 Cancelamento", callback_data='mask_cancelamento')],
            [InlineKeyboardButton("🎭 Repasse", callback_data='mask_repasse')],
            [InlineKeyboardButton("🔙 Voltar", callback_data='voltar')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('🎭 *Gerador de Máscaras*\n\nSelecione o modelo desejado:', reply_markup=reply_markup, parse_mode='Markdown')
        return AGUARDANDO_TIPO_MASCARA

    # Callbacks do painel admin
    elif query.data.startswith('admin_'):
        from admin_handlers import admin_callback_handler
        return await admin_callback_handler(update, context)
        
    elif query.data.startswith('broadcast_'):
        from admin_handlers import confirmar_broadcast
        # Este handler é chamado via CallbackQueryHandler específico no main, mas se cair aqui...
        pass

    return None

async def receber_tipo_mascara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'voltar':
        await start(update, context)
        return ConversationHandler.END
        
    tipo_map = {
        'mask_batimento': 'Batimento CDOE',
        'mask_pendencia': 'Pendência',
        'mask_cancelamento': 'Cancelamento',
        'mask_repasse': 'Repasse'
    }
    
    tipo = tipo_map.get(query.data)
    if not tipo:
        return AGUARDANDO_TIPO_MASCARA
        
    context.user_data['tipo_mascara'] = tipo
    context.user_data['fotos_mascara'] = []
    
    keyboard = [[InlineKeyboardButton("⏩ Pular Foto (Preencher Manual)", callback_data='skip_photo')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f'🎭 *Máscara: {tipo}*\n\n'
        '📸 Envie os *prints da tela* do aplicativo.\n'
        '💡 Você pode enviar várias fotos para complementar os dados.\n\n'
        'Quando terminar, clique em *✅ Gerar Máscara*.',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return AGUARDANDO_FOTO_MASCARA

async def receber_foto_mascara(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Inicializar lista de fotos se não existir
    if 'fotos_mascara' not in context.user_data:
        context.user_data['fotos_mascara'] = []
    
    # Se enviou foto, acumula
    if update.message and update.message.photo:
        photo = update.message.photo[-1]
        try:
            file = await photo.get_file()
            out = io.BytesIO()
            await file.download_to_memory(out)
            image_bytes = out.getvalue()
            context.user_data['fotos_mascara'].append(image_bytes)
            
            qtd = len(context.user_data['fotos_mascara'])
            keyboard = [[InlineKeyboardButton("✅ Gerar Máscara", callback_data='gerar_mascara')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f'📸 *{qtd} foto(s) recebida(s)*\nEnvie mais ou clique em Gerar.',
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return AGUARDANDO_FOTO_MASCARA
        except Exception as e:
            logger.error(f"Erro ao baixar foto mascara: {e}")
            await update.message.reply_text('❌ Erro ao baixar imagem. Tente novamente.')
            return AGUARDANDO_FOTO_MASCARA

    # Se clicou em Gerar ou Pular
    elif update.callback_query:
        await update.callback_query.answer()
        if update.callback_query.data not in ['gerar_mascara', 'skip_photo']:
            return AGUARDANDO_FOTO_MASCARA
            
    # Processar OCR
    from utils import extrair_dados_completos
    
    imgs = context.user_data.get('fotos_mascara', [])
    dados = {}
    
    if imgs:
        msg_proc = await (update.callback_query.message if update.callback_query else update.message).reply_text('⏳ Analisando imagens e gerando máscara...', parse_mode='Markdown')
        try:
            tipo = context.user_data.get('tipo_mascara')
            dados = await extrair_dados_completos(imgs, tipo_mascara=tipo)
        except Exception as e:
            logger.error(f"Erro OCR mascara: {e}")
        
        # Tentar apagar msg de processamento
        try:
            await msg_proc.delete()
        except:
            pass
    
    # Salvar dados extraídos
    context.user_data['dados_mascara'] = dados
    
    # Agora perguntar informações complementares baseado no tipo
    tipo = context.user_data.get('tipo_mascara')
    
    if tipo == 'Batimento CDOE':
        await (update.callback_query.message if update.callback_query else update.message).reply_text(
            '📝 *Informações Complementares*\n\n'
            'Digite as *Observações* (ou envie "-" se não houver):',
            parse_mode='Markdown'
        )
        return AGUARDANDO_OBS_BATIMENTO
        
    elif tipo == 'Pendência':
        keyboard = [
            [InlineKeyboardButton("📦 Falta Material", callback_data='pend_falta_material')],
            [InlineKeyboardButton("👤 Cliente Ausente", callback_data='pend_cliente_ausente')],
            [InlineKeyboardButton("⚠️ Problema Técnico", callback_data='pend_problema_tecnico')],
            [InlineKeyboardButton("🔧 Infraestrutura", callback_data='pend_infraestrutura')],
            [InlineKeyboardButton("📋 Outro", callback_data='pend_outro')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await (update.callback_query.message if update.callback_query else update.message).reply_text(
            '📝 *Informações Complementares*\n\n'
            'Selecione o *Tipo de Pendência*:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return AGUARDANDO_TIPO_PENDENCIA
        
    elif tipo == 'Cancelamento':
        keyboard = [
            [InlineKeyboardButton("🚫 Cliente Desistiu", callback_data='canc_cliente_desistiu')],
            [InlineKeyboardButton("📡 Área sem Cobertura", callback_data='canc_sem_cobertura')],
            [InlineKeyboardButton("💰 Problema Financeiro", callback_data='canc_financeiro')],
            [InlineKeyboardButton("⏰ Cliente não Aguardou", callback_data='canc_nao_aguardou')],
            [InlineKeyboardButton("📋 Outro", callback_data='canc_outro')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await (update.callback_query.message if update.callback_query else update.message).reply_text(
            '📝 *Informações Complementares*\n\n'
            'Selecione o *Motivo do Cancelamento*:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return AGUARDANDO_MOTIVO_CANCELAMENTO
        
    elif tipo == 'Repasse':
        await (update.callback_query.message if update.callback_query else update.message).reply_text(
            '📝 *Informações Complementares*\n\n'
            'Digite a *Cidade*:',
            parse_mode='Markdown'
        )
        return AGUARDANDO_CIDADE_REPASSE
    
    # Fallback (não deveria chegar aqui)
    return ConversationHandler.END

# ==================== HANDLERS DE DADOS COMPLEMENTARES DAS MÁSCARAS ====================

async def receber_obs_batimento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    obs = update.message.text.strip()
    if obs == '-':
        obs = ''
    context.user_data['obs_batimento'] = obs
    return await gerar_mascara_final(update, context)

async def receber_tipo_pendencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    tipo_map = {
        'pend_falta_material': 'Falta Material',
        'pend_cliente_ausente': 'Cliente Ausente',
        'pend_problema_tecnico': 'Problema Técnico',
        'pend_infraestrutura': 'Infraestrutura',
        'pend_outro': 'Outro'
    }
    
    tipo_pendencia = tipo_map.get(query.data, 'Outro')
    context.user_data['tipo_pendencia'] = tipo_pendencia
    
    await query.edit_message_text(
        f'✅ Tipo: *{tipo_pendencia}*\n\n'
        'Agora digite as *Observações* detalhadas (ou "-" se não houver):',
        parse_mode='Markdown'
    )
    return AGUARDANDO_OBS_PENDENCIA

async def receber_obs_pendencia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    obs = update.message.text.strip()
    if obs == '-':
        obs = ''
    context.user_data['obs_pendencia'] = obs
    return await gerar_mascara_final(update, context)

async def receber_motivo_cancelamento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    motivo_map = {
        'canc_cliente_desistiu': 'Cliente Desistiu',
        'canc_sem_cobertura': 'Área sem Cobertura',
        'canc_financeiro': 'Problema Financeiro',
        'canc_nao_aguardou': 'Cliente não Aguardou',
        'canc_outro': 'Outro'
    }
    
    motivo = motivo_map.get(query.data, 'Outro')
    context.user_data['motivo_cancelamento'] = motivo
    
    return await gerar_mascara_final(update, context)

async def receber_cidade_repasse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cidade = update.message.text.strip().upper()
    context.user_data['cidade_repasse'] = cidade
    
    keyboard = [
        [InlineKeyboardButton("📱 Vivo", callback_data='oper_vivo')],
        [InlineKeyboardButton("📱 Claro", callback_data='oper_claro')],
        [InlineKeyboardButton("📱 Tim", callback_data='oper_tim')],
        [InlineKeyboardButton("📱 Oi", callback_data='oper_oi')],
        [InlineKeyboardButton("📱 Outro", callback_data='oper_outro')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f'✅ Cidade: *{cidade}*\n\n'
        'Selecione a *Operadora*:',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return AGUARDANDO_OPERADORA_REPASSE

async def receber_operadora_repasse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    oper_map = {
        'oper_vivo': 'VIVO',
        'oper_claro': 'CLARO',
        'oper_tim': 'TIM',
        'oper_oi': 'OI',
        'oper_outro': 'OUTRO'
    }
    
    operadora = oper_map.get(query.data, 'OUTRO')
    context.user_data['operadora_repasse'] = operadora
    
    await query.edit_message_text(
        f'✅ Operadora: *{operadora}*\n\n'
        'Digite as *Observações* (ou "-" se não houver):',
        parse_mode='Markdown'
    )
    return AGUARDANDO_OBS_REPASSE

async def receber_obs_repasse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    obs = update.message.text.strip()
    if obs == '-':
        obs = ''
    context.user_data['obs_repasse'] = obs
    return await gerar_mascara_final(update, context)

# ==================== GERAÇÃO FINAL DA MÁSCARA ====================

async def gerar_mascara_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gera a máscara final com todos os dados coletados"""
    
    dados = context.user_data.get('dados_mascara', {})
    tipo = context.user_data.get('tipo_mascara')
    
    # Helper para pegar dados ou vazio
    def get(key, default=""): return dados.get(key, default)
    
    texto_final = ""
    
    if tipo == 'Batimento CDOE':
        obs = context.user_data.get('obs_batimento', '')
        texto_final = (
            "Máscara Batimento CDOE\n\n"
            f"ATIVIDADE: {get('atividade')}\n"
            f"ESTAÇÃO: {get('estacao')}\n"
            f"CDOE: {get('cdo')}\n"
            f"PORTA CLIENTE: {get('porta')}\n"
            f"ACESSO GPON: {get('gpon')}\n"
            f"OBS: {obs}"
        )
        
    elif tipo == 'Pendência':
        tipo_pend = context.user_data.get('tipo_pendencia', '')
        obs = context.user_data.get('obs_pendencia', '')
        texto_final = (
            "Máscara de Pendência!\n\n"
            f"Tipo de serviço: {get('atividade')}\n"
            f"SA: {get('sa')}\n"
            f"Doc associado: {get('documento')}\n"
            f"GPON: {get('gpon')}\n"
            f"Cliente: {get('cliente')}\n"
            f"Contato: {get('telefone')}\n"
            f"Endereço: {get('endereco')}\n"
            f"Tipo de pendência: {tipo_pend}\n"
            f"Obs: {obs}"
        )
        
    elif tipo == 'Cancelamento':
        motivo = context.user_data.get('motivo_cancelamento', '')
        texto_final = (
            "Máscara de cancelamento:\n\n"
            f"Pedido: {get('sa')}\n"
            f"Doc: {get('documento')}\n"
            f"Telefone: {get('telefone')}\n"
            f"Nome: {get('cliente')}\n"
            f"Motivo do cancelamento: {motivo}"
        )
        
    elif tipo == 'Repasse':
        # Pegar dados do usuário logado para o campo TECNICO
        user_id = update.effective_user.id
        db_user = await db.get_user(str(user_id))
        tecnico_nome = f"{db_user.get('nome','')} {db_user.get('sobrenome','')}".strip() if db_user else ""
        
        cidade = context.user_data.get('cidade_repasse', '')
        operadora = context.user_data.get('operadora_repasse', '')
        obs = context.user_data.get('obs_repasse', '')
        
        texto_final = (
            "MASCARA REPASSE\n\n"
            "🚨(×)REPARO\n\n"
            f"🚨 SA: {get('sa')}\n\n"
            f"🚨ACESSO GPON: {get('gpon')}\n\n"
            f"🚨DOC ASSOC: {get('documento')}\n\n"
            f"🚨 CDO: {get('cdo')}\n\n"
            f"🚨PORTA: {get('porta')}\n\n"
            f"🚨ENDERECO: {get('endereco')}\n\n"
            f"🚨CIDADE: {cidade}\n\n"
            f"🚨CLIENTE: {get('cliente')}\n\n"
            f"🚨CONTATO: {get('telefone')}\n\n"
            f"🚨OPERADORA: {operadora}\n\n"
            f"🚨TECNICO: {tecnico_nome}\n\n"
            f"🚨OBS: {obs}"
        )

    msg = f"✅ *Máscara Gerada com Sucesso!*\n\n```\n{texto_final}\n```\n\n👆 _Toque para copiar_"
    
    # Enviar a máscara
    if update.callback_query:
        try:
            await update.callback_query.message.delete()
        except:
            pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')
    
    # Limpar dados temporários
    context.user_data.pop('fotos_mascara', None)
    context.user_data.pop('dados_mascara', None)
    context.user_data.pop('tipo_mascara', None)
    context.user_data.pop('obs_batimento', None)
    context.user_data.pop('tipo_pendencia', None)
    context.user_data.pop('obs_pendencia', None)
    context.user_data.pop('motivo_cancelamento', None)
    context.user_data.pop('cidade_repasse', None)
    context.user_data.pop('operadora_repasse', None)
    context.user_data.pop('obs_repasse', None)
    
    # Retorna ao menu principal
    await exibir_menu_principal(update, context, update.effective_user.first_name, new_message=True)
    return ConversationHandler.END


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    raw_username = user.username or user.first_name
    # Escapar caracteres de Markdown V1 para evitar erro Bad Request
    username = raw_username.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
    
    # Verificar se usuário existe e se está bloqueado
    db_user = await db.get_user(str(user_id))
    
    if db_user and db_user.get('status') == 'bloqueado':
        keyboard = [[InlineKeyboardButton("💬 Falar com Admin", url="https://t.me/caioadmin")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '⛔ *Acesso Bloqueado*\n\n'
            'Seu acesso foi suspenso. Para regularizar, clique no botão abaixo ou chame: @caioadmin',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    if db_user and db_user.get('status') == 'pendente':
        await update.message.reply_text(
            '⏳ *Cadastro em Análise*\n\n'
            'Seu cadastro foi realizado e está aguardando aprovação do administrador.\n'
            'Você será notificado assim que for liberado.',
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    if not db_user:
        msg_text = (
            f'👋 Olá, {username}!\n\n'
            'Bem-vindo ao *Bot Técnico*.\n'
            'Para começar, preciso de alguns dados.\n\n'
            'Digite seu *Nome*:'
        )
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                msg_text,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                msg_text,
                parse_mode='Markdown'
            )
        return AGUARDANDO_NOME
    
    await exibir_menu_principal(update, context, username)
    return ConversationHandler.END

async def exibir_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str, new_message: bool = False):
    keyboard = [
        [InlineKeyboardButton("📝 Nova Instalação", callback_data='registrar')],
        [InlineKeyboardButton("🛠️ Novo Reparo", callback_data='registrar_reparo')],
        [InlineKeyboardButton("🔎 Consultar SA/GPON", callback_data='consultar')],
        [InlineKeyboardButton("📂 Minhas Instalações", callback_data='minhas')],
        [InlineKeyboardButton("📊 Produção do Ciclo", callback_data='consulta_producao')],
        [InlineKeyboardButton("🎭 Máscaras", callback_data='mascaras')],
        [InlineKeyboardButton("📈 Relatórios", callback_data='relatorios')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        '🤖 *Bot Técnico*\n'
        f'👤 {username}\n\n'
        '📡 Seu assistente de campo.\n'
        '🏆 Qualidade e agilidade. Bora bater meta hoje! 🚀'
    )
    
    if update.callback_query and not new_message:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        chat_id = update.effective_chat.id
        await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup, parse_mode='Markdown')

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nome = update.message.text.strip()
    context.user_data['nome'] = nome
    await update.message.reply_text('Ok! Agora digite seu *Sobrenome*:', parse_mode='Markdown')
    return AGUARDANDO_SOBRENOME

async def receber_sobrenome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sobrenome = update.message.text.strip()
    context.user_data['sobrenome'] = sobrenome
    await update.message.reply_text('Certo. Qual sua *Região*? (Ex: Centro, Norte, etc):', parse_mode='Markdown')
    return AGUARDANDO_REGIAO

async def receber_regiao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    regiao = update.message.text.strip()
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name
    
    novo_usuario = {
        'id': str(user_id),
        'nome': context.user_data['nome'],
        'sobrenome': context.user_data['sobrenome'],
        'regiao': regiao,
        'username': username,
        'status': 'pendente' # Novo status padrão
    }
    
    await db.save_user(novo_usuario)
    
    # Mensagem para o usuário
    await update.message.reply_text(
        '✅ *Cadastro Enviado!*\n\n'
        'Seus dados foram enviados para análise.\n'
        '⏳ Aguarde a aprovação do administrador para usar o bot.',
        parse_mode='Markdown'
    )
    
    # Notificar Admins
    esc_nome = novo_usuario['nome'].replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
    esc_sobrenome = novo_usuario['sobrenome'].replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
    esc_regiao = regiao.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
    esc_username = username.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

    msg_admin = (
        '👤 *Novo Cadastro Pendente*\n\n'
        f'Nome: {esc_nome} {esc_sobrenome}\n'
        f'Região: {esc_regiao}\n'
        f'User: @{esc_username}\n'
        f'ID: `{user_id}`'
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Aprovar", callback_data=f'access_set_ativo_{user_id}')],
        [InlineKeyboardButton("⛔ Bloquear", callback_data=f'access_set_bloqueado_{user_id}')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=msg_admin, reply_markup=reply_markup, parse_mode='Markdown')
        except:
            pass # Se admin bloqueou bot ou erro de rede

    return ConversationHandler.END


async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        '🆘 *Ajuda*\n\n'
        '/start - Menu Principal\n'
        '/producao - Ver produção atual\n'
        '/consultar - Consultar instalação\n'
        '/reparo - Registrar reparo\n'
        '/cancelar - Cancelar operação\n'
        '/admin - Painel Administrativo (apenas admins)'
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def meu_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    await update.message.reply_text(f'🆔 Seu ID: `{user_id}`', parse_mode='Markdown')

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Limpar TODOS os dados temporários
    context.user_data.clear()
    logger.info(f"Operação cancelada e memória limpa para usuário {update.effective_user.id}")
    await update.message.reply_text(
        '❌ Operação cancelada. Memória limpa.\n'
        'Use /start para voltar ao menu.'
    )
    return ConversationHandler.END

async def receber_sa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sa = update.message.text.strip()
    context.user_data['sa'] = sa
    await update.message.reply_text(
        f'✅ *SA Registrada com Sucesso!*\n'
        f'📋 SA: `{sa}`\n\n'
        f'📝 *[Etapa 2/5]*\n'
        f'Agora digite o *GPON*:\n'
        f'💡 Exemplo: ABCD1234\n\n'
        f'_(Digite /cancelar para voltar)_',
        parse_mode='Markdown'
    )
    return AGUARDANDO_GPON

async def receber_print_autofill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-2] if len(update.message.photo) > 1 else update.message.photo[-1]
    try:
        file = await photo.get_file()
    except Exception:
        await update.message.reply_text('❌ Não consegui acessar a imagem. Envie novamente ou digite a SA.')
        return AGUARDANDO_SA
    image_bytes = None
    try:
        out = io.BytesIO()
        await file.download_to_memory(out)
        image_bytes = out.getvalue()
    except Exception:
        try:
            if hasattr(file, 'download_as_bytearray'):
                ba = await file.download_as_bytearray()
                image_bytes = bytes(ba)
        except Exception:
            try:
                tmp = f"tmp_{photo.file_unique_id}.jpg"
                await file.download_to_drive(tmp)
                with open(tmp, 'rb') as f:
                    image_bytes = f.read()
                try:
                    os.remove(tmp)
                except Exception:
                    pass
            except Exception:
                pass
    if not image_bytes:
        await update.message.reply_text('❌ Não consegui processar a imagem. Envie novamente (print recortado) ou digite a SA.')
        return AGUARDANDO_SA
    imgs = context.user_data.get('autofill_images') or []
    imgs.append(image_bytes)
    context.user_data['autofill_images'] = imgs
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
    
    data = await extrair_campos_por_imagens(imgs)
    if not data.get('sa'):
        d_sa = await extrair_campo_especifico(imgs, 'sa')
        if d_sa.get('sa'):
            data['sa'] = d_sa['sa']
    if not data.get('gpon'):
        d_gpon = await extrair_campo_especifico(imgs, 'gpon')
        if d_gpon.get('gpon'):
            data['gpon'] = d_gpon['gpon']
    if not data.get('serial_do_modem'):
        d_serial = await extrair_campo_especifico(imgs, 'serial_do_modem')
        if d_serial.get('serial_do_modem'):
            data['serial_do_modem'] = d_serial['serial_do_modem']
    # Não extrair mesh nesta etapa para evitar falsos positivos
    # data['mesh'] = []  <-- Removido para permitir preenchimento de mesh
    sa = data.get('sa')
    gpon = data.get('gpon')
    serial_modem = data.get('serial_do_modem')
    
    # Filtrar mesh: válido e diferente do modem principal
    mesh_list = [
        m for m in (data.get('mesh') or []) 
        if is_valid_serial(m) and m != serial_modem
    ]
    if sa:
        context.user_data['sa'] = sa
    if gpon:
        context.user_data['gpon'] = gpon
    if serial_modem and is_valid_serial(serial_modem):
        context.user_data['serial_modem'] = serial_modem
    else:
        serial_modem = None
    if mesh_list:
        context.user_data['mesh_candidates'] = mesh_list
        mesh_text = ', '.join(mesh_list)
    else:
        mesh_text = 'não informado'
    msg = (
        '🧠 *Autopreenchimento por Foto*\n\n'
        f"SA: `{escape_markdown(sa)}`\n"
        f"GPON: `{escape_markdown(gpon)}`\n"
        f"Serial Modem: `{escape_markdown(serial_modem)}`\n"
        f"Mesh: `{escape_markdown(mesh_text)}`\n"
        f"Prints usados: {len(imgs)}\n\n"
    )
    await update.message.reply_text(msg, parse_mode='Markdown')
    if sa and gpon:
        # Verificar modo_registro para mostrar os botões corretos
        modo = context.user_data.get('modo_registro') or 'instalacao'
        logger.info(f"Autopreenchimento detectou SA e GPON - modo: {modo}")
        
        if modo == 'reparo':
            keyboard = [
                [InlineKeyboardButton('Defeito Banda Larga', callback_data='defeito_banda_larga')],
                [InlineKeyboardButton('Defeito Linha', callback_data='defeito_linha')],
                [InlineKeyboardButton('Defeito TV', callback_data='defeito_tv')],
                [InlineKeyboardButton('Mudança de Endereço', callback_data='mudanca_endereco')],
                [InlineKeyboardButton('Retirada', callback_data='retirada')],
                [InlineKeyboardButton('Serviços', callback_data='servicos')]
            ]
            prompt_text = 'Selecione o *tipo de reparo*:'
        else:
            keyboard = [
                [InlineKeyboardButton('Instalação', callback_data='instalacao')],
                [InlineKeyboardButton('Instalação TV', callback_data='instalacao_tv')],
                [InlineKeyboardButton('Instalação + Mesh', callback_data='instalacao_mesh')],
                [InlineKeyboardButton('Instalação FTTR', callback_data='instalacao_fttr')],
                [InlineKeyboardButton('Mudança de Endereço', callback_data='mudanca_endereco')],
                [InlineKeyboardButton('Serviços', callback_data='servicos')]
            ]
            prompt_text = 'Selecione o *tipo de serviço*:'
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(prompt_text, reply_markup=reply_markup, parse_mode='Markdown')
        return AGUARDANDO_TIPO
    if not sa:
        await update.message.reply_text('Envie o *número da SA*:', parse_mode='Markdown')
        return AGUARDANDO_SA
    await update.message.reply_text('Agora digite o *GPON*:', parse_mode='Markdown')
    return AGUARDANDO_GPON

async def receber_gpon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    gpon = update.message.text.strip()
    context.user_data['gpon'] = gpon
    context.user_data['fotos'] = []
    
    modo = context.user_data.get('modo_registro') or 'instalacao'
    
    if modo == 'reparo':
        keyboard = [
            [InlineKeyboardButton('Defeito Banda Larga', callback_data='defeito_banda_larga')],
            [InlineKeyboardButton('Defeito Linha', callback_data='defeito_linha')],
            [InlineKeyboardButton('Defeito TV', callback_data='defeito_tv')],
            [InlineKeyboardButton('Mudança de Endereço', callback_data='mudanca_endereco')],
            [InlineKeyboardButton('Retirada', callback_data='retirada')],
            [InlineKeyboardButton('Serviços', callback_data='servicos')]
        ]
        prompt = (
            '✅ *GPON Registrado!*\n'
            f'🔗 GPON: `{gpon}`\n\n'
            '📝 *[Etapa 3/5]*\n'
            'Selecione o *tipo de reparo*:'
        )
    else:
        keyboard = [
            [InlineKeyboardButton('Instalação', callback_data='instalacao')],
            [InlineKeyboardButton('Instalação TV', callback_data='instalacao_tv')],
            [InlineKeyboardButton('Instalação + Mesh', callback_data='instalacao_mesh')],
            [InlineKeyboardButton('Instalação FTTR', callback_data='instalacao_fttr')],
            [InlineKeyboardButton('Mudança de Endereço', callback_data='mudanca_endereco')],
            [InlineKeyboardButton('Serviços', callback_data='servicos')]
        ]
        prompt = (
            '✅ *GPON Registrado!*\n'
            f'🔗 GPON: `{gpon}`\n\n'
            '📝 *[Etapa 3/5]*\n'
            'Selecione o *tipo de serviço*:'
        )
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(prompt, reply_markup=reply_markup, parse_mode='Markdown')
    return AGUARDANDO_TIPO

async def receber_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tipo = query.data
    context.user_data['tipo'] = tipo
    
    tipos_com_serial = ['instalacao', 'instalacao_tv', 'instalacao_mesh', 'instalacao_fttr', 'mudanca_endereco', 'defeito_banda_larga', 'defeito_linha', 'defeito_tv']
    
    if tipo in tipos_com_serial:
        # Se for REPARO, perguntar se houve troca de ONT
        if context.user_data.get('modo_registro') == 'reparo':
            keyboard = [
                [InlineKeyboardButton("Sim", callback_data='trocou_ont_sim')],
                [InlineKeyboardButton("Não", callback_data='trocou_ont_nao')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                '🛠️ *Troca de Equipamento*\n\n'
                'Houve troca da ONT (Modem)?',
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return AGUARDANDO_TROCA_ONT
            
        await query.edit_message_text(
            '✅ *Tipo Selecionado!*\n'
            '📝 *[Etapa 4/5]*\n'
            'Agora envie o *Número de Série do Modem*:\n'
            '💡 Exemplo: ZTEGC8...\n\n'
            '_(Ou digite /cancelar para sair)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SERIAL
    else:
        await query.edit_message_text(
            '✅ *Tipo Selecionado!*\n'
            '📝 *[Etapa 5/5]*\n'
            'Agora envie as *3 fotos* da instalação.\n'
            '💡 Tire fotos claras.\n'
            'Quando terminar, digite /finalizar',
            parse_mode='Markdown'
        )
        return AGUARDANDO_FOTOS

async def verificar_troca_ont(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'trocou_ont_sim':
        await query.edit_message_text(
            '✅ *Troca Confirmada*\n'
            '📝 *[Etapa 4/5]*\n'
            'Agora envie o *Novo Serial do Modem*:\n'
            '💡 Exemplo: ZTEGC8...\n\n'
            '_(Ou digite /cancelar para sair)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SERIAL
        
    else: # trocou_ont_nao
        # Força "Não Trocado" para não exibir serial antigo/errado
        context.user_data['serial_modem'] = 'Não Trocado'
            
        await query.edit_message_text(
            '✅ *Equipamento Mantido*\n'
            '📝 *[Etapa 5/5]*\n'
            'Agora envie as *3 fotos* do reparo.\n'
            'Quando terminar, digite /finalizar',
            parse_mode='Markdown'
        )
        return AGUARDANDO_FOTOS

async def receber_serial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    serial = update.message.text.strip()
    context.user_data['serial_modem'] = serial
    
    if context.user_data.get('tipo') == 'instalacao_mesh':
        await update.message.reply_text(
            '✅ *Serial Modem Registrado!*\n'
            '📝 *[Etapa 5/6]*\n'
            'Agora envie o *Serial do Roteador Mesh*:\n'
            '_(Ou digite /cancelar para sair)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SERIAL_MESH

    if context.user_data.get('tipo') == 'instalacao_fttr':
        await update.message.reply_text(
            '✅ *Serial Modem Registrado!*\n'
            '📝 *[Etapa 5/6]*\n'
            'Agora envie os *Seriais dos APs Repetidores FTTR*:\n'
            '💡 Se houver mais de um, separe por vírgula ou espaço.\n'
            '_(Ou digite /cancelar para sair)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SERIAL_MESH
    
    await update.message.reply_text(
        '✅ *Serial Registrado!*\n'
        '📝 *[Etapa 5/5]*\n'
        'Agora envie as *3 fotos* da instalação.\n'
        'Quando terminar, digite /finalizar',
        parse_mode='Markdown'
    )
    return AGUARDANDO_FOTOS

async def receber_serial_por_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-2] if len(update.message.photo) > 1 else update.message.photo[-1]
    image_bytes = None
    try:
        file = await photo.get_file()
        out = io.BytesIO()
        await file.download_to_memory(out)
        image_bytes = out.getvalue()
        if not image_bytes and hasattr(file, 'download_as_bytearray'):
            ba = await file.download_as_bytearray()
            image_bytes = bytes(ba)
        if not image_bytes:
            tmp = f"tmp_{photo.file_unique_id}.jpg"
            await file.download_to_drive(tmp)
            with open(tmp, 'rb') as f:
                image_bytes = f.read()
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Falha ao baixar foto do serial: {e}")
        await update.message.reply_text('❌ Não consegui processar a imagem. Envie novamente ou digite o serial.')
        return AGUARDANDO_SERIAL
    imgs = context.user_data.get('autofill_images') or []
    imgs.append(image_bytes)
    context.user_data['autofill_images'] = imgs
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
    
    d = await extrair_campo_especifico(imgs, 'serial_do_modem')
    serial = d.get('serial_do_modem')
    if not serial or not is_valid_serial(serial):
        await update.message.reply_text('❌ Não consegui extrair o serial. Digite o número de série do modem.')
        return AGUARDANDO_SERIAL
    context.user_data['serial_modem'] = serial
    if context.user_data.get('tipo') == 'instalacao_mesh':
        # Se já houver candidatos de mesh detectados anteriormente, pré-preenche
        mesh_candidates = context.user_data.get('mesh_candidates') or []
        if mesh_candidates and not context.user_data.get('serial_mesh'):
            context.user_data['serial_mesh'] = mesh_candidates[0]
            await update.message.reply_text(
                f"✅ *Serial Modem Detectado!*\n\n📶 Mesh detectado: `{escape_markdown(mesh_candidates[0])}`\n📝 *[Etapa 5/6]*\nSe quiser alterar, envie uma foto do roteador mesh; caso contrário, siga com as fotos da instalação.",
                parse_mode='Markdown'
            )
            return AGUARDANDO_SERIAL_MESH
        await update.message.reply_text('✅ *Serial Modem Detectado!*\n\n📝 *[Etapa 5/6]*\nAgora envie o *Serial do Roteador Mesh*:', parse_mode='Markdown')
        return AGUARDANDO_SERIAL_MESH

    if context.user_data.get('tipo') == 'instalacao_fttr':
        mesh_candidates = context.user_data.get('mesh_candidates') or []
        if mesh_candidates and not context.user_data.get('serial_mesh'):
            seriais_fttr = ', '.join(mesh_candidates)
            context.user_data['serial_mesh'] = seriais_fttr
            await update.message.reply_text(
                f"✅ *Serial Modem Detectado!*\n\n📶 APs FTTR detectados: `{escape_markdown(seriais_fttr)}`\n📝 *[Etapa 5/6]*\nSe quiser alterar, envie uma foto ou digite os seriais; caso contrário, siga com as fotos da instalação.",
                parse_mode='Markdown'
            )
            return AGUARDANDO_SERIAL_MESH
        await update.message.reply_text('✅ *Serial Modem Detectado!*\n\n📝 *[Etapa 5/6]*\nAgora envie os *Seriais dos APs Repetidores FTTR*:', parse_mode='Markdown')
        return AGUARDANDO_SERIAL_MESH

    await update.message.reply_text('✅ *Serial Detectado!*\n\n📝 *[Etapa 5/5]*\nAgora envie as *3 fotos* da instalação.\nQuando terminar, digite /finalizar', parse_mode='Markdown')
    return AGUARDANDO_FOTOS

async def receber_serial_mesh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    serial_mesh = update.message.text.strip()
    context.user_data['serial_mesh'] = serial_mesh
    await update.message.reply_text(
        '✅ *Serial Mesh Registrado!*\n'
        '📝 *[Etapa 6/6]*\n'
        'Agora envie as *3 fotos* da instalação.\n'
        'Quando terminar, digite /finalizar',
        parse_mode='Markdown'
    )
    return AGUARDANDO_FOTOS

async def receber_serial_mesh_por_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-2] if len(update.message.photo) > 1 else update.message.photo[-1]
    image_bytes = None
    try:
        file = await photo.get_file()
        out = io.BytesIO()
        await file.download_to_memory(out)
        image_bytes = out.getvalue()
        if not image_bytes and hasattr(file, 'download_as_bytearray'):
            ba = await file.download_as_bytearray()
            image_bytes = bytes(ba)
        if not image_bytes:
            tmp = f"tmp_{photo.file_unique_id}.jpg"
            await file.download_to_drive(tmp)
            with open(tmp, 'rb') as f:
                image_bytes = f.read()
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Falha ao baixar foto do mesh: {e}")
        await update.message.reply_text('❌ Não consegui processar a imagem. Envie novamente ou digite o serial mesh.')
        return AGUARDANDO_SERIAL_MESH
    imgs = context.user_data.get('autofill_images') or []
    imgs.append(image_bytes)
    context.user_data['autofill_images'] = imgs
    
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)
    
    d = await extrair_campo_especifico(imgs, 'mesh')
    mesh_list = [m for m in (d.get('mesh') or []) if is_valid_serial(m)]
    
    if not mesh_list:
        await update.message.reply_text('❌ Não consegui extrair o serial mesh/FTTR. Digite manualmente.')
        return AGUARDANDO_SERIAL_MESH
        
    if context.user_data.get('tipo') == 'instalacao_fttr':
        # Para FTTR, pega todos os encontrados
        seriais_fttr = ', '.join(mesh_list)
        context.user_data['serial_mesh'] = seriais_fttr
        await update.message.reply_text(f'✅ *Seriais FTTR Detectados!*\n`{seriais_fttr}`\n\n📝 *[Etapa 6/6]*\nAgora envie as *3 fotos* da instalação.\nQuando terminar, digite /finalizar', parse_mode='Markdown')
    else:
        # Para Mesh normal, pega o primeiro
        context.user_data['serial_mesh'] = mesh_list[0]
        await update.message.reply_text('✅ *Serial Mesh Detectado!*\n\n📝 *[Etapa 6/6]*\nAgora envie as *3 fotos* da instalação.\nQuando terminar, digite /finalizar', parse_mode='Markdown')
        
    return AGUARDANDO_FOTOS

async def receber_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'fotos' not in context.user_data:
        context.user_data['fotos'] = []
    
    photo = update.message.photo[-1]
    context.user_data['fotos'].append(photo.file_id)
    
    num_fotos = len(context.user_data['fotos'])
    
    if num_fotos < 3:
        await update.message.reply_text(
            f'✅ *Foto {num_fotos}/3 Recebida!*\n'
            f'{"🟢" * num_fotos}{"⚪" * (3-num_fotos)}\n\n'
            f'Envie mais {3 - num_fotos} foto(s).',
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f'✅ *{num_fotos} fotos recebidas!*\n'
            f'{"🟢" * 3}\n\n'
            'Digite /finalizar para salvar.',
            parse_mode='Markdown'
        )
    return AGUARDANDO_FOTOS

async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'sa' not in context.user_data or 'gpon' not in context.user_data:
        await update.message.reply_text('❌ Erro: Dados incompletos. Use /start para recomeçar.')
        return ConversationHandler.END
    
    user_id = update.message.from_user.id
    user_data = await db.get_user(str(user_id))
    
    tecnico_nome = (f"{user_data.get('nome','')} {user_data.get('sobrenome','')}".strip() if user_data else (update.message.from_user.username or update.message.from_user.first_name))
    tecnico_regiao = (user_data.get('regiao') if user_data else None)
    
    # Determinar tipo e categoria corretamente
    tipo = context.user_data.get('tipo') or 'instalacao'
    modo_registro = context.user_data.get('modo_registro')
    
    # Inferir categoria baseada no tipo (mais confiável que modo_registro)
    if tipo in TIPOS_REPARO:
        categoria = 'reparo'
        logger.info(f"Categoria inferida como REPARO (tipo: {tipo})")
    elif tipo in TIPOS_INSTALACAO:
        categoria = 'instalacao'
        logger.info(f"Categoria inferida como INSTALAÇÃO (tipo: {tipo})")
    else:
        # Para tipos ambíguos, usar modo_registro se disponível
        categoria = context.user_data.get('modo_registro') or 'instalacao'
        logger.info(f"Categoria ambígua (tipo: {tipo}), usando modo_registro: {modo_registro} → categoria: {categoria}")
    
    nova_instalacao = {
        'sa': context.user_data['sa'],
        'gpon': context.user_data['gpon'],
        'tipo': tipo,
        'categoria': categoria,
        'fotos': context.user_data.get('fotos', []),
        'tecnico_id': user_id,
        'tecnico_nome': tecnico_nome,
        'tecnico_regiao': tecnico_regiao,
        'serial_modem': context.user_data.get('serial_modem'),
        'serial_mesh': context.user_data.get('serial_mesh'),
        'data': datetime.now(TZ).strftime('%d/%m/%Y %H:%M')
    }
    
    # Remover Nones
    nova_instalacao = {k: v for k, v in nova_instalacao.items() if v is not None}
    
    ok = await db.save_installation(nova_instalacao)
    
    def escape_markdown_v2(text):
        if text is None:
            return 'não informada'
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
        for char in special_chars:
            text = str(text).replace(char, f'\\{char}')
        return text
    
    if ok:
        logger.info(f"✅ {nova_instalacao['categoria'].upper()} salvo com sucesso - SA: {nova_instalacao['sa']}, Tipo: {nova_instalacao['tipo']}")
        titulo = '✅ *REPARO REGISTRADO*' if nova_instalacao['categoria'] == 'reparo' else '✅ *INSTALAÇÃO REGISTRADA*'
        msg_parts = [
            '━━━━━━━━━━━━━━━━━━━━\n',
            f'{titulo}\n',
            '━━━━━━━━━━━━━━━━━━━━\n\n',
            '📋 *Detalhes:*\n',
            f'🔖 SA: `{nova_instalacao["sa"]}`\n',
            f'🔗 GPON: `{nova_instalacao["gpon"]}`\n'
        ]
    
        if nova_instalacao.get("serial_modem") and nova_instalacao.get("serial_modem") != 'Não Trocado':
            msg_parts.append(f'📟 Serial Modem: `{nova_instalacao["serial_modem"]}`\n')
            
        if nova_instalacao.get("serial_mesh"):
            label_mesh = "Seriais FTTR" if nova_instalacao['tipo'] == 'instalacao_fttr' else "Serial Mesh"
            msg_parts.append(f'📶 {label_mesh}: `{nova_instalacao["serial_mesh"]}`\n')
    
        status_msg = '📡 Cliente conectado\\! 📈 Produção atualizada' if nova_instalacao['categoria'] != 'reparo' else '🛠️ Atendimento registrado\\! 📈 Produção atualizada'
        registro_msg = '📝 Instalação registrada no @tecnico\\_bot\\!' if nova_instalacao['categoria'] != 'reparo' else '🛠️ Reparo registrado no @tecnico\\_bot\\!'

        msg_parts.extend([
            f'🧩 Tipo: {escape_markdown_v2(nova_instalacao["tipo"])}\n',
            f'🏷️ Categoria: {escape_markdown_v2(nova_instalacao["categoria"])}\n',
            f'📸 Fotos: {len(nova_instalacao["fotos"])}\n\n',
            f'👤 *Técnico:* {escape_markdown_v2(nova_instalacao["tecnico_nome"])}\n',
            f'📍 *Região:* {escape_markdown_v2(nova_instalacao["tecnico_regiao"])}\n',
            f'📅 *Data:* {escape_markdown_v2(nova_instalacao["data"])}\n\n',
            '🎉 Ótimo trabalho\\!\n',
            f'{status_msg}\n',
            f'{registro_msg}\n'
        ])
        
        summary_text = ''.join(msg_parts)
        
        # Enviar Album (Fotos + Caption) se houver fotos
        fotos_ids = nova_instalacao.get('fotos', [])
        if fotos_ids:
            media_group = []
            for i, file_id in enumerate(fotos_ids):
                # Apenas a primeira foto leva o caption
                if i == 0:
                    media_group.append(InputMediaPhoto(media=file_id, caption=summary_text, parse_mode='MarkdownV2'))
                else:
                    media_group.append(InputMediaPhoto(media=file_id))
            
            try:
                await update.message.reply_media_group(media=media_group)
            except Exception as e:
                logger.error(f"Erro ao enviar album: {e}")
                # Fallback se falhar album: envia texto normal
                await update.message.reply_text(summary_text, parse_mode='MarkdownV2')
        else:
            # Sem fotos, envia só texto
            await update.message.reply_text(summary_text, parse_mode='MarkdownV2')

        # === NOTIFICAÇÃO DE PROGRESSO (QUASE LÁ) ===
        try:
            inicio, fim = ciclo_atual()
            insts_ciclo = await db.get_installations({
                'tecnico_id': user_id, 
                'data_inicio': inicio, 
                'data_fim': fim
            })
            pontos_totais = calcular_pontos(insts_ciclo)
            msg_progresso = gerar_resumo_progresso(pontos_totais)
            
            # Adicionar dica de encaminhamento
            msg_progresso += "\n👆 _Dica: Segure nas fotos acima para encaminhar ao grupo!_"
            
            # Envia em mensagem separada usando Markdown V1 com botões de ação rápida
            keyboard_acoes = [
                [InlineKeyboardButton("📝 Nova Instalação", callback_data='registrar')],
                [InlineKeyboardButton("🛠️ Novo Reparo", callback_data='registrar_reparo')],
                [InlineKeyboardButton("🏠 Voltar ao Menu", callback_data='voltar')]
            ]
            reply_markup_acoes = InlineKeyboardMarkup(keyboard_acoes)
            
            await update.message.reply_text(msg_progresso, parse_mode='Markdown', reply_markup=reply_markup_acoes)
        except Exception as e:
            logger.error(f"Erro ao gerar notificacao de progresso: {e}")

    else:
        keyboard = [[InlineKeyboardButton("🔄 Tentar Novamente", callback_data='retry_save')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '❌ Erro ao salvar no banco de dados. Tente novamente.',
            reply_markup=reply_markup
        )
        return AGUARDANDO_FOTOS # Mantém no estado para retry
    
    # Limpar dados temporários para evitar memory leak
    context.user_data.clear()
    logger.info(f"Memória limpa para usuário {update.effective_user.id}")
    return ConversationHandler.END

async def consultar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_busca = update.message.text.strip()
    
    # Buscar TODAS as instalações
    insts = await db.get_installations(limit=5000)
    
    # Busca em memória (substring match)
    termo = texto_busca.lower()
    resultados = []
    for d in insts:
        sa = str(d.get('sa') or '').lower()
        gpon = str(d.get('gpon') or '').lower()
        serial = str(d.get('serial_modem') or '').lower()
        if termo in sa or termo in gpon or termo in serial:
            resultados.append(d)
    
    if not resultados:
        await update.message.reply_text(
            f'❌ Nenhuma instalação encontrada para: `{texto_busca}`',
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    # Limitar resultados para evitar spam
    MAX_RESULTADOS = 5
    total = len(resultados)
    
    if total > MAX_RESULTADOS:
        await update.message.reply_text(
            f'🔍 Encontradas *{total} instalações*\n'
            f'Mostrando as primeiras {MAX_RESULTADOS}.\n'
            f'💡 _Seja mais específico para refinar a busca._',
            parse_mode='Markdown'
        )
        resultados = resultados[:MAX_RESULTADOS]
    
    for resultado in resultados:
        # Construir mensagem com Markdown simples
        tipo = resultado.get('tipo', 'instalacao').replace('_', ' ').title()
        tecnico = resultado.get('tecnico_nome', 'N/A')
        data = resultado.get('data', 'N/A')
        serial = resultado.get('serial_modem', '')
        mesh_list = resultado.get('mesh', [])
        
        msg = (
            f'📋 *SA:* `{resultado["sa"]}`\n'
            f'🔗 *GPON:* `{resultado["gpon"]}`\n'
        )
        
        if serial:
            msg += f'📟 *Serial Modem:* `{serial}`\n'
        
        if mesh_list:
            mesh_text = ', '.join([f'`{m}`' for m in mesh_list[:3]])
            if len(mesh_list) > 3:
                mesh_text += f' (+{len(mesh_list)-3})'
            msg += f'📶 *Mesh:* {mesh_text}\n'
        
        msg += (
            f'🧩 *Tipo:* {tipo}\n'
            f'👤 *Técnico:* {tecnico}\n'
            f'📅 *Data:* {data}\n'
            f'📸 *Fotos:* {len(resultado.get("fotos", []))}'
        )
        
        try:
            await update.message.reply_text(msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Erro ao enviar mensagem de consulta: {e}")
            # Fallback sem formatação
            await update.message.reply_text(
                f'SA: {resultado["sa"]}\n'
                f'GPON: {resultado["gpon"]}\n'
                f'Tipo: {tipo}\n'
                f'Técnico: {tecnico}\n'
                f'Data: {data}'
            )
        
        # Enviar as fotos
        fotos = resultado.get('fotos', [])
        if fotos:
            # Enviar no máximo 3 fotos por consulta
            for foto_id in fotos[:3]:
                try:
                    await update.message.reply_photo(photo=foto_id)
                except Exception as e:
                    logger.error(f"Erro ao enviar foto: {e}")
                    
    return ConversationHandler.END

async def comando_consultar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tem_acesso, msg_erro = await verificar_acesso_usuario(update.message.from_user.id)
    if not tem_acesso:
        await update.message.reply_text(msg_erro, parse_mode='Markdown')
        return ConversationHandler.END
    
    await update.message.reply_text('🔎 Digite o SA, GPON ou Serial do Modem para buscar:')
    return AGUARDANDO_CONSULTA

async def comando_reparo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tem_acesso, msg_erro = await verificar_acesso_usuario(update.message.from_user.id)
    if not tem_acesso:
        await update.message.reply_text(msg_erro, parse_mode='Markdown')
        return ConversationHandler.END
    
    context.user_data['modo_registro'] = 'reparo'
    logger.info(f"Usuário {update.message.from_user.id} iniciou REPARO via comando /reparo")
    await update.message.reply_text('🛠️ *Novo Reparo*\nEnvie o *número da SA:*', parse_mode='Markdown')
    return AGUARDANDO_SA

async def comando_producao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tem_acesso, msg_erro = await verificar_acesso_usuario(update.message.from_user.id)
    if not tem_acesso:
        await update.message.reply_text(msg_erro, parse_mode='Markdown')
        return
    
    # Atalho para produção
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "User"
    inicio_dt, fim_dt = ciclo_atual()
    insts = await db.get_installations({'tecnico_id': user_id, 'data_inicio': inicio_dt, 'data_fim': fim_dt})
    msg = gerar_texto_producao(insts, inicio_dt, fim_dt, username)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def comando_mensal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /mensal - Relatório do mês atual"""
    tem_acesso, msg_erro = await verificar_acesso_usuario(update.message.from_user.id)
    if not tem_acesso:
        await update.message.reply_text(msg_erro, parse_mode='Markdown')
        return
    
    from reports import gerar_relatorio_mensal
    insts = await db.get_installations(limit=5000)
    msg = gerar_relatorio_mensal(insts)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def comando_semanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /semanal - Relatório da semana atual"""
    tem_acesso, msg_erro = await verificar_acesso_usuario(update.message.from_user.id)
    if not tem_acesso:
        await update.message.reply_text(msg_erro, parse_mode='Markdown')
        return
    
    from reports import gerar_relatorio_semanal
    insts = await db.get_installations(limit=5000)
    msg = gerar_relatorio_semanal(insts)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def comando_hoje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /hoje - Relatório de hoje"""
    tem_acesso, msg_erro = await verificar_acesso_usuario(update.message.from_user.id)
    if not tem_acesso:
        await update.message.reply_text(msg_erro, parse_mode='Markdown')
        return
    
    from reports import gerar_relatorio_hoje
    insts = await db.get_installations(limit=5000)
    msg = gerar_relatorio_hoje(insts)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def receber_data_inicio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a data inicial para relatório por período"""
    texto = update.message.text.strip()
    try:
        inicio = datetime.strptime(texto, '%d/%m/%Y')
        context.user_data['data_inicio'] = inicio
        await update.message.reply_text(
            'Agora envie a *data final* no formato `dd/mm/aaaa`:',
            parse_mode='Markdown'
        )
        return AGUARDANDO_DATA_FIM
    except:
        await update.message.reply_text('❌ Data inválida. Use o formato dd/mm/aaaa.')
        return AGUARDANDO_DATA_INICIO

async def receber_data_fim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a data final e gera relatório por período"""
    texto = update.message.text.strip()
    try:
        fim = datetime.strptime(texto, '%d/%m/%Y')
    except:
        await update.message.reply_text('❌ Data inválida. Use o formato dd/mm/aaaa.')
        return AGUARDANDO_DATA_FIM
        
    inicio = context.user_data.get('data_inicio')
    if not inicio:
        await update.message.reply_text('❌ Erro: data inicial não encontrada.')
        return ConversationHandler.END
        
    if fim < inicio:
        await update.message.reply_text('❌ A data final é anterior à inicial.')
        return AGUARDANDO_DATA_FIM
    
    # Buscar instalações do período
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "User"
    
    inicio_dt = inicio.replace(hour=0, minute=0, second=0, tzinfo=TZ)
    fim_dt = fim.replace(hour=23, minute=59, second=59, tzinfo=TZ)
    
    insts = await db.get_installations({
        'tecnico_id': user_id,
        'data_inicio': inicio_dt,
        'data_fim': fim_dt
    })
    
    if not insts:
        await update.message.reply_text(
            f'❌ Nenhuma instalação entre {inicio.strftime("%d/%m/%Y")} e {fim.strftime("%d/%m/%Y")}.'
        )
        context.user_data.pop('data_inicio', None)
        return ConversationHandler.END
    
    # Gerar relatório
    msg = gerar_texto_producao(insts, inicio_dt, fim_dt, username)
    await update.message.reply_text(msg, parse_mode='Markdown')
    
    context.user_data.pop('data_inicio', None)
    return ConversationHandler.END
