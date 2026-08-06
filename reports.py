from datetime import datetime
from config import TZ, TABELA_FAIXAS, PONTOS_SERVICO, CICLO_DIAS_TURBO
from utils import calcular_pontos, contar_dias_produtivos, obter_faixa_valor, formata_brl, parse_data

def gerar_texto_producao(instalacoes: list, inicio: datetime, fim: datetime, username: str) -> str:
    """Gera o texto do relatório de produção detalhado."""
    dias_periodo = (fim - inicio).days + 1
    media_dia = len(instalacoes) / dias_periodo if dias_periodo > 0 else 0
    pontos = calcular_pontos(instalacoes)
    dias_produtivos = contar_dias_produtivos(instalacoes)
    turbo_ativo = dias_produtivos >= CICLO_DIAS_TURBO
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

def gerar_ranking_texto(instalacoes: list, is_admin: bool = False) -> str:
    """Gera o texto do ranking de técnicos do CICLO ATUAL."""
    if not instalacoes:
        return "❌ Nenhuma instalação registrada ainda."
    
    from collections import defaultdict
    from utils import ciclo_atual
    
    # Pegar apenas instalações do ciclo atual
    inicio_ciclo, fim_ciclo = ciclo_atual()
    
    instalacoes_ciclo = []
    for inst in instalacoes:
        data_inst = parse_data(inst.get('data', ''))
        if data_inst and inicio_ciclo <= data_inst <= fim_ciclo:
            instalacoes_ciclo.append(inst)
    
    if not instalacoes_ciclo:
        return (
            f'🏆 *Ranking do Ciclo Atual*\n'
            f'📅 {inicio_ciclo.strftime("%d/%m")} a {fim_ciclo.strftime("%d/%m/%Y")}\n\n'
            f'❌ Nenhuma instalação registrada neste ciclo ainda.'
        )
    
    # Agrupar por técnico
    por_tecnico = defaultdict(lambda: {'quantidade': 0, 'pontos': 0.0, 'instalacoes': []})
    
    for inst in instalacoes_ciclo:
        nome = inst.get('tecnico_nome', 'Desconhecido')
        tipo = str(inst.get('tipo', 'instalacao')).lower()
        pontos = PONTOS_SERVICO.get(tipo, 1.0)
        
        por_tecnico[nome]['quantidade'] += 1
        por_tecnico[nome]['pontos'] += pontos
        por_tecnico[nome]['instalacoes'].append(inst)
    
    # Ordenar por pontos
    tecnicos_ordenados = sorted(
        por_tecnico.items(), 
        key=lambda x: x[1]['pontos'], 
        reverse=True
    )
    
    # Calcular totais
    total_instalacoes = len(instalacoes_ciclo)
    total_pontos = sum(t[1]['pontos'] for t in tecnicos_ordenados)
    
    msg = (
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'🏆 *RANKING DO CICLO*\n'
        f'━━━━━━━━━━━━━━━━━━━━\n\n'
        f'📅 *Período:* {inicio_ciclo.strftime("%d/%m")} a {fim_ciclo.strftime("%d/%m/%Y")}\n'
        f'📊 *Total:* {total_instalacoes} instalações\n'
    )
    
    if is_admin:
        msg += f'⭐ *Pontos Totais:* {total_pontos:.2f}\n'
    
    msg += '\n👥 *TOP TÉCNICOS:*\n'
    
    medals = ['🥇', '🥈', '🥉']
    for idx, (tecnico, dados) in enumerate(tecnicos_ordenados, 1):
        medal = medals[idx-1] if idx <= 3 else f'{idx}º'
        percentual_inst = (dados['quantidade'] / total_instalacoes) * 100
        
        if is_admin:
            # VERSÃO ADMIN - Completa com valores
            percentual_pts = (dados['pontos'] / total_pontos) * 100
            
            # Calcular dias produtivos
            dias = set()
            for inst in dados['instalacoes']:
                dt = parse_data(inst.get('data', ''))
                if dt:
                    dias.add(dt.date())
            dias_produtivos = len(dias)
            
            # Calcular valor estimado
            turbo_ativo = dias_produtivos >= CICLO_DIAS_TURBO
            tier = obter_faixa_valor(dados['pontos'])
            valor_unit = tier['valor_turbo'] if turbo_ativo else tier['valor']
            valor_estimado = dados['pontos'] * valor_unit
            
            msg += f'\n{medal} *{tecnico}*\n'
            msg += f'   📦 {dados["quantidade"]} inst. ({percentual_inst:.1f}%)\n'
            msg += f'   ⭐ {dados["pontos"]:.2f} pts ({percentual_pts:.1f}%)\n'
            msg += f'   📅 {dias_produtivos} dias | Faixa {tier["faixa"]}\n'
            msg += f'   💰 {formata_brl(valor_estimado)} {"🚀" if turbo_ativo else ""}\n'
        else:
            # VERSÃO PÚBLICA - Simples sem valores
            msg += f'\n{medal} *{tecnico}*\n'
            msg += f'   📦 {dados["quantidade"]} instalações ({percentual_inst:.1f}%)\n'
            msg += f'   ⭐ {dados["pontos"]:.2f} pontos\n'
    
    # Estatísticas do ciclo
    dias_decorridos = (datetime.now(TZ) - inicio_ciclo).days + 1
    media_dia = total_instalacoes / dias_decorridos if dias_decorridos > 0 else 0
    
    msg += (
        f'\n━━━━━━━━━━━━━━━━━━━━\n'
        f'📈 *Estatísticas:*\n'
        f'📅 Dias: {dias_decorridos}\n'
        f'📊 Média: {media_dia:.1f} inst/dia\n'
    )
    
    return msg

def gerar_relatorio_mensal(instalacoes: list) -> str:
    """Gera relatório do mês atual."""
    from collections import defaultdict
    agora = datetime.now(TZ)
    mes_atual = agora.month
    ano_atual = agora.year
    
    instalacoes_mes = []
    for inst in instalacoes:
        dt = parse_data(inst.get('data', ''))
        if dt and dt.month == mes_atual and dt.year == ano_atual:
            instalacoes_mes.append(inst)
    
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
    
    instalacoes_semana = []
    for inst in instalacoes:
        dt = parse_data(inst.get('data', ''))
        if dt and dt >= inicio_semana:
            instalacoes_semana.append(inst)
    
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
    
    instalacoes_hoje = []
    for inst in instalacoes:
        dt = parse_data(inst.get('data', ''))
        if dt and dt.date() == agora.date():
            instalacoes_hoje.append(inst)
    
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

