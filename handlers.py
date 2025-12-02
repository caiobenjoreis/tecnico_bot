from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import *
from database import db
from datetime import datetime
from reports import gerar_texto_producao, gerar_ranking_texto
from utils import ciclo_atual, escape_markdown, extrair_campos_por_imagem, extrair_campos_por_imagens, extrair_campo_especifico, is_valid_serial
import io
import os
import logging

logger = logging.getLogger(__name__)

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
        
        for inst in insts_sorted:
            tipo = inst.get('tipo', 'Instalação')
            from config import PONTOS_SERVICO
            pontos = PONTOS_SERVICO.get(tipo.lower(), 0)
            msg += f"📅 {inst['data']} | {pontos} pts\n"
            msg += f"🔧 {tipo} | SA: {inst['sa']}\n"
            msg += f"──────────────────\n"
        
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
        msg = gerar_ranking_texto(insts)
        await query.edit_message_text(msg, parse_mode='Markdown')
        return None
        
    # Callbacks do painel admin
    elif query.data.startswith('admin_'):
        from admin_handlers import admin_callback_handler
        return await admin_callback_handler(update, context)
        
    elif query.data.startswith('broadcast_'):
        from admin_handlers import confirmar_broadcast
        # Este handler é chamado via CallbackQueryHandler específico no main, mas se cair aqui...
        pass

    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name
    
    # Verificar se usuário existe
    db_user = await db.get_user(str(user_id))
    
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

async def exibir_menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE, username: str):
    keyboard = [
        [InlineKeyboardButton("📝 Nova Instalação", callback_data='registrar')],
        [InlineKeyboardButton("🛠️ Novo Reparo", callback_data='registrar_reparo')],
        [InlineKeyboardButton("🔎 Consultar SA/GPON", callback_data='consultar')],
        [InlineKeyboardButton("📂 Minhas Instalações", callback_data='minhas')],
        [InlineKeyboardButton("📊 Produção do Ciclo", callback_data='consulta_producao')],
        [InlineKeyboardButton("📈 Relatórios", callback_data='relatorios')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        '🤖 *Bot Técnico*\n'
        f'👤 {username}\n\n'
        '📡 Seu assistente de campo.\n'
        '🏆 Qualidade e agilidade. Bora bater meta hoje! 🚀'
    )
    
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

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
        'username': username
    }
    
    await db.save_user(novo_usuario)
    await update.message.reply_text('✅ Cadastro realizado com sucesso!')
    await exibir_menu_principal(update, context, username)
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
    context.user_data.clear()
    await update.message.reply_text('❌ Operação cancelada. Use /start para voltar ao menu.')
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
    if not data.get('mesh'):
        d_mesh = await extrair_campo_especifico(imgs, 'mesh')
        if d_mesh.get('mesh'):
            data['mesh'] = d_mesh['mesh']
    sa = data.get('sa')
    gpon = data.get('gpon')
    serial_modem = data.get('serial_do_modem')
    mesh_list = [m for m in (data.get('mesh') or []) if is_valid_serial(m)]
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
    mesh_text = ', '.join(mesh_list) if mesh_list else 'não informado'
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
        keyboard = [
            [InlineKeyboardButton('Instalação', callback_data='instalacao')],
            [InlineKeyboardButton('Instalação TV', callback_data='instalacao_tv')],
            [InlineKeyboardButton('Instalação + Mesh', callback_data='instalacao_mesh')],
            [InlineKeyboardButton('Mudança de Endereço', callback_data='mudanca_endereco')],
            [InlineKeyboardButton('Serviços', callback_data='servicos')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Selecione o *tipo de serviço*:', reply_markup=reply_markup, parse_mode='Markdown')
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
    
    tipos_com_serial = ['instalacao', 'instalacao_tv', 'instalacao_mesh', 'mudanca_endereco', 'defeito_banda_larga', 'defeito_linha', 'defeito_tv']
    
    if tipo in tipos_com_serial:
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
    d = await extrair_campo_especifico(imgs, 'mesh')
    mesh_list = [m for m in (d.get('mesh') or []) if is_valid_serial(m)]
    if not mesh_list:
        await update.message.reply_text('❌ Não consegui extrair o serial mesh. Digite o serial do roteador.')
        return AGUARDANDO_SERIAL_MESH
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
    
    nova_instalacao = {
        'sa': context.user_data['sa'],
        'gpon': context.user_data['gpon'],
        'tipo': context.user_data.get('tipo') or 'instalacao',
        'categoria': context.user_data.get('modo_registro') or 'instalacao',
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
        titulo = '✅ *REPARO REGISTRADO*' if nova_instalacao['categoria'] == 'reparo' else '✅ *INSTALAÇÃO REGISTRADA*'
        msg_parts = [
            '━━━━━━━━━━━━━━━━━━━━\n',
            f'{titulo}\n',
            '━━━━━━━━━━━━━━━━━━━━\n\n',
            '📋 *Detalhes:*\n',
            f'🔖 SA: `{nova_instalacao["sa"]}`\n',
            f'🔗 GPON: `{nova_instalacao["gpon"]}`\n'
        ]
    
        if nova_instalacao.get("serial_modem"):
            msg_parts.append(f'📟 Serial Modem: `{nova_instalacao["serial_modem"]}`\n')
            
        if nova_instalacao.get("serial_mesh"):
            msg_parts.append(f'📶 Serial Mesh: `{nova_instalacao["serial_mesh"]}`\n')
    
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
            f'{registro_msg}\n\n',
            '🔁 Use /start para nova ação\\.'
        ])
        await update.message.reply_text(''.join(msg_parts), parse_mode='MarkdownV2')
    else:
        keyboard = [[InlineKeyboardButton("🔄 Tentar Novamente", callback_data='retry_save')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            '❌ Erro ao salvar no banco de dados. Tente novamente.',
            reply_markup=reply_markup
        )
        return AGUARDANDO_FOTOS # Mantém no estado para retry
    
    context.user_data.clear()
    return ConversationHandler.END

async def consultar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto_busca = update.message.text.strip()
    
    # Buscar TODAS as instalações (como no original)
    insts = await db.get_installations(limit=5000)
    
    # Busca em memória (substring match)
    termo = texto_busca.lower()
    resultados = []
    for d in insts:
        sa = str(d.get('sa') or '').lower()
        gpon = str(d.get('gpon') or '').lower()
        if termo in sa or termo in gpon:
            resultados.append(d)
    
    if not resultados:
        await update.message.reply_text(
            f'❌ Nenhuma instalação encontrada para: `{texto_busca}`',
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    for resultado in resultados:
        # Escapar caracteres especiais para MarkdownV2
        def escape_md(text):
            if text is None:
                return 'N/A'
            special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
            text = str(text)
            for char in special_chars:
                text = text.replace(char, f'\\{char}')
            return text
        
        msg_parts = [
            f'📋 *SA:* `{resultado["sa"]}`\n',
            f'🔗 *GPON:* `{resultado["gpon"]}`\n'
        ]
        
        if resultado.get("serial_modem"):
            msg_parts.append(f'📟 *Serial:* `{resultado["serial_modem"]}`\n')
        
        msg_parts.extend([
            f'🧩 *Tipo:* {escape_md(resultado.get("tipo", "instalacao"))}\n',
            f'👤 *Técnico:* {escape_md(resultado["tecnico_nome"])}\n',
            f'📅 *Data:* {escape_md(resultado["data"])}\n',
            f'📸 *Fotos:* {len(resultado.get("fotos", []))}'
        ])
        
        msg = ''.join(msg_parts)
        await update.message.reply_text(msg, parse_mode='MarkdownV2')
        
        # Enviar as fotos (COMO NO ORIGINAL)
        for foto_id in resultado.get('fotos', []):
            try:
                await update.message.reply_photo(photo=foto_id)
            except:
                pass
                
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
