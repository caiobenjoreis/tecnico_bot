from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS, AGUARDANDO_BROADCAST, AGUARDANDO_CONFIRMACAO_BROADCAST, TZ
from database import db
from datetime import datetime
import io
import csv

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
        # Estatísticas simplificadas para não travar
        users = await db.get_all_users()
        # Para total de instalações, ideal seria count(), mas get_installations traz lista
        # Vamos limitar a query para não explodir
        insts = await db.get_installations(limit=1000) 
        
        msg = (
            f'📊 *Estatísticas*\n\n'
            f'👥 Técnicos: {len(users)}\n'
            f'📦 Instalações (Amostra): {len(insts)}\n'
        )
        await query.edit_message_text(msg, parse_mode='Markdown')
        
    elif query.data == 'admin_users':
        users = await db.get_all_users()
        msg = f'👥 *Técnicos ({len(users)})*\n\n'
        for uid, u in list(users.items())[:20]:
            msg += f'👤 {u.get("nome")} {u.get("sobrenome")} | {u.get("regiao")}\n'
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
            document=csv_bytes,
            filename=filename,
            caption='📊 Exportação Completa'
        )
        
    elif query.data == 'admin_broadcast':
        await query.edit_message_text('📢 Envie a mensagem para todos (Texto, Foto ou Vídeo):')
        return AGUARDANDO_BROADCAST
        
    elif query.data == 'admin_exit':
        await query.delete_message()
        
    return None

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
        [InlineKeyboardButton("✅ Enviar", callback_data='broadcast_send')],
        [InlineKeyboardButton("📌 Enviar e Fixar", callback_data='broadcast_send_pin')],
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
    
    pin_message = query.data == 'broadcast_send_pin'
    broadcast_data = context.user_data.get('broadcast_data')
    
    if not broadcast_data:
        await query.edit_message_text('❌ Erro: dados não encontrados.')
        return ConversationHandler.END
    
    users = await db.get_all_users()
    await query.edit_message_text('📤 Enviando...')
    
    header = '📢 *AVISO DA ADMINISTRAÇÃO*\n━━━━━━━━━━━━━━━━━━━━\n\n'
    footer = '\n\n━━━━━━━━━━━━━━━━━━━━'
    
    enviados = 0
    falhas = 0
    fixados = 0
    
    for uid in users.keys():
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
        except:
            falhas += 1
    
    relatorio = (
        f'✅ *Broadcast Concluído!*\n\n'
        f'📊 *Estatísticas:*\n'
        f'✅ Enviados: {enviados}\n'
        f'❌ Falhas: {falhas}\n'
        f'👥 Total: {len(users)}\n'
    )
    
    if pin_message:
        relatorio += f'📌 Fixadas: {fixados}\n'
    
    await query.edit_message_text(relatorio, parse_mode='Markdown')
    context.user_data.pop('broadcast_data', None)
    return ConversationHandler.END

