from datetime import datetime
from config import TZ, TABELA_FAIXAS
from utils import calcular_pontos, contar_dias_produtivos, obter_faixa_valor, formata_brl

def gerar_texto_producao(instalacoes: list, inicio: datetime, fim: datetime, username: str) -> str:
    """Gera o texto do relatório de produção detalhado."""
    dias_periodo = (fim - inicio).days + 1
    media_dia = len(instalacoes) / dias_periodo if dias_periodo > 0 else 0
    pontos = calcular_pontos(instalacoes)
    dias_produtivos = contar_dias_produtivos(instalacoes)
    turbo_ativo = dias_produtivos >= 24
    tier = obter_faixa_valor(pontos)
    valor_unit = tier['valor_turbo'] if turbo_ativo else tier['valor']
    valor_total = pontos * valor_unit
    
    progresso_msg = gerar_resumo_progresso(pontos)
    
    # Definição de ícones e status
    status_turbo = "✅ *ATIVO*" if turbo_ativo else "❌ *INATIVO*"
    if not turbo_ativo:
        status_turbo += f" ({dias_produtivos}/24 dias)"
    
    msg = (
        f'🚀 *Painel de Produtividade*\n'
        f'━━━━━━━━━━━━━━━━━━\n'
        f'👤 *Técnico:* {username}\n'
        f'📅 *Ciclo:* {inicio.strftime("%d/%m")} - {fim.strftime("%d/%m")}\n\n'
        
        f'📦 *RESUMO OPERACIONAL*\n'
        f'├ 🔧 Instalações: *{len(instalacoes)}*\n'
        f'├ ⭐ Pontos: *{pontos:.2f}*\n'
        f'└ 📅 Modo Turbo: {status_turbo}\n\n'
        
        f'💸 *FINANCEIRO (Estimado)*\n'
        f'━━━━━━━━━━━━━━━━━━\n'
        f'💰 *{formata_brl(valor_total)}*\n'
        f'_Baseado na Faixa {tier["faixa"]} - {formata_brl(valor_unit)}/pt_\n'
        f'{progresso_msg}'
    )
    return msg

def gerar_resumo_progresso(pontos: float) -> str:
    """Gera apenas a mensagem de progresso e próxima meta."""
    # Encontrar próxima faixa
    proxima_faixa = None
    for t in reversed(TABELA_FAIXAS):
        if t['min'] > pontos:
            proxima_faixa = t
            break
            
    if proxima_faixa:
        meta = proxima_faixa['min']
        falta = meta - pontos
        percentual = min(100, (pontos / meta) * 100) if meta > 0 else 100
        blocos = int(percentual / 10)
        # Barra mais sólida e bonita
        barra = "▰" * blocos + "▱" * (10 - blocos)
        
        return (
            f'\n🏆 *PRÓXIMO NÍVEL*\n'
            f'━━━━━━━━━━━━━━━━━━\n'
            f'🎯 Rumo à *Faixa {proxima_faixa["faixa"]}*\n'
            f'{barra} {percentual:.0f}%\n'
            f'⚡ Falta pouco: *{falta:.2f} pts*'
        )
    else:
        return (
            f'\n🏆 *NÍVEL MÁXIMO*\n'
            f'━━━━━━━━━━━━━━━━━━\n'
            f'👑 Você alcançou a *Faixa A*!\n'
            f'🚀 Continue assim!'
        )

def gerar_ranking_texto(instalacoes: list) -> str:
    """Gera o texto do ranking de técnicos."""
    if not instalacoes:
        return "❌ Nenhuma instalação registrada ainda."
    
    from collections import defaultdict
    por_tecnico = defaultdict(int)
    for inst in instalacoes:
        nome = inst.get('tecnico_nome', 'Desconhecido')
        por_tecnico[nome] += 1
    
    msg = f'🏆 *Ranking Geral de Técnicos*\n\n'
    msg += f'📊 *Total Geral:* {len(instalacoes)} instalações\n\n'
    
    tecnicos_ordenados = sorted(por_tecnico.items(), key=lambda x: x[1], reverse=True)
    
    medals = ['🥇', '🥈', '🥉']
    for idx, (tecnico, quantidade) in enumerate(tecnicos_ordenados, 1):
        medal = medals[idx-1] if idx <= 3 else f'{idx}º'
        percentual = (quantidade / len(instalacoes)) * 100
        msg += f'{medal} *{tecnico}*\n'
        msg += f'   {quantidade} instalações ({percentual:.1f}%)\n\n'
    
    return msg

def gerar_relatorio_mensal(instalacoes: list) -> str:
    """Gera relatório do mês atual."""
    from collections import defaultdict
    agora = datetime.now(TZ)
    mes_atual = agora.month
    ano_atual = agora.year
    
    instalacoes_mes = [
        inst for inst in instalacoes
        if datetime.strptime(inst['data'], '%d/%m/%Y %H:%M').month == mes_atual
        and datetime.strptime(inst['data'], '%d/%m/%Y %H:%M').year == ano_atual
    ]
    
    if not instalacoes_mes:
        return "❌ Nenhuma instalação registrada neste mês."
    
    por_tecnico = defaultdict(int)
    for inst in instalacoes_mes:
        por_tecnico[inst['tecnico_nome']] += 1
    
    nome_mes = agora.strftime('%B/%Y')
    msg = (
        '━━━━━━━━━━━━━━━━━━━━\n'
        '📅 *RELATÓRIO MENSAL*\n'
        '━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📆 Período: *{nome_mes}*\n'
        f'📊 Total: *{len(instalacoes_mes)} instalações*\n\n'
        '👥 *Por Técnico:*\n'
    )
    
    tecnicos_ordenados = sorted(por_tecnico.items(), key=lambda x: x[1], reverse=True)
    for tecnico, quantidade in tecnicos_ordenados:
        msg += f'  • {tecnico}: *{quantidade}* instalações\n'
    
    dias_mes = agora.day
    media_dia = len(instalacoes_mes) / dias_mes
    msg += f'\n📈 *Média diária:* {media_dia:.1f} instalações/dia'
    
    return msg

def gerar_relatorio_semanal(instalacoes: list) -> str:
    """Gera relatório da semana atual."""
    from collections import defaultdict
    from datetime import timedelta
    
    agora = datetime.now(TZ)
    inicio_semana = agora - timedelta(days=agora.weekday())
    inicio_semana = inicio_semana.replace(hour=0, minute=0, second=0, microsecond=0)
    
    instalacoes_semana = [
        inst for inst in instalacoes
        if datetime.strptime(inst['data'], '%d/%m/%Y %H:%M').replace(tzinfo=TZ) >= inicio_semana
    ]
    
    if not instalacoes_semana:
        return "❌ Nenhuma instalação registrada nesta semana."
    
    por_tecnico = defaultdict(int)
    for inst in instalacoes_semana:
        por_tecnico[inst['tecnico_nome']] += 1
    
    msg = (
        '━━━━━━━━━━━━━━━━━━━━\n'
        '📊 *RELATÓRIO SEMANAL*\n'
        '━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📆 Período: {inicio_semana.strftime("%d/%m")} a {agora.strftime("%d/%m/%Y")}\n'
        f'📊 Total: *{len(instalacoes_semana)} instalações*\n\n'
        '👥 *Por Técnico:*\n'
    )
    
    tecnicos_ordenados = sorted(por_tecnico.items(), key=lambda x: x[1], reverse=True)
    for tecnico, quantidade in tecnicos_ordenados:
        msg += f'  • {tecnico}: *{quantidade}* instalações\n'
    
    dias_semana = (agora - inicio_semana).days + 1
    media_dia = len(instalacoes_semana) / dias_semana
    msg += f'\n📈 *Média diária:* {media_dia:.1f} instalações/dia'
    
    return msg

def gerar_relatorio_hoje(instalacoes: list) -> str:
    """Gera relatório do dia atual."""
    from collections import defaultdict
    
    agora = datetime.now(TZ)
    
    instalacoes_hoje = [
        inst for inst in instalacoes
        if datetime.strptime(inst['data'], '%d/%m/%Y %H:%M').date() == agora.date()
    ]
    
    if not instalacoes_hoje:
        return "❌ Nenhuma instalação registrada hoje."
    
    por_tecnico = defaultdict(int)
    for inst in instalacoes_hoje:
        por_tecnico[inst['tecnico_nome']] += 1
    
    msg = (
        '━━━━━━━━━━━━━━━━━━━━\n'
        '📈 *RELATÓRIO DE HOJE*\n'
        '━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📅 Data: *{agora.strftime("%d/%m/%Y")}*\n'
        f'📊 Total: *{len(instalacoes_hoje)} instalações*\n\n'
        '👥 *Por Técnico:*\n'
    )
    
    tecnicos_ordenados = sorted(por_tecnico.items(), key=lambda x: x[1], reverse=True)
    for tecnico, quantidade in tecnicos_ordenados:
        msg += f'  • {tecnico}: *{quantidade}* instalações\n'
    
    return msg

