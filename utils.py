from datetime import datetime
from config import TZ, PONTOS_SERVICO, TABELA_FAIXAS

def formata_brl(v: float) -> str:
    """Formata um valor float para string de moeda BRL."""
    s = f"{v:,.2f}"
    s = s.replace(',', 'X').replace('.', ',').replace('X', '.')
    return f"R$ {s}"

def calcular_pontos(instalacoes: list) -> float:
    """Calcula o total de pontos de uma lista de instalações."""
    total = 0.0
    for inst in instalacoes:
        tipo = str(inst.get('tipo') or 'instalacao').lower()
        total += PONTOS_SERVICO.get(tipo, 1.0)
    return total

def contar_dias_produtivos(instalacoes: list) -> int:
    """Conta quantos dias únicos existem na lista de instalações."""
    dias = set()
    for inst in instalacoes:
        try:
            # Assume formato dd/mm/YYYY HH:MM
            dt = datetime.strptime(inst['data'], '%d/%m/%Y %H:%M')
            dias.add(dt.date())
        except (ValueError, KeyError):
            continue
    return len(dias)

def obter_faixa_valor(pontos: float):
    """Retorna a faixa de valor baseada nos pontos."""
    p = float(pontos)
    for tier in TABELA_FAIXAS:
        if tier['min'] <= p <= tier['max']:
            return tier
    return TABELA_FAIXAS[-1]

def ciclo_atual():
    """Retorna o início e fim do ciclo de produção atual (dia 16 a 15)."""
    agora = datetime.now(TZ)
    if agora.day >= 16:
        inicio = datetime(agora.year, agora.month, 16, tzinfo=TZ)
        ano = agora.year + 1 if agora.month == 12 else agora.year
        mes = 1 if agora.month == 12 else agora.month + 1
        fim = datetime(ano, mes, 15, 23, 59, tzinfo=TZ)
    else:
        ano_prev = agora.year - 1 if agora.month == 1 else agora.year
        mes_prev = 12 if agora.month == 1 else agora.month - 1
        inicio = datetime(ano_prev, mes_prev, 16, tzinfo=TZ)
        fim = datetime(agora.year, agora.month, 15, 23, 59, tzinfo=TZ)
    return inicio, fim

def escape_markdown(text):
    """Escapa caracteres especiais para MarkdownV2."""
    if text is None:
        return 'não informada'
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    text = str(text)
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text
