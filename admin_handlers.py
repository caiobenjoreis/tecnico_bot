from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS, AGUARDANDO_BROADCAST, AGUARDANDO_CONFIRMACAO_BROADCAST, AGUARDANDO_BUSCA_USER, AGUARDANDO_ENQUETE, AGUARDANDO_CONFIRMACAO_ENQUETE, TZ
from database import db
from datetime import datetime
import io
import csv
import asyncio
from telegram.error import RetryAfter
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def render_access_panel(context, page=0, filter_type='all', search_mode='none'):
    """Helper para renderizar o painel de gestão de acesso"""
    users = await db.get_all_users()
    if not users:
        return "❌ Nenhum usuário encontrado.", None
        
    # --- FILTRAGEM ---
    filtered_items = []
    search_query = context.user_data.get('search_query', '').lower() if search_mode == 'active' else ''
    
    for uid, u in users.items():
        status = u.get('status', 'ativo')
        nome = str(u.get('nome', '')).lower()
        sobrenome = str(u.get('sobrenome', '')).lower()
        full_str = f"{nome} {sobrenome} {uid}"
        
        # Filtro por Tab
        if filter_type == 'pending' and status != 'pendente': continue
        if filter_type == 'blocked' and status != 'bloqueado': continue
        
        # Filtro por Busca
        if search_mode == 'active' and search_query:
            if search_query not in full_str: continue
            
        filtered_items.append((uid, u))
        
    # Ordenação
    def sort_key(item):
        uid, u = item
        st = u.get('status', 'ativo')
        prio = 2
        if st == 'pendente': prio = 0
        elif st == 'bloqueado': prio = 1
        return (prio, u.get('nome', '').lower())

    sorted_users = sorted(filtered_items, key=sort_key)
    
    # Paginação
    USERS_PER_PAGE = 8
    total_users = len(sorted_users)
    
    # Ajustar paginação se exceder
    if page * USERS_PER_PAGE >= total_users and page > 0:
        page = 0
        
    start_idx = page * USERS_PER_PAGE
    end_idx = start_idx + USERS_PER_PAGE
    current_page_users = sorted_users[start_idx:end_idx]
    
    subtitle = "Todos os Usuários"
    if filter_type == 'pending': subtitle = "⏳ Pendentes"
    elif filter_type == 'blocked': subtitle = "⛔ Bloqueados"
    
    if search_mode == 'active':
        subtitle = f"🔍 Busca: '{context.user_data.get('search_query')}'"
    
    msg = f"⚙️ *Gestão de Acesso*\n📂 {subtitle}\nTotal: {total_users}\n\n"
    keyboard = []
    
    # --- ABAS DE FILTRO ---
    if search_mode != 'active':
        tabs = []
        # Botão Todos
        txt = "📂 Todos" if filter_type == 'all' else "Todos"
        tabs.append(InlineKeyboardButton(txt, callback_data='admin_access_0_all_none'))
        
        # Botão Pendentes
        txt = "⏳ Pend" if filter_type == 'pending' else "Pend"
        tabs.append(InlineKeyboardButton(txt, callback_data='admin_access_0_pending_none'))
        
        # Botão Bloqueados
        txt = "⛔ Block" if filter_type == 'blocked' else "Block"
        tabs.append(InlineKeyboardButton(txt, callback_data='admin_access_0_blocked_none'))
        
        keyboard.append(tabs)
        
        # Botão Buscar
        keyboard.append([InlineKeyboardButton("🔍 Buscar Usuário", callback_data='admin_access_search_start')])
    else:
        keyboard.append([InlineKeyboardButton("❌ Limpar Busca", callback_data='admin_access_search_clear')])
    
    # Lista de Usuários
    if not current_page_users:
        msg += "_Nenhum usuário encontrado com este filtro._"
    else:
        msg += "Selecione para alterar:"
        for uid, u in current_page_users:
            status = u.get('status', 'ativo')
            icon = "✅"
            if status == 'pendente': icon = "⏳"
            elif status == 'bloqueado': icon = "⛔"
            
            nome = f"{u.get('nome','')} {u.get('sobrenome','')}".strip()
            if len(nome) > 18: nome = nome[:16] + ".."
            
            # Callback inclui o estado atual para o retorno ser consistente
            cb_data = f'access_user_{uid}_{page}_{filter_type}_{search_mode}'
            keyboard.append([InlineKeyboardButton(f"{icon} {nome}", callback_data=cb_data)])
        
    # Botões de Navegação
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Ant", callback_data=f'admin_access_{page-1}_{filter_type}_{search_mode}'))
    
    if end_idx < total_users:
        nav_buttons.append(InlineKeyboardButton("Próx ➡️", callback_data=f'admin_access_{page+1}_{filter_type}_{search_mode}'))
        
    if nav_buttons:
        keyboard.append(nav_buttons)
        
    keyboard.append([InlineKeyboardButton("🔙 Voltar ao Painel", callback_data='admin_panel_back')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    return msg, reply_markup

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
    
    # Processar access_user_ ANTES de chamar answer() para poder mostrar toast
    if query.data.startswith('access_user_'):
        try:
            parts = query.data.split('_')
            # access_user_{uid}_{page}_{filter}_{search_mode}
            
            target_uid = parts[2]
            current_page = 0
            current_filter = 'all'
            current_search = 'none'
            
            if len(parts) >= 4: 
                try: current_page = int(parts[3])
                except: current_page = 0
            if len(parts) >= 5: current_filter = parts[4]
            if len(parts) >= 6: current_search = parts[5]

            user = await db.get_user(target_uid)
            if user:
                current_status = user.get('status', 'ativo')
                new_status = 'bloqueado'
                
                if current_status == 'bloqueado':
                    new_status = 'ativo'
                elif current_status == 'pendente':
                    new_status = 'ativo' # Aprovar
                
                success = await db.update_user_status(target_uid, new_status)
                
                if success:
                    status_text = "✅ ATIVADO" if new_status == 'ativo' else "🔒 BLOQUEADO"
                    await query.answer(f"Usuário {status_text}!", show_alert=False)
                else:
                    await query.answer("❌ Erro ao atualizar status", show_alert=True)
            else:
                await query.answer("❌ Usuário não encontrado", show_alert=True)
            
            # --- RE-RENDERIZAR (Sem recursão) ---
            msg, reply_markup = await render_access_panel(context, current_page, current_filter, current_search)
            
            try:
                await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Erro ao editar mensagem da lista: {e}")
                
        except Exception as e:
            logger.error(f"ERRO em access_user: {e}", exc_info=True)
            try: await query.answer(f"Erro: {e}", show_alert=True)
            except: pass
            
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
        # Formato: admin_access_{page}_{filter}_{search_mode}
        
        parts = query.data.split('_')
        page = 0
        filter_type = 'all'
        search_mode = 'none'
        
        if len(parts) >= 3:
            try: page = int(parts[2])
            except: page = 0
        if len(parts) >= 4:
            filter_type = parts[3]
        if len(parts) >= 5:
            search_mode = parts[4]
            
        # Se usuário pediu para buscar
        if query.data == 'admin_access_search_start':
            await query.edit_message_text(
                '🔍 *Consultar Usuário*\n\n'
                'Digite o *Nome* ou *ID* do técnico que deseja buscar:\n'
                '_(Digite /cancelar para voltar)_',
                parse_mode='Markdown'
            )
            return AGUARDANDO_BUSCA_USER
        
        # Se clicou em "Limpar Busca"
        if query.data == 'admin_access_search_clear':
            context.user_data.pop('search_query', None)
            search_mode = 'none'
            page = 0
            
        # Renderizar painel
        msg, reply_markup = await render_access_panel(context, page, filter_type, search_mode)
        
        try:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        except Exception:
             # Ignora erro se msg for igual
             pass
        
    elif query.data == 'admin_panel_back':
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

    elif query.data.startswith('access_set_'):
        # Formato: access_set_{status}_{user_id}
        try:
            parts = query.data.split('_')
            if len(parts) >= 4:
                new_status = parts[2]  # 'ativo' ou 'bloqueado'
                target_uid = parts[3]
                
                success = await db.update_user_status(target_uid, new_status)
                
                if success:
                    user = await db.get_user(target_uid)
                    nome_completo = "Usuário"
                    if user:
                        nome_completo = f"{user.get('nome', '')} {user.get('sobrenome', '')}".strip()
                    
                    status_emoji = "✅" if new_status == 'ativo' else "⛔"
                    status_text = "APROVADO" if new_status == 'ativo' else "BLOQUEADO"
                    
                    await query.answer(f"{status_emoji} {nome_completo} {status_text}!", show_alert=True)
                    
                    # Atualizar a mensagem removendo os botões
                    try:
                        await query.edit_message_text(
                            query.message.text + f"\n\n{status_emoji} *{status_text}*",
                            parse_mode='Markdown'
                        )
                    except:
                        pass
                    
                    # Notificar o usuário
                    try:
                        if new_status == 'ativo':
                            await context.bot.send_message(
                                chat_id=int(target_uid),
                                text=(
                                    '✅ *Cadastro Aprovado!*\n\n'
                                    'Seu acesso foi liberado!\n'
                                    'Use /start para começar a usar o bot.'
                                ),
                                parse_mode='Markdown'
                            )
                        else:
                            await context.bot.send_message(
                                chat_id=int(target_uid),
                                text=(
                                    '⛔ *Cadastro Recusado*\n\n'
                                    'Seu cadastro não foi aprovado.\n'
                                    'Entre em contato com o administrador para mais informações.'
                                ),
                                parse_mode='Markdown'
                            )
                    except Exception as e:
                        logger.error(f"Erro ao notificar usuário {target_uid}: {e}")
                else:
                    await query.answer("❌ Erro ao atualizar status", show_alert=True)
            else:
                await query.answer("❌ Formato de callback inválido", show_alert=True)
        except Exception as e:
            logger.error(f"Erro em access_set_: {e}", exc_info=True)
            await query.answer(f"❌ Erro: {e}", show_alert=True)
        
        return ConversationHandler.END

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
    
async def admin_access_search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe o termo de busca do admin e exibe a lista filtrada"""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        return ConversationHandler.END
        
    query_text = update.message.text.strip()
    
    if query_text in ['/cancelar', '/start', 'cancelar']:
        await update.message.reply_text('❌ Busca cancelada.')
        return ConversationHandler.END
        
    # Salvar termo de busca
    context.user_data['search_query'] = query_text
    
    # Renderizar painel com busca ativa
    msg, reply_markup = await render_access_panel(context, 0, 'all', 'active')
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    
    return ConversationHandler.END
