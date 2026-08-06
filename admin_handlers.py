from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS, AGUARDANDO_BROADCAST, AGUARDANDO_CONFIRMACAO_BROADCAST, AGUARDANDO_BUSCA_USER, AGUARDANDO_ENQUETE, AGUARDANDO_CONFIRMACAO_ENQUETE, AGUARDANDO_ID_TECNICO_AJUSTE, AGUARDANDO_DATA_AJUSTE, TZ
from database import db
from utils import parse_data, format_data
from datetime import datetime
import io
import csv
import asyncio
from asyncio import Semaphore
import time
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
            
            # Callback com formato mais curto para não exceder 64 bytes
            # Formato: au_{uid}_{page}_{filter_inicial}_{search_inicial}
            filter_short = filter_type[0] if filter_type else 'a'  # a=all, p=pending, b=blocked
            search_short = 's' if search_mode == 'active' else 'n'  # s=search, n=none
            cb_data = f'au_{uid}_{page}_{filter_short}_{search_short}'
            
            # LOG: Verificar tamanho do callback
            if len(cb_data) > 64:
                logger.warning(f"Callback muito longo ({len(cb_data)} bytes): {cb_data}")
                cb_data = cb_data[:64]  # Truncar se necessário
            
            logger.info(f"Criando botão para {nome}: {cb_data} ({len(cb_data)} bytes)")
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
        [InlineKeyboardButton("🛠️ Ajuste Manual (Dias)", callback_data='admin_fix_days')],
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
    
    # LOG DE DEBUG - Ver todos os callbacks recebidos
    logger.info(f"[ADMIN CALLBACK] Recebido: {query.data} de user {user_id}")
    
    if not is_admin(user_id):
        await query.answer('❌ Acesso negado', show_alert=True)
        return ConversationHandler.END
    
    # Processar au_ (access_user) ANTES de chamar answer() para poder mostrar toast
    # Formato curto: au_{uid}_{page}_{filter_short}_{search_short}
    if query.data.startswith('au_'):
        logger.info(f"[ACCESS_USER] Processando callback: {query.data}")
        try:
            parts = query.data.split('_')
            # au_{uid}_{page}_{filter_short}_{search_short}
            
            target_uid = parts[1]
            current_page = 0
            current_filter = 'all'
            current_search = 'none'
            
            if len(parts) >= 3: 
                try: current_page = int(parts[2])
                except: current_page = 0
            
            # Converter códigos curtos de volta
            if len(parts) >= 4:
                filter_short = parts[3]
                if filter_short == 'p': current_filter = 'pending'
                elif filter_short == 'b': current_filter = 'blocked'
                else: current_filter = 'all'
            
            if len(parts) >= 5:
                search_short = parts[4]
                current_search = 'active' if search_short == 's' else 'none'

            logger.info(f"Admin {user_id} alterando status do usuário {target_uid}")

            user = await db.get_user(target_uid)
            if user:
                current_status = user.get('status', 'ativo')
                new_status = 'bloqueado'
                
                if current_status == 'bloqueado':
                    new_status = 'ativo'
                elif current_status == 'pendente':
                    new_status = 'ativo' # Aprovar
                
                logger.info(f"Mudando status de {current_status} para {new_status}")
                
                success = await db.update_user_status(target_uid, new_status)
                
                if success:
                    status_text = "✅ ATIVADO" if new_status == 'ativo' else "🔒 BLOQUEADO"
                    logger.info(f"Status atualizado com sucesso: {status_text}")
                    await query.answer(f"Usuário {status_text}!", show_alert=False)
                else:
                    logger.error(f"Falha ao atualizar status do usuário {target_uid}")
                    await query.answer("❌ Erro ao atualizar status", show_alert=True)
            else:
                logger.error(f"Usuário {target_uid} não encontrado no banco")
                await query.answer("❌ Usuário não encontrado", show_alert=True)
            
            # --- RE-RENDERIZAR (Sem recursão) ---
            msg, reply_markup = await render_access_panel(context, current_page, current_filter, current_search)
            
            try:
                await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Erro ao editar mensagem da lista: {e}")
                
        except Exception as e:
            logger.error(f"ERRO em au_: {e}", exc_info=True)
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
            data_inst = parse_data(inst.get('data', ''))
            if data_inst is None:
                continue
            if data_inst.month == mes_atual and data_inst.year == ano_atual:
                inst_mes_atual += 1
            elif data_inst.month == mes_anterior and data_inst.year == ano_anterior:
                inst_mes_anterior += 1
            regiao = inst.get('tecnico_regiao') or 'Não informada'
            por_regiao[regiao] += 1
        
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

    elif query.data == 'admin_fix_days':
        await query.edit_message_text(
            '🛠️ *Ajuste Manual de Dias*\n\n'
            'Isso insere uma instalação administrativa em uma data específica para ajustar a contagem de dias trabalhados.\n\n'
            'Digite o *ID do Técnico* que deseja ajustar:\n'
            '_(Use /cancelar para sair)_',
            parse_mode='Markdown'
        )
        return AGUARDANDO_ID_TECNICO_AJUSTE
        
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
                # Juntar todas as partes restantes para formar o user_id completo
                # Isso garante que user_ids com múltiplos dígitos funcionem
                target_uid = '_'.join(parts[3:])
                
                logger.info(f"Tentando atualizar usuário {target_uid} para status {new_status}")
                
                success = await db.update_user_status(target_uid, new_status)
                
                if success:
                    user = await db.get_user(target_uid)
                    nome_completo = "Usuário"
                    if user:
                        nome_completo = f"{user.get('nome', '')} {user.get('sobrenome', '')}".strip()
                    
                    status_emoji = "✅" if new_status == 'ativo' else "⛔"
                    status_text = "APROVADO" if new_status == 'ativo' else "BLOQUEADO"
                    
                    logger.info(f"Usuário {target_uid} atualizado para {new_status} com sucesso")
                    
                    await query.answer(f"{status_emoji} {nome_completo} {status_text}!", show_alert=True)
                    
                    # Atualizar a mensagem removendo os botões
                    try:
                        await query.edit_message_text(
                            query.message.text + f"\n\n{status_emoji} *{status_text}*",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Erro ao editar mensagem: {e}")
                    
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
                            logger.info(f"Notificação de aprovação enviada para {target_uid}")
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
                            logger.info(f"Notificação de bloqueio enviada para {target_uid}")
                    except Exception as e:
                        logger.error(f"Erro ao notificar usuário {target_uid}: {e}")
                else:
                    logger.error(f"Falha ao atualizar status do usuário {target_uid}")
                    await query.answer("❌ Erro ao atualizar status", show_alert=True)
            else:
                logger.error(f"Formato de callback inválido: {query.data}")
                await query.answer("❌ Formato de callback inválido", show_alert=True)
        except Exception as e:
            logger.error(f"Erro em access_set_: {e}", exc_info=True)
            await query.answer(f"❌ Erro: {e}", show_alert=True)
        
        return ConversationHandler.END

    # Para outros callbacks admin que não transitam estado
    return ConversationHandler.END

async def admin_broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recebe a mensagem broadcast e mostra preview com opções avançadas"""
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
    elif update.message.audio:
        broadcast_data['type'] = 'audio'
        broadcast_data['file_id'] = update.message.audio.file_id
        broadcast_data['caption'] = update.message.caption or ''
        preview_type = '🎵 Áudio'
    elif update.message.voice:
        broadcast_data['type'] = 'voice'
        broadcast_data['file_id'] = update.message.voice.file_id
        broadcast_data['caption'] = update.message.caption or ''
        preview_type = '🎤 Áudio de Voz'
    elif update.message.text:
        broadcast_data['type'] = 'text'
        broadcast_data['text'] = update.message.text.strip()
        preview_type = '📝 Texto'
    else:
        await update.message.reply_text('❌ Tipo não suportado.')
        return AGUARDANDO_BROADCAST
    
    # Armazenar no contexto
    context.user_data['broadcast_data'] = broadcast_data
    
    # Estatísticas dos usuários
    users = await db.get_all_users()
    total_users = len(users)
    
    # Contar por status
    ativos = sum(1 for u in users.values() if u.get('status', 'ativo') == 'ativo')
    pendentes = sum(1 for u in users.values() if u.get('status') == 'pendente')
    bloqueados = sum(1 for u in users.values() if u.get('status') == 'bloqueado')
    
    # Contar por região
    regioes = {}
    for u in users.values():
        r = u.get('regiao', 'Não informada')
        regioes[r] = regioes.get(r, 0) + 1
    
    if broadcast_data['type'] == 'text':
        preview = broadcast_data['text'][:150]
        if len(broadcast_data['text']) > 150:
            preview += '...'
    else:
        preview = broadcast_data.get('caption', '(sem legenda)')[:150]
        if len(broadcast_data.get('caption', '')) > 150:
            preview += '...'
    
    msg = (
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'📢 *ENVIO DE MENSAGEM*\n'
        f'━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📋 *Tipo:* {preview_type}\n'
        f'📊 *Destinatários Totais:* {total_users}\n\n'
        f'👥 *Por Status:*\n'
        f'  ✅ Ativos: {ativos}\n'
        f'  ⏳ Pendentes: {pendentes}\n'
        f'  ⛔ Bloqueados: {bloqueados}\n\n'
        f'📍 *Top 3 Regiões:*\n'
    )
    
    # Mostrar top 3 regiões
    top_regioes = sorted(regioes.items(), key=lambda x: x[1], reverse=True)[:3]
    for idx, (regiao, qtd) in enumerate(top_regioes, 1):
        msg += f'  {idx}. {regiao}: {qtd}\n'
    
    msg += f'\n*Preview:*\n_{preview}_\n\n🎯 *Escolha os destinatários:*'
    
    keyboard = [
        [InlineKeyboardButton("👥 TODOS os Técnicos", callback_data='broadcast_send_all')],
        [InlineKeyboardButton("✅ Apenas ATIVOS", callback_data='broadcast_filter_status_ativo')],
        [InlineKeyboardButton("📍 Por REGIÃO", callback_data='broadcast_select_region')],
        [InlineKeyboardButton("🔔 Opções Avançadas", callback_data='broadcast_advanced_options')],
        [InlineKeyboardButton("❌ Cancelar", callback_data='broadcast_cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
    return AGUARDANDO_CONFIRMACAO_BROADCAST

async def confirmar_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executa o broadcast após confirmação com opções avançadas"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer('❌ Acesso negado', show_alert=True)
        return ConversationHandler.END
    
    await query.answer()
    
    if query.data == 'broadcast_cancel':
        await query.edit_message_text('❌ Broadcast cancelado.')
        context.user_data.pop('broadcast_data', None)
        context.user_data.pop('broadcast_options', None)
        return ConversationHandler.END
    
    # Opções Avançadas
    if query.data == 'broadcast_advanced_options':
        keyboard = [
            [InlineKeyboardButton("🔕 Notificação Silenciosa", callback_data='broadcast_opt_silent')],
            [InlineKeyboardButton("📌 Fixar Mensagem", callback_data='broadcast_opt_pin')],
            [InlineKeyboardButton("🔔 Notificação Normal", callback_data='broadcast_opt_normal')],
            [InlineKeyboardButton("🔙 Voltar", callback_data='broadcast_back_to_preview')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            '🔔 *Opções de Notificação*\n\n'
            'Escolha como a mensagem será enviada:\n\n'
            '🔕 *Silenciosa:* Sem som de notificação\n'
            '📌 *Fixada:* Será fixada no chat\n'
            '🔔 *Normal:* Com notificação padrão',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return AGUARDANDO_CONFIRMACAO_BROADCAST
    
    # Voltar ao preview
    if query.data == 'broadcast_back_to_preview':
        # Recriar o preview
        broadcast_data = context.user_data.get('broadcast_data', {})
        users = await db.get_all_users()
        total_users = len(users)
        
        ativos = sum(1 for u in users.values() if u.get('status', 'ativo') == 'ativo')
        pendentes = sum(1 for u in users.values() if u.get('status') == 'pendente')
        bloqueados = sum(1 for u in users.values() if u.get('status') == 'bloqueado')
        
        preview_type = {
            'text': '📝 Texto',
            'photo': '📷 Foto',
            'video': '🎥 Vídeo',
            'document': '📄 Documento',
            'audio': '🎵 Áudio',
            'voice': '🎤 Áudio de Voz'
        }.get(broadcast_data.get('type'), '❓ Desconhecido')
        
        if broadcast_data.get('type') == 'text':
            preview = broadcast_data.get('text', '')[:150]
        else:
            preview = broadcast_data.get('caption', '(sem legenda)')[:150]
        
        msg = (
            f'━━━━━━━━━━━━━━━━━━━━\n'
            f'📢 *ENVIO DE MENSAGEM*\n'
            f'━━━━━━━━━━━━━━━━━━━━\n\n'
            f'📋 *Tipo:* {preview_type}\n'
            f'📊 *Destinatários Totais:* {total_users}\n\n'
            f'👥 *Por Status:*\n'
            f'  ✅ Ativos: {ativos}\n'
            f'  ⏳ Pendentes: {pendentes}\n'
            f'  ⛔ Bloqueados: {bloqueados}\n\n'
            f'*Preview:*\n_{preview}_\n\n🎯 *Escolha os destinatários:*'
        )
        
        keyboard = [
            [InlineKeyboardButton("👥 TODOS os Técnicos", callback_data='broadcast_send_all')],
            [InlineKeyboardButton("✅ Apenas ATIVOS", callback_data='broadcast_filter_status_ativo')],
            [InlineKeyboardButton("📍 Por REGIÃO", callback_data='broadcast_select_region')],
            [InlineKeyboardButton("🔔 Opções Avançadas", callback_data='broadcast_advanced_options')],
            [InlineKeyboardButton("❌ Cancelar", callback_data='broadcast_cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        return AGUARDANDO_CONFIRMACAO_BROADCAST
    
    # Configurar opções de envio
    if query.data.startswith('broadcast_opt_'):
        opt_type = query.data.replace('broadcast_opt_', '')
        context.user_data['broadcast_options'] = {
            'silent': opt_type == 'silent',
            'pin': opt_type == 'pin',
            'normal': opt_type == 'normal'
        }
        
        opt_name = {
            'silent': '🔕 Silenciosa',
            'pin': '📌 Fixada',
            'normal': '🔔 Normal'
        }.get(opt_type, 'Normal')
        
        keyboard = [
            [InlineKeyboardButton("👥 TODOS os Técnicos", callback_data='broadcast_send_all')],
            [InlineKeyboardButton("✅ Apenas ATIVOS", callback_data='broadcast_filter_status_ativo')],
            [InlineKeyboardButton("📍 Por REGIÃO", callback_data='broadcast_select_region')],
            [InlineKeyboardButton("🔙 Voltar", callback_data='broadcast_back_to_preview')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f'✅ *Opção Selecionada:* {opt_name}\n\n'
            f'🎯 Agora escolha os destinatários:',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return AGUARDANDO_CONFIRMACAO_BROADCAST
        
    if query.data == 'broadcast_select_region':
        # Listar regiões disponíveis
        users = await db.get_all_users()
        regioes = {}
        for u in users.values():
            r = u.get('regiao')
            if r:
                status = u.get('status', 'ativo')
                if r not in regioes:
                    regioes[r] = {'total': 0, 'ativos': 0}
                regioes[r]['total'] += 1
                if status == 'ativo':
                    regioes[r]['ativos'] += 1
            
        if not regioes:
            await query.edit_message_text('❌ Nenhuma região encontrada.')
            return ConversationHandler.END
            
        keyboard = []
        for reg in sorted(regioes.keys()):
            stats = regioes[reg]
            keyboard.append([
                InlineKeyboardButton(
                    f"📍 {reg} ({stats['ativos']}/{stats['total']})", 
                    callback_data=f'broadcast_region_{reg}'
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 Voltar", callback_data='broadcast_back_to_preview')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            '🎯 *Selecione a região alvo:*\n\n'
            '_(Mostrando: ativos/total)_',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return AGUARDANDO_CONFIRMACAO_BROADCAST

    if query.data == 'broadcast_back':
        await query.edit_message_text('🔙 Operação cancelada. Envie o comando novamente.')
        return ConversationHandler.END

    # Definir alvos e filtros
    users = await db.get_all_users()
    target_users = []
    filter_description = ""
    
    # Filtro por status
    if query.data == 'broadcast_filter_status_ativo':
        target_users = [uid for uid, u in users.items() if u.get('status', 'ativo') == 'ativo']
        filter_description = "✅ Apenas técnicos ATIVOS"
    elif query.data == 'broadcast_send_all':
        target_users = list(users.keys())
        filter_description = "👥 TODOS os técnicos"
    elif query.data.startswith('broadcast_region_'):
        region = query.data.replace('broadcast_region_', '')
        target_users = [uid for uid, u in users.items() if u.get('regiao') == region]
        filter_description = f"📍 Região: {region}"
    else:
        # Fallback
        target_users = list(users.keys())
        filter_description = "👥 TODOS os técnicos"
    
    broadcast_data = context.user_data.get('broadcast_data')
    broadcast_options = context.user_data.get('broadcast_options', {})
    
    if not broadcast_data:
        await query.edit_message_text('❌ Erro: dados não encontrados.')
        return ConversationHandler.END
    
    # Configurações de envio
    pin_message = broadcast_options.get('pin', False)
    silent_notification = broadcast_options.get('silent', False)
    
    # Mensagem inicial de progresso
    progress_msg = await query.edit_message_text(
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'📤 *ENVIANDO MENSAGEM*\n'
        f'━━━━━━━━━━━━━━━━━━━━\n\n'
        f'🎯 Filtro: {filter_description}\n'
        f'👥 Total: {len(target_users)} técnicos\n\n'
        f'⏳ Iniciando envio...\n'
        f'📊 Progresso: 0/{len(target_users)} (0%)',
        parse_mode='Markdown'
    )
    
    header = '📢 *AVISO DA ADMINISTRAÇÃO*\n━━━━━━━━━━━━━━━━━━━━\n\n'
    footer = '\n\n━━━━━━━━━━━━━━━━━━━━'
    
    enviados = 0
    falhas = 0
    fixados = 0
    falhas_detalhadas = []
    sucessos_detalhados = []
    nunca_iniciaram = 0
    
    # Rate Limiter: máximo 30 mensagens por segundo
    semaphore = Semaphore(30)
    last_send_time = time.time()
    
    for idx, uid in enumerate(target_users, 1):
        try:
            # Controle de taxa com semaphore
            async with semaphore:
                current_time = time.time()
                elapsed = current_time - last_send_time
                
                # Garantir mínimo de 0.05s entre mensagens (20/segundo)
                if elapsed < 0.05:
                    await asyncio.sleep(0.05 - elapsed)
                
                message_sent = None
                user_data = users.get(uid, {})
                user_name = f"{user_data.get('nome', '')} {user_data.get('sobrenome', '')}".strip() or f"ID {uid}"
                
                if broadcast_data['type'] == 'text':
                    msg = header + broadcast_data['text'] + footer
                    message_sent = await context.bot.send_message(
                        chat_id=int(uid),
                        text=msg,
                        parse_mode='Markdown',
                        disable_notification=silent_notification
                    )
                elif broadcast_data['type'] == 'photo':
                    caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                    message_sent = await context.bot.send_photo(
                        chat_id=int(uid),
                        photo=broadcast_data['file_id'],
                        caption=caption,
                        parse_mode='Markdown',
                        disable_notification=silent_notification
                    )
                elif broadcast_data['type'] == 'video':
                    caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                    message_sent = await context.bot.send_video(
                        chat_id=int(uid),
                        video=broadcast_data['file_id'],
                        caption=caption,
                        parse_mode='Markdown',
                        disable_notification=silent_notification
                    )
                elif broadcast_data['type'] == 'document':
                    caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                    message_sent = await context.bot.send_document(
                        chat_id=int(uid),
                        document=broadcast_data['file_id'],
                        caption=caption,
                        parse_mode='Markdown',
                        disable_notification=silent_notification
                    )
                elif broadcast_data['type'] == 'audio':
                    caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                    message_sent = await context.bot.send_audio(
                        chat_id=int(uid),
                        audio=broadcast_data['file_id'],
                        caption=caption,
                        parse_mode='Markdown',
                        disable_notification=silent_notification
                    )
                elif broadcast_data['type'] == 'voice':
                    message_sent = await context.bot.send_voice(
                        chat_id=int(uid),
                        voice=broadcast_data['file_id'],
                        caption=broadcast_data.get('caption', ''),
                        parse_mode='Markdown',
                        disable_notification=silent_notification
                    )
                
                enviados += 1
                sucessos_detalhadas.append(user_name)
                
                if pin_message and message_sent:
                    try:
                        await context.bot.pin_chat_message(
                            chat_id=int(uid),
                            message_id=message_sent.message_id,
                            disable_notification=True
                        )
                        fixados += 1
                    except Exception as pin_error:
                        logger.warning(f"Não foi possível fixar mensagem para {uid}: {pin_error}")
                
                last_send_time = time.time()
                    
        except RetryAfter as e:
            # Telegram pediu para esperar
            logger.warning(f"Rate limit atingido! Aguardando {e.retry_after}s")
            await asyncio.sleep(e.retry_after)
            # Tentar reenviar
            try:
                async with semaphore:
                    if broadcast_data['type'] == 'text':
                        msg = header + broadcast_data['text'] + footer
                        await context.bot.send_message(
                            chat_id=int(uid), 
                            text=msg, 
                            parse_mode='Markdown',
                            disable_notification=silent_notification
                        )
                    enviados += 1
                    sucessos_detalhados.append(user_name)
            except Exception as retry_error:
                falhas += 1
                error_msg = str(retry_error).lower()
                if "chat not found" in error_msg:
                    nunca_iniciaram += 1
                    falhas_detalhadas.append(f"{user_name}: Nunca iniciou o bot")
                else:
                    falhas_detalhadas.append(f"{user_name}: {str(retry_error)[:50]}")
        except Exception as e:
            falhas += 1
            error_msg = str(e).lower()
            
            if "bot was blocked" in error_msg:
                falhas_detalhadas.append(f"{user_name}: Bloqueou o bot")
            elif "chat not found" in error_msg:
                nunca_iniciaram += 1
                falhas_detalhadas.append(f"{user_name}: Nunca iniciou o bot")
            else:
                falhas_detalhadas.append(f"{user_name}: {str(e)[:50]}")
        
        # Atualizar progresso a cada 10 envios ou no último
        if idx % 10 == 0 or idx == len(target_users):
            percentual = int((idx / len(target_users)) * 100)
            barra_progresso = "█" * (percentual // 5) + "░" * (20 - percentual // 5)
            
            try:
                await progress_msg.edit_text(
                    f'━━━━━━━━━━━━━━━━━━━━\n'
                    f'📤 *ENVIANDO MENSAGEM*\n'
                    f'━━━━━━━━━━━━━━━━━━━━\n\n'
                    f'🎯 Filtro: {filter_description}\n'
                    f'👥 Total: {len(target_users)} técnicos\n\n'
                    f'📊 Progresso: {idx}/{len(target_users)} ({percentual}%)\n'
                    f'{barra_progresso}\n\n'
                    f'✅ Enviados: {enviados}\n'
                    f'❌ Falhas: {falhas}',
                    parse_mode='Markdown'
                )
            except Exception:
                pass  # Ignora erro de edição muito rápida
    
    # Relatório final detalhado
    relatorio = (
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'✅ *ENVIO CONCLUÍDO!*\n'
        f'━━━━━━━━━━━━━━━━━━━━\n\n'
        f'🎯 *Filtro:* {filter_description}\n\n'
        f'📊 *Estatísticas:*\n'
        f'✅ Enviados: {enviados}\n'
        f'❌ Falhas: {falhas}\n'
        f'👥 Total Alvo: {len(target_users)}\n'
        f'📈 Taxa de Sucesso: {int((enviados/len(target_users)*100)) if target_users else 0}%\n'
    )
    
    if pin_message:
        relatorio += f'📌 Fixadas: {fixados}\n'
    
    if silent_notification:
        relatorio += f'🔕 Modo: Silencioso\n'
    
    # Adicionar nota sobre usuários que nunca iniciaram
    if nunca_iniciaram > 0:
        relatorio += f'\n⚠️ *Atenção:*\n'
        relatorio += f'📱 {nunca_iniciaram} usuário(s) nunca iniciaram conversa com o bot.\n'
        relatorio += f'💡 _Peça para eles enviarem /start no bot primeiro._\n'
    
    # Adicionar detalhes de falhas se houver
    if falhas_detalhadas and len(falhas_detalhadas) <= 10:
        relatorio += f'\n❌ *Falhas Detalhadas:*\n'
        for falha in falhas_detalhadas[:10]:
            relatorio += f'  • {falha}\n'
    elif falhas_detalhadas:
        relatorio += f'\n❌ *Primeiras 10 Falhas:*\n'
        for falha in falhas_detalhadas[:10]:
            relatorio += f'  • {falha}\n'
        relatorio += f'\n_...e mais {len(falhas_detalhadas) - 10} falhas_'
    
    await progress_msg.edit_text(relatorio, parse_mode='Markdown')
    context.user_data.pop('broadcast_data', None)
    context.user_data.pop('broadcast_options', None)
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

async def receber_id_tecnico_ajuste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    
    # Validar se é número
    if not texto.isdigit():
        await update.message.reply_text('❌ ID inválido. Digite apenas números.')
        return AGUARDANDO_ID_TECNICO_AJUSTE
        
    tecnico = await db.get_user(texto)
    if not tecnico:
        await update.message.reply_text('❌ Técnico não encontrado com este ID.\nTente novamente ou use /cancelar.')
        return AGUARDANDO_ID_TECNICO_AJUSTE
        
    context.user_data['ajuste_tecnico_id'] = texto
    context.user_data['ajuste_tecnico_nome'] = tecnico.get('username') or tecnico.get('nome')
    
    await update.message.reply_text(
        f'👤 Técnico: *{context.user_data["ajuste_tecnico_nome"]}*\n\n'
        '📅 Digite a *DATA* que deseja adicionar como dia trabalhado:\n'
        'Formato: `dd/mm/aaaa` (Ex: 01/12/2025)',
        parse_mode='Markdown'
    )
    return AGUARDANDO_DATA_AJUSTE

async def receber_data_ajuste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    try:
        data_ajuste = datetime.strptime(texto, '%d/%m/%Y')
    except:
        await update.message.reply_text('❌ Data inválida. Use o formato dd/mm/aaaa.')
        return AGUARDANDO_DATA_AJUSTE
        
    tecnico_id = context.user_data.get('ajuste_tecnico_id')
    
    # Criar registro de instalação "fake" para contar dia
    inst_ajuste = {
        'sa': f'AJUSTE-{datetime.now().strftime("%H%M%S")}',
        'gpon': 'AJUSTE-ADM',
        'tipo': 'servicos', # Tipo neutro
        'categoria': 'instalacao',
        'fotos': [],
        'tecnico_id': tecnico_id,
        'tecnico_nome': context.user_data.get('ajuste_tecnico_nome'),
        'tecnico_regiao': 'ADM',
        'serial_modem': None,
        'serial_mesh': None,
        # Importante: Hora 12:00 para não ficar 00:00 e parecer erro
        'data': data_ajuste.strftime('%d/%m/%Y 12:00') 
    }
    
    ok = await db.save_installation(inst_ajuste)
    
    if ok:
        await update.message.reply_text(
            f'✅ *Dia Adicionado com Sucesso!*\n\n'
            f'👤 Técnico: {context.user_data["ajuste_tecnico_nome"]}\n'
            f'📅 Data: {texto}\n'
            f'📝 Registro: `{inst_ajuste["sa"]}`\n\n'
            'O sistema agora contabilizará este dia na produção.',
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text('❌ Erro ao salvar no banco de dados.')
        
    return ConversationHandler.END
