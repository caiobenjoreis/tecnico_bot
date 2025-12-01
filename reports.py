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
    
    # Encontrar próxima faixa
    proxima_faixa = None
    for t in reversed(TABELA_FAIXAS):
        if t['min'] > pontos:
            proxima_faixa = t
            break
            
    # Barra de progresso
    progresso_msg = ""
    if proxima_faixa:
        meta = proxima_faixa['min']
        falta = meta - pontos
        percentual = min(100, (pontos / meta) * 100) if meta > 0 else 100
        blocos = int(percentual / 10)
        barra = "█" * blocos + "░" * (10 - blocos)
        
        inst_faltantes = int(falta / 1.5) + 1
        
        progresso_msg = (
            f'\n🎯 *Próxima Meta: Faixa {proxima_faixa["faixa"]}*\n'
            f'Progresso: `{barra}` {percentual:.1f}%\n'
            f'Faltam: *{falta:.2f} pontos* (~{inst_faltantes} inst.)\n'
        )
    else:
        progresso_msg = "\n🏆 *Parabéns! Você atingiu a faixa máxima!*\n"

    msg = (
        f'📆 *Produção no Período*\n'
        f'Período: {inicio.strftime("%d/%m/%Y")} a {fim.strftime("%d/%m/%Y")}\n'
        f'👤 Técnico: {username}\n\n'
        f'📊 *Resumo:*\n'
        f'• Instalações: {len(instalacoes)}\n'
        f'• Pontos: *{pontos:.2f}*\n'
        f'• Dias Produtivos: {dias_produtivos}/24\n'
        f'• Média Diária: {media_dia:.1f}\n'
        f'{progresso_msg}\n'
        f'💰 *Financeiro:*\n'
        f'• Faixa Atual: *{tier["faixa"]}*\n'
        f'• Modo Turbo: {"✅ ATIVO" if turbo_ativo else "❌ INATIVO"}\n'
        f'• Valor Ponto: {formata_brl(valor_unit)}\n'
        f'• *Total Estimado: {formata_brl(valor_total)}*\n'
    )
    return msg

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

