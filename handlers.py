from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from datetime import datetime
from config import *
from database import db
from utils import ciclo_atual, escape_markdown
from reports import gerar_texto_producao, gerar_ranking_texto
import logging

logger = logging.getLogger(__name__)

# ==================== FUNÇÕES AUXILIARES DE MENU ====================

async def exibir_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    keyboard = [
        [InlineKeyboardButton("🆕 Registrar Instalação", callback_data='registrar')],
        [InlineKeyboardButton("🛠️ Registrar Reparo", callback_data='registrar_reparo')],
        [InlineKeyboardButton("🔎 Consultar SA/GPON", callback_data='consultar')],
        [InlineKeyboardButton("📂 Minhas Instalações", callback_data='minhas')],
        [InlineKeyboardButton("📅 Consulta Produção", callback_data='consulta_producao')],
        [InlineKeyboardButton("📊 Relatórios", callback_data='relatorios')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        '━━━━━━━━━━━━━━━━━━━━\n'
        '🛠️ *TÉCNICO BOT*\n'
        '━━━━━━━━━━━━━━━━━━━━\n\n'
        f'👋 Olá, *{username}*!\n'
        f'📅 {datetime.now(TZ).strftime("%d/%m/%Y")}\n\n'
        'Escolha uma opção abaixo:'
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== HANDLERS DE COMANDO ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name
    
    # Verificar se usuário existe
    user_data = await db.get_user(str(user_id))
    
    if not user_data:
        context.user_data['ident'] = {}
        await update.message.reply_text(
            '👋 *Bem-vindo ao TÉCNICO BOT!*\n\n'
            'Para começar, vamos configurar seu perfil.\n\n'
            '📝 Por favor, informe seu *primeiro nome*:\n'
            '_(Digite /cancelar a qualquer momento para sair)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_NOME
    
    await exibir_menu_principal(update, context, username)
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('❌ Operação cancelada. Use /start para começar novamente.')
    context.user_data.clear()
    return ConversationHandler.END

async def ajuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        '🆘 *Central de Ajuda*\n\n'
        'Aqui estão os comandos disponíveis:\n\n'
        '🔹 /start - Iniciar o bot e ver o menu principal\n'
        '🔹 /ajuda - Ver esta mensagem de ajuda\n'
        '🔹 /cancelar - Cancelar a operação atual\n'
        '🔹 /meuid - Descobrir seu ID do Telegram\n'
        '🔹 /mensal - Relatório de produção mensal\n'
        '🔹 /semanal - Relatório de produção semanal\n'
        '🔹 /hoje - Relatório de produção de hoje\n'
        '🔹 /consultar - Consultar uma instalação por SA ou GPON\n'
        '🔹 /reparo - Iniciar registro de reparo rápido\n'
        '🔹 /producao - Consultar produção por período\n\n'
        '💡 *Dica:* Se ficar preso em alguma etapa, digite /cancelar para voltar ao início.'
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def meu_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "Não definido"
    first_name = update.message.from_user.first_name
    
    msg = (
        f'🆔 *Suas Informações*\n\n'
        f'👤 Nome: {first_name}\n'
        f'🔖 Username: @{username}\n'
        f'🔢 **ID do Telegram:** `{user_id}`\n\n'
        f'💡 *Para se tornar admin:*\n'
        f'Envie este ID para o administrador do sistema.'
    )
    await update.message.reply_text(msg, parse_mode='Markdown')

# ==================== FLUXO DE REGISTRO (CADASTRO INICIAL) ====================

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault('ident', {})
    context.user_data['ident']['nome'] = update.message.text.strip()
    await update.message.reply_text(
        '📝 Ótimo! Agora informe seu *sobrenome*:\n'
        '_(Ou /cancelar para sair)_',
        parse_mode='Markdown'
    )
    return AGUARDANDO_SOBRENOME

async def receber_sobrenome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault('ident', {})
    context.user_data['ident']['sobrenome'] = update.message.text.strip()
    await update.message.reply_text(
        '📍 Para finalizar, informe sua *região de atuação*:\n'
        '_(Ou /cancelar para sair)_',
        parse_mode='Markdown'
    )
    return AGUARDANDO_REGIAO

async def receber_regiao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    regiao = update.message.text.strip()
    user_id = update.message.from_user.id
    ident = context.user_data.get('ident', {})
    
    dados_usuario = {
        'id': str(user_id),
        'nome': ident.get('nome', ''),
        'sobrenome': ident.get('sobrenome', ''),
        'regiao': regiao,
        'telegram': update.message.from_user.username or update.message.from_user.first_name
    }
    
    ok = await db.save_user(dados_usuario)
    
    if ok:
        await update.message.reply_text('✅ Perfil salvo com sucesso!', parse_mode='Markdown')
        await exibir_menu_principal(update, context, dados_usuario['telegram'])
    else:
        await update.message.reply_text('❌ Erro ao salvar perfil. Tente novamente mais tarde.')
        
    context.user_data.pop('ident', None)
    return ConversationHandler.END

# ==================== FLUXO DE INSTALAÇÃO/REPARO ====================

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'registrar':
        context.user_data['modo_registro'] = 'instalacao'
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
            'Digite o *número da SA* ou *GPON*:\n\n'
            '💡 Exemplos:\n'
            '• SA: 12345678\n'
            '• GPON: ABCD1234',
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
        await query.edit_message_text(msg, parse_mode='Markdown')
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
        msg = gerar_ranking_texto(insts)
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None
        
    elif query.data == 'voltar':
        username = query.from_user.username or query.from_user.first_name
        await exibir_menu_principal(update, context, username)
        return None

    return None

async def receber_sa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sa = update.message.text.strip()
    context.user_data['sa'] = sa
    await update.message.reply_text(
        f'✅ *SA Registrada!*\n📋 SA: `{sa}`\n\n'
        f'📝 [Etapa 2/5]\nAgora digite o *GPON*:\n💡 Exemplo: ABCD1234',
        parse_mode='Markdown'
    )
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
        prompt = '✅ *GPON Registrado!*\n📝 [Etapa 3/5]\nSelecione o *tipo de reparo*:'
    else:
        keyboard = [
            [InlineKeyboardButton('Instalação', callback_data='instalacao')],
            [InlineKeyboardButton('Instalação TV', callback_data='instalacao_tv')],
            [InlineKeyboardButton('Instalação + Mesh', callback_data='instalacao_mesh')],
            [InlineKeyboardButton('Mudança de Endereço', callback_data='mudanca_endereco')],
            [InlineKeyboardButton('Serviços', callback_data='servicos')]
        ]
        prompt = '✅ *GPON Registrado!*\n📝 [Etapa 3/5]\nSelecione o *tipo de serviço*:'
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(prompt, reply_markup=reply_markup, parse_mode='Markdown')
    return AGUARDANDO_TIPO

async def receber_tipo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tipo = query.data
    context.user_data['tipo'] = tipo
    
    tipos_com_serial = ['instalacao', 'instalacao_tv', 'instalacao_mesh', 'mudanca_endereco', 'defeito_banda_larga', 'defeito_linha', 'defeito_tv']
    
    if tipo in tipos_com_serial:
        await query.edit_message_text(
            '✅ *Tipo Selecionado!*\n📝 [Etapa 4/5]\nAgora envie o *Número de Série do Modem*:\n💡 Exemplo: ZTEGC8...',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SERIAL
    else:
        await query.edit_message_text(
            '✅ *Tipo Selecionado!*\n📝 [Etapa 5/5]\nAgora envie as *3 fotos* da instalação.\n💡 Tire fotos claras.\nQuando terminar, digite /finalizar',
            parse_mode='Markdown'
        )
        return AGUARDANDO_FOTOS

async def receber_serial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    serial = update.message.text.strip()
    context.user_data['serial_modem'] = serial
    
    if context.user_data.get('tipo') == 'instalacao_mesh':
        await update.message.reply_text(
            '✅ *Serial Modem Registrado!*\n📝 [Etapa 5/6]\nAgora envie o *Serial do Roteador Mesh*:',
            parse_mode='Markdown'
        )
        return AGUARDANDO_SERIAL_MESH
    
    await update.message.reply_text(
        '✅ *Serial Registrado!*\n📝 [Etapa 5/5]\nAgora envie as *3 fotos* da instalação.\nQuando terminar, digite /finalizar',
        parse_mode='Markdown'
    )
    return AGUARDANDO_FOTOS

async def receber_serial_mesh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    serial_mesh = update.message.text.strip()
    context.user_data['serial_mesh'] = serial_mesh
    await update.message.reply_text(
        '✅ *Serial Mesh Registrado!*\n📝 [Etapa 6/6]\nAgora envie as *3 fotos* da instalação.\nQuando terminar, digite /finalizar',
        parse_mode='Markdown'
    )
    return AGUARDANDO_FOTOS

async def receber_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'fotos' not in context.user_data:
        context.user_data['fotos'] = []
    
    photo = update.message.photo[-1]
    context.user_data['fotos'].append(photo.file_id)
    
    num_fotos = len(context.user_data['fotos'])
    
    if num_fotos < 3:
        await update.message.reply_text(
            f'✅ *Foto {num_fotos}/3 Recebida!*\nEnvie mais {3 - num_fotos} foto(s).',
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f'✅ *{num_fotos} fotos recebidas!*\nDigite /finalizar para salvar.',
            parse_mode='Markdown'
        )
    return AGUARDANDO_FOTOS

async def finalizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'sa' not in context.user_data or 'gpon' not in context.user_data:
        await update.message.reply_text('❌ Erro: Dados incompletos. Use /start para recomeçar.')
        return ConversationHandler.END
    
    user_id = update.message.from_user.id
    user_data = await db.get_user(str(user_id))
    
    tecnico_nome = user_data.get('nome', '') + ' ' + user_data.get('sobrenome', '') if user_data else "Desconhecido"
    tecnico_regiao = user_data.get('regiao') if user_data else None
    
    nova_instalacao = {
        'sa': context.user_data['sa'],
        'gpon': context.user_data['gpon'],
        'tipo': context.user_data.get('tipo') or 'instalacao',
        'categoria': context.user_data.get('modo_registro') or 'instalacao',
        'fotos': context.user_data.get('fotos', []),
        'tecnico_id': user_id,
        'tecnico_nome': tecnico_nome.strip(),
        'tecnico_regiao': tecnico_regiao,
        'serial_modem': context.user_data.get('serial_modem'),
        'serial_mesh': context.user_data.get('serial_mesh'),
        'data': datetime.now(TZ).strftime('%d/%m/%Y %H:%M')
    }
    
    # Remover Nones
    nova_instalacao = {k: v for k, v in nova_instalacao.items() if v is not None}
    
    ok = await db.save_installation(nova_instalacao)
    
    if ok:
        await update.message.reply_text(
            f'✅ *Registro Salvo com Sucesso!*\n'
            f'SA: `{nova_instalacao["sa"]}`\n'
            f'Use /start para nova ação.',
            parse_mode='Markdown'
        )
        context.user_data.clear()
        return ConversationHandler.END
    else:
        # Não limpar user_data em caso de erro
        keyboard = [[InlineKeyboardButton("🔄 Tentar Novamente", callback_data='retry_save')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '❌ Erro ao salvar no banco de dados. Tente novamente.',
            reply_markup=reply_markup
        )
        return AGUARDANDO_FOTOS # Mantém no estado para retry

async def consultar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    termo = update.message.text.strip()
    insts = await db.get_installations({'termo_busca': termo}, limit=5)
    
    if not insts:
        await update.message.reply_text(f'❌ Nada encontrado para: `{termo}`', parse_mode='Markdown')
        return ConversationHandler.END
        
    for inst in insts:
        msg = (
            f'📋 *SA:* `{inst.get("sa")}`\n'
            f'🔌 *GPON:* `{inst.get("gpon")}`\n'
            f'🧩 *Tipo:* {escape_markdown(inst.get("tipo"))}\n'
            f'📅 *Data:* {escape_markdown(inst.get("data"))}\n'
        )
        await update.message.reply_text(msg, parse_mode='MarkdownV2')
        
    return ConversationHandler.END

async def comando_consultar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('🔎 Digite o SA ou GPON para buscar:')
    return AGUARDANDO_CONSULTA

async def comando_reparo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['modo_registro'] = 'reparo'
    await update.message.reply_text('🛠️ *Novo Reparo*\nEnvie o *número da SA:*', parse_mode='Markdown')
    return AGUARDANDO_SA

async def comando_producao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Atalho para produção
    user_id = update.message.from_user.id
    username = update.message.from_user.username or "User"
    inicio_dt, fim_dt = ciclo_atual()
    insts = await db.get_installations({'tecnico_id': user_id, 'data_inicio': inicio_dt, 'data_fim': fim_dt})
    msg = gerar_texto_producao(insts, inicio_dt, fim_dt, username)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def comando_mensal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /mensal - Relatório do mês atual"""
    from reports import gerar_relatorio_mensal
    insts = await db.get_installations(limit=5000)
    msg = gerar_relatorio_mensal(insts)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def comando_semanal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /semanal - Relatório da semana atual"""
    from reports import gerar_relatorio_semanal
    insts = await db.get_installations(limit=5000)
    msg = gerar_relatorio_semanal(insts)
    await update.message.reply_text(msg, parse_mode='Markdown')

async def comando_hoje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /hoje - Relatório de hoje"""
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

