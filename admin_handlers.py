from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS, TZ
from database import db
from datetime import datetime
import io
import csv
import asyncio
from telegram.error import RetryAfter, Forbidden
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

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
        return
        
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
        insts.reverse()
        
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
        keyboard = [
            [InlineKeyboardButton("📊 Enquete Simples", callback_data='poll_type_regular')],
            [InlineKeyboardButton("🎯 Quiz (com resposta correta)", callback_data='poll_type_quiz')],
            [InlineKeyboardButton("🔙 Voltar", callback_data='admin_exit')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            '📊 *Criar Enquete*\n\n'
            'Escolha o tipo de enquete:\n\n'
            '• *Enquete Simples*: Votação normal\n'
            '• *Quiz*: Com resposta correta e explicação',
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
    elif query.data == 'poll_type_regular':
        context.user_data['poll_type'] = 'regular'
        context.user_data['waiting_poll'] = True
        await query.edit_message_text(
            '📊 *Enquete Simples*\n\n'
            'Crie a enquete usando o anexo do Telegram (📎 > Enquete).\n\n'
            '💡 *Dicas:*\n'
            '• Você pode adicionar até 10 opções\n'
            '• Marque "Múltiplas respostas" se quiser permitir mais de uma escolha\n'
            '• Marque "Anônima" para ocultar quem votou',
            parse_mode='Markdown'
        )
        
    elif query.data == 'poll_type_quiz':
        context.user_data['poll_type'] = 'quiz'
        context.user_data['waiting_poll'] = True
        await query.edit_message_text(
            '🎯 *Quiz*\n\n'
            'Crie o quiz usando o anexo do Telegram (📎 > Enquete).\n\n'
            '⚠️ *IMPORTANTE:*\n'
            '• Ative o modo "Quiz"\n'
            '• Selecione a resposta correta\n'
            '• Adicione uma explicação (opcional)\n\n'
            '🏆 O bot mostrará quem acertou!',
            parse_mode='Markdown'
        )

    elif query.data == 'admin_broadcast':
        context.user_data['waiting_broadcast'] = True
        await query.edit_message_text('📢 Envie a mensagem para todos (Texto, Foto ou Vídeo):')
        
    elif query.data == 'broadcast_cancel':
        context.user_data.clear()
        await query.edit_message_text('❌ Broadcast cancelado.')
        
    elif query.data == 'broadcast_send_all':
        await enviar_broadcast(update, context, None)
        
    elif query.data == 'broadcast_select_region':
        users = await db.get_all_users()
        regioes = set()
        for u in users.values():
            r = u.get('regiao')
            if r:
                regioes.add(r)
                
        if not regioes:
            await query.edit_message_text('❌ Nenhuma região encontrada.')
            return
            
        keyboard = []
        for reg in sorted(regioes):
            keyboard.append([InlineKeyboardButton(f"📍 {reg}", callback_data=f'broadcast_region_{reg}')])
        keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data='broadcast_cancel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('🎯 Selecione a região alvo:', reply_markup=reply_markup)
        
    elif query.data.startswith('broadcast_region_'):
        region = query.data.replace('broadcast_region_', '')
        await enviar_broadcast(update, context, region)
        
    elif query.data == 'poll_cancel':
        context.user_data.clear()
        await query.edit_message_text('❌ Enquete cancelada.')
        
    elif query.data == 'poll_send_all':
        await enviar_enquete(update, context, None)
        
    elif query.data == 'poll_select_region':
        users = await db.get_all_users()
        regioes = set()
        for u in users.values():
            r = u.get('regiao')
            if r:
                regioes.add(r)
                
        if not regioes:
            await query.edit_message_text('❌ Nenhuma região encontrada.')
            return
            
        keyboard = []
        for reg in sorted(regioes):
            keyboard.append([InlineKeyboardButton(f"📍 {reg}", callback_data=f'poll_region_{reg}')])
        keyboard.append([InlineKeyboardButton("🔙 Cancelar", callback_data='poll_cancel')])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text('🎯 Selecione a região alvo:', reply_markup=reply_markup)
        
    elif query.data.startswith('poll_region_'):
        region = query.data.replace('poll_region_', '')
        await enviar_enquete(update, context, region)
        
    elif query.data == 'admin_exit':
        await query.delete_message()

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler unificado para mensagens do admin"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Broadcast
    if context.user_data.get('waiting_broadcast'):
        context.user_data['waiting_broadcast'] = False
        
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
            return
        
        context.user_data['broadcast_data'] = broadcast_data
        
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
        return
    
    # Enquete
    if context.user_data.get('waiting_poll'):
        context.user_data['waiting_poll'] = False
        
        if not update.message.poll:
            await update.message.reply_text('❌ Por favor, envie uma ENQUETE válida.')
            return
            
        poll = update.message.poll
        poll_type = context.user_data.get('poll_type', 'regular')
        
        # Validar se é quiz quando deveria ser
        if poll_type == 'quiz' and poll.type != 'quiz':
            await update.message.reply_text(
                '❌ Você escolheu criar um Quiz, mas enviou uma enquete normal.\n\n'
                'Por favor, ao criar a enquete, ative o modo "Quiz" e selecione a resposta correta.',
                parse_mode='Markdown'
            )
            context.user_data['waiting_poll'] = True
            return
        
        context.user_data['poll_data'] = {
            'question': poll.question,
            'options': [o.text for o in poll.options],
            'is_anonymous': poll.is_anonymous,
            'allows_multiple_answers': poll.allows_multiple_answers,
            'type': poll.type,
            'correct_option_id': poll.correct_option_id if poll.type == 'quiz' else None,
            'explanation': poll.explanation if poll.type == 'quiz' else None
        }
        
        users = await db.get_all_users()
        
        # Detectar tipo de enquete
        if poll.type == 'quiz':
            tipo_emoji = '🎯'
            tipo_nome = 'Quiz'
            correct_answer = poll.options[poll.correct_option_id].text if poll.correct_option_id is not None else 'N/A'
            extra_info = f'✅ Resposta correta: {correct_answer}\n'
            if poll.explanation:
                extra_info += f'� Explicação: {poll.explanation}\n'
        else:
            tipo_emoji = '�📊'
            tipo_nome = 'Enquete'
            extra_info = ''
        
        msg = (
            f'{tipo_emoji} *Confirmar {tipo_nome}*\n\n'
            f'❓ Pergunta: {poll.question}\n'
            f'🔢 Opções: {len(poll.options)}\n'
            f'{extra_info}'
            f'👥 Destinatários: {len(users)} técnicos\n\n'
            'Escolha uma opção:'
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Enviar para TODOS", callback_data='poll_send_all')],
            [InlineKeyboardButton("🎯 Selecionar Região", callback_data='poll_select_region')],
            [InlineKeyboardButton("❌ Cancelar", callback_data='poll_cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(msg, reply_markup=reply_markup, parse_mode='Markdown')

async def enviar_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, region: str = None):
    """Envia broadcast para todos ou região específica"""
    query = update.callback_query
    broadcast_data = context.user_data.get('broadcast_data')
    
    if not broadcast_data:
        await query.edit_message_text('❌ Erro: dados não encontrados.')
        return
    
    users = await db.get_all_users()
    
    if region:
        target_users = [uid for uid, u in users.items() if u.get('regiao') == region]
        msg_region = f' na região {region}'
    else:
        target_users = list(users.keys())
        msg_region = ''
    
    await query.edit_message_text(f'📤 Enviando para {len(target_users)} técnicos{msg_region}...')
    
    header = '📢 *AVISO DA ADMINISTRAÇÃO*\n━━━━━━━━━━━━━━━━━━━━\n\n'
    footer = '\n\n━━━━━━━━━━━━━━━━━━━━'
    
    enviados = 0
    falhas = 0
    
    for uid in target_users:
        try:
            if broadcast_data['type'] == 'text':
                msg = header + broadcast_data['text'] + footer
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=msg,
                    parse_mode='Markdown'
                )
            elif broadcast_data['type'] == 'photo':
                caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                await context.bot.send_photo(
                    chat_id=int(uid),
                    photo=broadcast_data['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif broadcast_data['type'] == 'video':
                caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                await context.bot.send_video(
                    chat_id=int(uid),
                    video=broadcast_data['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            elif broadcast_data['type'] == 'document':
                caption = header + broadcast_data['caption'] + footer if broadcast_data['caption'] else header.strip()
                await context.bot.send_document(
                    chat_id=int(uid),
                    document=broadcast_data['file_id'],
                    caption=caption,
                    parse_mode='Markdown'
                )
            
            enviados += 1
            await asyncio.sleep(0.05)
            
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                if broadcast_data['type'] == 'text':
                    msg = header + broadcast_data['text'] + footer
                    await context.bot.send_message(chat_id=int(uid), text=msg, parse_mode='Markdown')
                enviados += 1
            except:
                falhas += 1
        except Forbidden:
            falhas += 1
        except Exception as e:
            logger.error(f"Erro ao enviar para {uid}: {e}")
            falhas += 1
    
    relatorio = (
        f'✅ *Broadcast Concluído!*\n\n'
        f'📊 *Estatísticas:*\n'
        f'✅ Enviados: {enviados}\n'
        f'❌ Falhas: {falhas}\n'
        f'👥 Total Alvo: {len(target_users)}\n'
    )
    
    await query.edit_message_text(relatorio, parse_mode='Markdown')
    context.user_data.clear()

async def enviar_enquete(update: Update, context: ContextTypes.DEFAULT_TYPE, region: str = None):
    """Envia enquete para todos ou região específica"""
    query = update.callback_query
    poll_data = context.user_data.get('poll_data')
    
    if not poll_data:
        await query.edit_message_text('❌ Erro: dados da enquete perdidos.')
        return
        
    users = await db.get_all_users()
    
    if region:
        target_users = [uid for uid, u in users.items() if u.get('regiao') == region]
        msg_region = f' na região {region}'
    else:
        target_users = list(users.keys())
        msg_region = ''
    
    tipo_emoji = '🎯' if poll_data['type'] == 'quiz' else '📊'
    await query.edit_message_text(f'{tipo_emoji} Enviando para {len(target_users)} técnicos{msg_region}...')
    
    enviados = 0
    falhas = 0
    
    for uid in target_users:
        try:
            # Preparar kwargs baseado no tipo
            poll_kwargs = {
                'chat_id': int(uid),
                'question': poll_data['question'],
                'options': poll_data['options'],
                'is_anonymous': poll_data['is_anonymous'],
                'type': poll_data['type']
            }
            
            # Adicionar parâmetros específicos de quiz
            if poll_data['type'] == 'quiz':
                if poll_data.get('correct_option_id') is not None:
                    poll_kwargs['correct_option_id'] = poll_data['correct_option_id']
                if poll_data.get('explanation'):
                    poll_kwargs['explanation'] = poll_data['explanation']
            else:
                # Para enquetes normais
                poll_kwargs['allows_multiple_answers'] = poll_data.get('allows_multiple_answers', False)
            
            await context.bot.send_poll(**poll_kwargs)
            enviados += 1
            await asyncio.sleep(0.05)
            
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.send_poll(**poll_kwargs)
                enviados += 1
            except:
                falhas += 1
        except Forbidden:
            falhas += 1
        except Exception as e:
            logger.error(f"Erro ao enviar enquete para {uid}: {e}")
            falhas += 1
    
    tipo_nome = 'Quiz' if poll_data['type'] == 'quiz' else 'Enquete'
    await query.edit_message_text(
        f'✅ *{tipo_nome} Enviada!*\n\n'
        f'📤 Enviados: {enviados}\n'
        f'❌ Falhas: {falhas}\n'
        f'👥 Total Alvo: {len(target_users)}',
        parse_mode='Markdown'
    )
    context.user_data.clear()

