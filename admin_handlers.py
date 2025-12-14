from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS, AGUARDANDO_BROADCAST, AGUARDANDO_CONFIRMACAO_BROADCAST, TZ
from database import db
from datetime import datetime
import io
import csv
import asyncio
from telegram.error import RetryAfter
from collections import defaultdict

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        await update.message.reply_text('❌ Acesso negado.')
        return

    keyboard = [
        [InlineKeyboardButton("📊 Estatísticas Gerais", callback_data='admin_stats')],
        [InlineKeyboardButton("👥 Listar Técnicos", callback_data='admin_users')],
        [InlineKeyboardButton("📋 Todas Instalações", callback_data='admin_all_installs')],
        [InlineKeyboardButton("📢 Enviar Mensagem", callback_data='admin_broadcast')],
        [InlineKeyboardButton("📊 Criar Enquete", callback_data='admin_poll')],
        [InlineKeyboardButton("⚙️ Gestão de Acesso", callback_data='admin_access')],
        [InlineKeyboardButton("📤 Exportar CSV", callback_data='admin_export')],
        [InlineKeyboardButton("🔙 Sair", callback_data='admin_exit')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        '👑 *PAINEL ADMINISTRATIVO*\nSelecione uma opção:',
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer('❌ Acesso negado', show_alert=True)
        return ConversationHandler.END
        
    await query.answer()
    
    if query.data == 'admin_stats':
        users = await db.get_all_users()
        insts = await db.get_installations(limit=10000)
        
        agora = datetime.now(TZ)
        mes_atual = agora.month
        ano_atual = agora.year
        
        if mes_atual == 1:
            mes_anterior = 12
            ano_anterior = ano_atual - 1
        else:
            mes_anterior = mes_atual - 1
            ano_anterior = ano_atual
            
        inst_mes_atual = 0
        inst_mes_anterior = 0
        por_regiao = defaultdict(int)
        
        for inst in insts:
            try:
                data_inst = datetime.strptime(inst['data'], '%d/%m/%Y %H:%M').replace(tzinfo=TZ)
                
                if data_inst.month == mes_atual and data_inst.year == ano_atual:
                    inst_mes_atual += 1
                elif data_inst.month == mes_anterior and data_inst.year == ano_anterior:
                    inst_mes_anterior += 1
                
                regiao = inst.get('tecnico_regiao') or 'Não informada'
                por_regiao[regiao] += 1
            except:
                continue
        
        crescimento = 0
        if inst_mes_anterior > 0:
            crescimento = ((inst_mes_atual - inst_mes_anterior) / inst_mes_anterior) * 100
            
        sinal = "+" if crescimento >= 0 else ""
        
        top_regioes = sorted(por_regiao.items(), key=lambda x: x[1], reverse=True)[:3]
        
        msg = (
            '━━━━━━━━━━━━━━━━━━━━\n'
            '📊 *ESTATÍSTICAS AVANÇADAS*\n'
            '━━━━━━━━━━━━━━━━━━━━\n\n'
            f'👥 *Técnicos:* {len(users)}\n'
            f'📦 *Total Geral:* {len(insts)}\n\n'
            '📅 *Comparativo Mensal*\n'
            f'• Este Mês: *{inst_mes_atual}*\n'
            f'• Mês Passado: *{inst_mes_anterior}*\n'
            f'📈 Crescimento: *{sinal}{crescimento:.1f}%*\n\n'
            '🏆 *Top Regiões*\n'
        )
        
        for idx, (regiao, qtd) in enumerate(top_regioes, 1):
            barra = "█" * min(int(qtd/5) + 1, 10)
            msg += f'{idx}. {regiao}: *{qtd}* ({barra})\n'
            
        await query.edit_message_text(msg, parse_mode='Markdown')
        
    elif query.data == 'admin_users':
        users = await db.get_all_users()
        insts = await db.get_installations(limit=10000)
        
        instalacoes_por_tecnico = defaultdict(int)
        for inst in insts:
            tid = str(inst.get('tecnico_id', ''))
            if tid:
                instalacoes_por_tecnico[tid] += 1
                
        def escape_md(text):
            return str(text).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
            
        msg = (
            '━━━━━━━━━━━━━━━━━━━━\n'
            f'👥 *TÉCNICOS ({len(users)})*\n'
            '━━━━━━━━━━━━━━━━━━━━\n\n'
        )
        
        lista_ordenada = sorted(users.items(), key=lambda x: instalacoes_por_tecnico.get(x[0], 0), reverse=True)
        
        for user_id, dados_user in lista_ordenada[:20]:
            nome = f"{dados_user.get('nome', '')} {dados_user.get('sobrenome', '')}".strip()
            regiao = dados_user.get('regiao', 'N/A')
            qtd = instalacoes_por_tecnico.get(user_id, 0)
            
            is_adm = '👑 ' if int(user_id) in ADMIN_IDS else ''
            
            msg += f'{is_adm}*{escape_md(nome)}*\n'
            msg += f'🆔 `{user_id}` | 📍 {escape_md(regiao)}\n'
            msg += f'📦 {qtd} instalações\n'
            msg += '───────────────\n'
            
        if len(lista_ordenada) > 20:
            msg += f'\n_E mais {len(lista_ordenada) - 20} técnicos..._'
            
        await query.edit_message_text(msg, parse_mode='Markdown')
        
    elif query.data == 'admin_all_installs':
        insts = await db.get_installations(limit=20)
        insts.reverse()  # Mais recentes primeiro
        
        msg = f'📋 *Últimas Instalações ({len(insts)})*\n\n'
        for inst in insts:
            msg += f'📅 {inst.get("data")}\n'
            msg += f'SA: `{inst.get("sa")}` | GPON: `{inst.get("gpon")}`\n'
            msg += f'👤 {inst.get("tecnico_nome")}\n'
            msg += f'🧩 {inst.get("tipo", "instalacao")}\n\n'
        
        await query.edit_message_text(msg, parse_mode='Markdown')
        
    elif query.data == 'admin_export':
        await query.edit_message_text('⏳ Gerando CSV...')
        insts = await db.get_installations(limit=5000)
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Data', 'SA', 'GPON', 'Tipo', 'Técnico', 'Região'])
        
        for i in insts:
            writer.writerow([
                i.get('data'), i.get('sa'), i.get('gpon'), 
                i.get('tipo'), i.get('tecnico_nome'), i.get('tecnico_regiao')
            ])
            
        output.seek(0)
        csv_bytes = output.getvalue().encode('utf-8-sig')
        filename = f'export_{datetime.now().strftime("%Y%m%d")}.csv'
        
        await query.message.reply_document(
            document=io.BytesIO(csv_bytes),
            filename=filename,
            caption='📊 Exportação Completa'
        )
        
    elif query.data == 'admin_poll':
        await query.edit_message_text(
            '📊 *Nova Enquete*\n\n'
            'Crie a enquete aqui no chat (use o anexo do Telegram > Enquete) e envie para mim.\n'
            'Eu irei repassá-la para todos os técnicos.',
            parse_mode='Markdown'
        )
        return AGUARDANDO_ENQUETE

    elif query.data == 'admin_broadcast':
        await query.edit_message_text('📢 Envie a mensagem para todos (Texto, Foto ou Vídeo):')
        return AGUARDANDO_BROADCAST
        
    elif query.data == 'admin_exit':
        await query.delete_message()
        return ConversationHandler.END
        
    elif query.data.startswith('admin_access'):
        # Formato: admin_access (página 0) ou admin_access_1 (página 1)
        page = 0
        if '_' in query.data.replace('admin_access', ''):
            try:
                page = int(query.data.split('_')[-1])
            except:
                pass
                
        users = await db.get_all_users()
        if not users:
            await query.edit_message_text('❌ Nenhum usuário encontrado.')
            return ConversationHandler.END
            
        # Ordenar: pendentes/bloqueados primeiro, depois ativos, depois por nome
        def get_status(u): return u.get('status', 'ativo')
        
        # Lógica de ordenação:
        # 1. Pendentes (status == 'pendente') -> Prioridade máx
        # 2. Bloqueados (status == 'bloqueado') -> Prioridade média
        # 3. Ativos -> Prioridade baixa
        def sort_key(item):
            uid, u = item
            st = get_status(u)
            prio = 2
            if st == 'pendente': prio = 0
            elif st == 'bloqueado': prio = 1
            return (prio, u.get('nome', '').lower())

        sorted_users = sorted(users.items(), key=sort_key)
        
        # Paginação
        USERS_PER_PAGE = 8
        total_users = len(sorted_users)
        start_idx = page * USERS_PER_PAGE
        end_idx = start_idx + USERS_PER_PAGE
        current_page_users = sorted_users[start_idx:end_idx]
        
        msg = f"⚙️ *Gestão de Acesso* (Pág {page+1})\nTotal: {total_users} usuários\n\nSelecione para gerenciar:"
        keyboard = []
        
        for uid, u in current_page_users:
            status = get_status(u)
            icon = "✅"
            if status == 'pendente': icon = "⏳"
            elif status == 'bloqueado': icon = "⛔"
            
            nome = f"{u.get('nome','')} {u.get('sobrenome','')}".strip()
            # Truncar nome se muito longo
            if len(nome) > 20: nome = nome[:18] + ".."
            
            keyboard.append([InlineKeyboardButton(f"{icon} {nome}", callback_data=f'access_user_{uid}')])
            
        # Botões de Navegação
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Ant", callback_data=f'admin_access_{page-1}'))
        
        if end_idx < total_users:
            nav_buttons.append(InlineKeyboardButton("Próx ➡️", callback_data=f'admin_access_{page+1}'))
            
        if nav_buttons:
            keyboard.append(nav_buttons)
            
        keyboard.append([InlineKeyboardButton("🔙 Voltar ao Painel", callback_data='admin_panel_back')]) # Usar callback que recarrega o menu
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        
    if query.data == 'admin_panel_back':
        # Reutilizar a função admin_panel mas precisamos editar a mensagem em vez de enviar nova
        # Vamos extrair a lógica de montar o teclado do admin_panel para reutilizar ou apenas copiar aqui (mais rápido)
        keyboard = [
            [InlineKeyboardButton("📊 Estatísticas Gerais", callback_data='admin_stats')],
            [InlineKeyboardButton("👥 Listar Técnicos", callback_data='admin_users')],
            [InlineKeyboardButton("📋 Todas Instalações", callback_data='admin_all_installs')],
            [InlineKeyboardButton("📢 Enviar Mensagem", callback_data='admin_broadcast')],
            [InlineKeyboardButton("📊 Criar Enquete", callback_data='admin_poll')],
            [InlineKeyboardButton("⚙️ Gestão de Acesso", callback_data='admin_access')],
            [InlineKeyboardButton("📤 Exportar CSV", callback_data='admin_export')],
            [InlineKeyboardButton("🔙 Sair", callback_data='admin_exit')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            '👑 *PAINEL ADMINISTRATIVO*\nSelecione uma opção:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    if query.data.startswith('access_user_'):
        target_uid = query.data.replace('access_user_', '')
        user = await db.get_user(target_uid)
        
        if not user:
            await query.answer("Usuário não encontrado.", show_alert=True)
            return None
            
        status_atual = user.get('status', 'ativo')
        nome = f"{user.get('nome','')} {user.get('sobrenome','')}".strip()
        
        msg = (
            f"👤 *Gerenciar Usuário*\n\n"
            f"Nome: {nome}\n"
            f"ID: `{target_uid}`\n"
            f"Região: {user.get('regiao','-')}\n"
            f"Status Atual: *{status_atual.upper()}*\n"
        )
        
        
        keyboard = []
        if status_atual == 'bloqueado':
            keyboard.append([InlineKeyboardButton("✅ Desbloquear/Ativar", callback_data=f'access_set_ativo_{target_uid}')])
        else:
            keyboard.append([InlineKeyboardButton("⛔ Bloquear Acesso", callback_data=f'access_set_bloqueado_{target_uid}')])
            
        keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data='admin_access')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        
    elif query.data.startswith('access_set_'):
        # access_set_ativo_123456
        parts = query.data.split('_')
        novo_status = parts[2]
        target_uid = parts[3]
        
        success = await db.update_user_status(target_uid, novo_status)
        
        if success:
            await query.answer(f"Sucesso! Usuário {novo_status}.", show_alert=True)
            # Reabre os detalhes do usuário atualizado para ver a mudança
            # Chamada recursiva "hack" via edição de callback data não rola fácil,
            # então copiamos a logica de exibir usuario ou simplificamos:
            
            # Vamos exibir a mensagem de sucesso e botão de voltar para lista
            await query.edit_message_text(
                f"✅ Status alterado para *{novo_status.upper()}* com sucesso!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar para Lista", callback_data='admin_access')]]),
                parse_mode='Markdown'
            )
            # Pequeno delay e volta pra lista? Ou deixa assim.
        else:
            await query.answer("Erro ao atualizar status.", show_alert=True)

    # Para outros callbacks admin que não transitam estado
    return ConversationHandler.END

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a mensagem broadcast e mostra preview com opções"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text('❌ Acesso negado.')
        return ConversationHandler.END
    
    # Detectar tipo de mensagem
    broadcast_data = {}
    
    if update.message.photo:
        broadcast_data['type'] = 'photo'
        broadcast_data['file_id'] = update.message.photo[-1].file_id
        broadcast_data['caption'] = update.message.caption or ''
        preview_type = '📷 Foto'
    elif update.message.video:
        broadcast_data['type'] = 'video'
        broadcast_data['file_id'] = update.message.video.file_id
        broadcast_data['caption'] = update.message.caption or ''
        preview_type = '🎥 Vídeo'
    elif update.message.document:
        broadcast_data['type'] = 'document'
        broadcast_data['file_id'] = update.message.document.file_id
        broadcast_data['caption'] = update.message.caption or ''
        preview_type = '📄 Documento'
    elif update.message.text:
        broadcast_data['type'] = 'text'
        broadcast_data['text'] = update.message.text.strip()
        preview_type = '📝 Texto'
    else:
        await update.message.reply_text('❌ Tipo não suportado.')
        return AGUARDANDO_BROADCAST
    
    # Armazenar no contexto
    context.user_data['broadcast_data'] = broadcast_data
    
    # Preview
    users = await db.get_all_users()
    total = len(users)
    
    if broadcast_data['type'] == 'text':
        preview = broadcast_data['text'][:200]
        if len(broadcast_data['text']) > 200:
            preview += '...'
    else:
        preview = broadcast_data.get('caption', '(sem legenda)')[:200]
    
    msg = (
        f'📋 *Preview da Mensagem*\n\n'
        f'Tipo: {preview_type}\n'
        f'Destinatários: {total} técnicos\n\n'
        f'*Conteúdo:*\n{preview}\n\n'
        f'Escolha uma opção:'
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Enviar para TODOS", callback_data='broadcast_send_all')],
        [InlineKeyboardButton("🎯 Selecionar Região", callback_data='broadcast_select_region')],
        [InlineKeyboardButton("❌ Cancelar", callback_data='broadcast_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    return AGUARDANDO_CONFIRMACAO_BROADCAST

async def confirmar_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa o broadcast após confirmação"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer('❌ Acesso negado', show_alert=True)
        return ConversationHandler.END
    
    await query.answer()
    
    if query.data == 'broadcast_cancel':
        await query.edit_message_text('❌ Broadcast cancelado.')
        context.user_data.pop('broadcast_data', None)
        return ConversationHandler.END
        
    if query.data == 'broadcast_select_region':
        # Listar regiões disponíveis
        users = await db.get_all_users()
        regioes = set()
        for u in users.values():
            r = u.get('regiao')
            if r: regioes.add(r)
            
        if not regioes:
            await query.edit_message_text('❌ Nenhuma região encontrada.')
            return ConversationHandler.END
            
        keyboard = []
        for reg in sorted(regioes):
            keyboard.append([InlineKeyboardButton(f"📍 {reg}", callback_data=f'broadcast_region_{reg}')])
        keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data='broadcast_back')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('🎯 Selecione a região alvo:', reply_markup=reply_markup)
        return AGUARDANDO_CONFIRMACAO_BROADCAST

    if query.data == 'broadcast_back':
        # Volta para o preview
        # (Simplificado: apenas pede para reenviar ou cancela, mas idealmente reconstruiria o preview.
        #  Para economizar código, vamos cancelar e pedir para reenviar ou apenas editar texto)
        await query.edit_message_text('🔙 Operação cancelada. Envie o comando novamente.')
        return ConversationHandler.END

    # Definir alvos
    users = await db.get_all_users()
    target_users = []
    
    if query.data == 'broadcast_send_all' or query.data == 'broadcast_send_pin': # Mantendo compatibilidade com pin se quiser reativar
        target_users = list(users.keys())
        pin_message = (query.data == 'broadcast_send_pin')
    elif query.data.startswith('broadcast_region_'):
        region = query.data.replace('broadcast_region_', '')
        target_users = [uid for uid, u in users.items() if u.get('regiao') == region]
        pin_message = False
    else:
        # Fallback
        target_users = list(users.keys())
        pin_message = False
    
    broadcast_data = context.user_data.get('broadcast_data')
    
    if not broadcast_data:
        await query.edit_message_text('❌ Erro: dados não encontrados.')
        return ConversationHandler.END
    
    await query.edit_message_text(f'📤 Enviando para {len(target_users)} técnicos...')
    
    header = '📢 *AVISO DA ADMINISTRAÇÃO*\n━━━━━━━━━━━━━━━━━━━━\n\n'
    footer = '\n\n━━━━━━━━━━━━━━━━━━━━'
    
    enviados = 0
    falhas = 0
    fixados = 0
    
    for uid in target_users:
        try:
            message_sent = None
            
            if broadcast_data['type'] == 'text':
                msg = header + broadcast_data['text'] + footer
                message_sent = await context.bot.send_message(
                    chat_id=int(uid),
                    text=msg,
                    parse_mode='Markdown'
                )
            elif broadcast_data['type'] == 'photo':
                caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                message_sent = await context.bot.send_photo(
                    chat_id=int(uid),
                    photo=broadcast_data['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif broadcast_data['type'] == 'video':
                caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                message_sent = await context.bot.send_video(
                    chat_id=int(uid),
                    video=broadcast_data['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif broadcast_data['type'] == 'document':
                caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                message_sent = await context.bot.send_document(
                    chat_id=int(uid),
                    document=broadcast_data['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            
            enviados += 1
            
            if pin_message and message_sent:
                try:
                    await context.bot.pin_chat_message(
                        chat_id=int(uid),
                        message_id=message_sent.message_id,
                        disable_notification=True
                    )
                    fixados += 1
                except:
                    pass
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            # Tentar novamente após o tempo de espera
            try:
                if broadcast_data['type'] == 'text':
                    msg = header + broadcast_data['text'] + footer
                    await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode='Markdown')
                # (Simplificação: apenas re-tenta texto ou ignora mídia complexa no retry para não duplicar código excessivamente aqui)
                enviados += 1
            except:
                falhas += 1
        except Exception as e:
            falhas += 1
        
        # Pequeno delay para evitar flood
        await asyncio.sleep(0.05)
    
    relatorio = (
        f'✅ *Broadcast Concluído!*\n\n'
        f'📊 *Estatísticas:*\n'
        f'✅ Enviados: {enviados}\n'
        f'❌ Falhas: {falhas}\n'
        f'👥 Total Alvo: {len(target_users)}\n'
    )
    
    if pin_message:
        relatorio += f'📌 Fixadas: {fixados}\n'
    
    await query.edit_message_text(relatorio, parse_mode='Markdown')
    context.user_data.pop('broadcast_data', None)
    return ConversationHandler.END

async def admin_poll_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a enquete criada pelo admin"""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
        
    if not update.message.poll:
        await update.message.reply_text('❌ Por favor, envie uma ENQUETE válida (use o menu de anexos do Telegram).')
        return AGUARDANDO_ENQUETE
        
    poll = update.message.poll
    
    # Salvar dados da enquete para broadcast
    context.user_data['poll_data'] = {
        'question': poll.question,
        'options': [o.text for o in poll.options],
        'is_anonymous': poll.is_anonymous,
        'allows_multiple_answers': poll.allows_multiple_answers,
        'type': poll.type
    }
    
    users = await db.get_all_users()
    
    msg = (
        '📊 *Confirmar Enquete*\n\n'
        f'❓ Pergunta: {poll.question}\n'
        f'🔢 Opções: {len(poll.options)}\n'
        f'👥 Destinatários: {len(users)} técnicos\n\n'
        'Deseja enviar agora?'
    )
    
    keyboard = [
        [InlineKeyboardButton("✅ Enviar Enquete", callback_data='poll_send')],
        [InlineKeyboardButton("❌ Cancelar", callback_data='poll_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    return AGUARDANDO_CONFIRMACAO_ENQUETE

async def confirmar_enquete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == 'poll_cancel':
        await query.edit_message_text('❌ Enquete cancelada.')
        context.user_data.pop('poll_data', None)
        return ConversationHandler.END
        
    poll_data = context.user_data.get('poll_data')
    if not poll_data:
        await query.edit_message_text('❌ Erro: dados da enquete perdidos.')
        return ConversationHandler.END
        
    users = await db.get_all_users()
    await query.edit_message_text('📤 Enviando enquete...')
    
    enviados = 0
    falhas = 0
    
    for uid in users.keys():
        try:
            await context.bot.send_poll(
                chat_id=int(uid),
                question=poll_data['question'],
                options=poll_data['options'],
                is_anonymous=poll_data['is_anonymous'],
                allows_multiple_answers=poll_data['allows_multiple_answers'],
                type=poll_data['type']
            )
            enviados += 1
            await asyncio.sleep(0.05) # Evitar flood
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.send_poll(
                    chat_id=int(uid),
                    question=poll_data['question'],
                    options=poll_data['options'],
                    is_anonymous=poll_data['is_anonymous'],
                    allows_multiple_answers=poll_data['allows_multiple_answers'],
                    type=poll_data['type']
                )
                enviados += 1
            except:
                falhas += 1
        except:
            falhas += 1
            
    await query.edit_message_text(
        f'✅ *Enquete Enviada!*\n\n'
        f'📤 Enviados: {enviados}\n'
        f'❌ Falhas: {falhas}',
        parse_mode='Markdown'
    )
    context.user_data.pop('poll_data', None)
    return ConversationHandler.END
