from datetime import datetime
from config import TZ, PONTOS_SERVICO, TABELA_FAIXAS, USE_GROQ, GROQ_API_KEY, GROQ_MODEL, CICLO_DIA_INICIO, CICLO_DIAS_TURBO
import base64
import json
import re
import logging
import asyncio
from typing import List, Optional, Dict, Any

# Configurar logger
logger = logging.getLogger(__name__)

# ==================== PROMPTS E CONSTANTES OCR ====================

OCR_SYSTEM_DEFAULT = (
    "Você é um assistente especializado em OCR de dados técnicos de telecomunicações. "
    "Sua tarefa é extrair EXATAMENTE os dados solicitados de prints de tela de sistemas técnicos. "
    "Retorne APENAS um JSON válido."
)

OCR_USER_DEFAULT = (
    "Analise a imagem e extraia os seguintes dados:\n"
    "1. SA (Service Order): Formato geralmente numérico ou SA-números.\n"
    "2. GPON (Acesso/Designação): MUITO IMPORTANTE! Procure por:\n"
    "   - Labels: 'GPON', 'Acesso', 'Designação', 'ONT ID', 'Código de Acesso'\n"
    "   - Formato: Código alfanumérico com 6-20 caracteres\n"
    "   - Pode conter: letras, números, traços (-), pontos (.), barras (/)\n"
    "   - Exemplos: ABCD123456, ABC-123-456, ABC.123.456, ABC/123/456\n"
    "   - Geralmente está próximo ao nome do cliente ou endereço\n"
    "   - ATENÇÃO: NÃO confunda com CPF, telefone ou CEP!\n"
    "3. Serial do Modem (ONT/ONU): Código alfanumérico longo (ex: ZTEGC8..., ALCLB...). É o equipamento PRINCIPAL. Procure por 'Serial', 'S/N', 'SN', 'ONT ID'.\n"
    "4. Seriais Mesh: Códigos alfanuméricos de extensores/roteadores mesh (equipamentos SECUNDÁRIOS). Retorne uma lista. NÃO inclua o serial do modem aqui.\n\n"
    "Regras:\n"
    "- Se encontrar múltiplos códigos parecidos com GPON, escolha o que está mais próximo de 'Acesso' ou 'Designação'\n"
    "- Ignore dados que não sejam claramente identificáveis.\n"
    "- Converta tudo para MAIÚSCULAS.\n"
    "- Mantenha traços, pontos e barras no GPON se existirem.\n"
    "- Se não encontrar, retorne null.\n\n"
    "Retorne o JSON no seguinte formato:\n"
    "{\n"
    '  "sa": "...",\n'
    '  "gpon": "...",\n'
    '  "serial_do_modem": "...",\n'
    '  "mesh": ["..."]\n'
    "}"
)

OCR_SYSTEM_MASK = (
    "Você é um especialista em OCR de sistemas técnicos de telecomunicações. "
    "Sua tarefa é extrair TODOS os dados solicitados com MÁXIMA precisão. "
    "NUNCA deixe campos vazios se a informação estiver visível na tela. "
    "Procure em TODAS as partes da imagem: cabeçalhos, tabelas, campos de formulário, labels, etc. "
    "Se houver múltiplas imagens, combine as informações para completar TODOS os campos. "
    "Retorne APENAS um JSON válido e completo."
)

CAMPO_INSTRUCOES = {
    'sa': "Número da SA/OS/Pedido. Procure por: 'SA' no TOPO DA TELA (ex: SA-37273090) ou campo 'SA'.",
    'gpon': "Código GPON/Designação/Acesso. CRÍTICO! Procure na ABA REDE por 'Acesso GPON' (ex: A0002VG20). Formato alfanumérico com 6-20 caracteres. NÃO confunda com CPF ou telefone!",
    'cliente': "Nome completo do cliente. Procure na ABA INFO ou ABA CLIENTE por 'Cliente'.",
    'documento': "CPF/CNPJ do cliente. Procure na ABA INFO por 'Doc. Assoc.' (ex: 10426209).",
    'telefone': "Telefone de contato. Procure na ABA CLIENTE por 'Contato 1' ou 'Contato Principal' (ex: 47997849329).",
    'endereco': "Endereço completo. Procure na ABA INFO ou ABA CLIENTE por 'Endereço' (inclui rua, número, bairro, CEP, cidade).",
    'cdo': "Código da CDO/CDOE. Procure por: 'CDO', 'CDOE', 'Caixa', 'Armário Óptico'.",
    'porta': "Número da porta. Procure por: 'Porta', 'Port', 'P', 'Porta CDO', 'Porta Cliente'.",
    'estacao': "Estação/Armário. Procure por: 'Estação', 'EST', 'Armário', 'Central'.",
    'atividade': "Tipo de atividade/serviço. Procure na ABA INFO por 'Atividade' (ex: INSTALAÇÃO BL + MESH)."
}

OCR_PROMPTS_ESPECIFICOS = {
    "sa": "Extraia apenas o número da SA (Service Order). Retorne JSON: {\"sa\": \"valor\"}",
    "gpon": (
        "Extraia APENAS o código GPON/Acesso/Designação. "
        "IMPORTANTE: Procure por labels como 'GPON', 'Acesso', 'Designação', 'ONT ID', 'Código de Acesso'. "
        "O GPON é um código alfanumérico com 6-20 caracteres, pode conter traços, pontos ou barras. "
        "Exemplos válidos: ABCD123456, ABC-123-456, ABC.123.456, ABC/123/456. "
        "NÃO confunda com CPF, telefone, CEP ou endereço! "
        "Retorne JSON: {\"gpon\": \"valor\"}"
    ),
    "serial_do_modem": "Extraia apenas o Serial Number (S/N) do modem/ONT principal. NÃO confunda com Mesh. Retorne JSON: {\"serial_do_modem\": \"valor\"}",
    "mesh": "Extraia apenas os Seriais de equipamentos Mesh (extensores). NÃO inclua o modem principal. Retorne JSON: {\"mesh\": [\"valor1\", \"valor2\"]}"
}

# ==================== VALIDAÇÃO ====================

def is_valid_sa(sa: str) -> bool:
    try:
        # Accept both formats: "SA-12345" and just numeric "12345"
        return bool(re.fullmatch(r"(SA-)?\d{5,}", sa or ""))
    except Exception:
        return False

def is_valid_gpon(gpon: str) -> bool:
    """Valida GPON com múltiplos formatos aceitos."""
    try:
        if not gpon:
            return False
        
        gpon = str(gpon).strip().upper()
        
        # Aceitar vários formatos comuns de GPON:
        # 1. Alfanumérico puro (6-20 caracteres)
        if re.fullmatch(r"[A-Z0-9]{6,20}", gpon):
            return True
        
        # 2. Com traços ou pontos (ex: ABC-123-456 ou ABC.123.456)
        if re.fullmatch(r"[A-Z0-9\-\.]{6,25}", gpon):
            return True
        
        # 3. Com barras (ex: ABC/123/456)
        if re.fullmatch(r"[A-Z0-9/]{6,25}", gpon):
            return True
        
        return False
    except Exception:
        return False

def is_valid_serial(s: str) -> bool:
    try:
        if not s: return False
        if s.upper().startswith("SA-"): return False
        return bool(re.fullmatch(r"[A-Z0-9]{8,20}", s))
    except Exception:
        return False

def parse_data(data_str: str) -> Optional[datetime]:
    """Converte string de data (ISO ou BR legado) para datetime com TZ. Retorna None se inválido."""
    if not data_str:
        return None
    # Formato ISO (novos registros): 2026-04-01T12:20:00-03:00
    try:
        dt = datetime.fromisoformat(str(data_str))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt
    except (ValueError, TypeError):
        pass
    # Formato BR legado (registros antigos): 01/04/2026 12:20
    try:
        return datetime.strptime(str(data_str), '%d/%m/%Y %H:%M').replace(tzinfo=TZ)
    except (ValueError, TypeError):
        return None

def format_data(data_str: str) -> str:
    """Formata string de data (ISO ou BR) para exibição no formato BR dd/mm/YYYY HH:MM."""
    dt = parse_data(data_str)
    if dt:
        return dt.strftime('%d/%m/%Y %H:%M')
    return str(data_str) if data_str else 'N/A'

try:
    from groq import Groq
except Exception:
    Groq = None

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
        dt = parse_data(inst.get('data', ''))
        if dt:
            dias.add(dt.date())
    return len(dias)

def obter_faixa_valor(pontos: float):
    """Retorna a faixa de valor baseada nos pontos."""
    p = float(pontos)
    # Assume TABELA_FAIXAS ordenada decrescente por min (A -> I)
    for tier in TABELA_FAIXAS:
        if p >= tier['min']:
            return tier
    return TABELA_FAIXAS[-1]

def ciclo_atual():
    """Retorna o início e fim do ciclo de produção atual (configurável via CICLO_DIA_INICIO)."""
    agora = datetime.now(TZ)
    dia_inicio = CICLO_DIA_INICIO  # Padrão: 16
    dia_fim = dia_inicio - 1       # Padrão: 15
    
    if agora.day >= dia_inicio:
        inicio = datetime(agora.year, agora.month, dia_inicio, tzinfo=TZ)
        ano = agora.year + 1 if agora.month == 12 else agora.year
        mes = 1 if agora.month == 12 else agora.month + 1
        fim = datetime(ano, mes, dia_fim, 23, 59, tzinfo=TZ)
    else:
        ano_prev = agora.year - 1 if agora.month == 1 else agora.year
        mes_prev = 12 if agora.month == 1 else agora.month - 1
        inicio = datetime(ano_prev, mes_prev, dia_inicio, tzinfo=TZ)
        fim = datetime(agora.year, agora.month, dia_fim, 23, 59, tzinfo=TZ)
    return inicio, fim

def escape_markdown(text):
    if text is None:
        return 'não informada'
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '=', '|', '{', '}', '.', '!']
    text = str(text)
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def _call_groq_vision(
    system_prompt: str,
    user_prompt: str,
    images: List[bytes],
    json_mode: bool = True,
    retries: int = 2,
    timeout_seconds: int = 30
) -> str:
    """
    Função centralizada para chamar a API de visão da Groq com retry, fallback de modelos e timeout.
    """
    logger.info(f"[OCR] Iniciando chamada Groq - USE_GROQ: {USE_GROQ}, GROQ_API_KEY setado: {bool(GROQ_API_KEY)}, Groq disponível: {Groq is not None}")
    
    if not USE_GROQ or not GROQ_API_KEY or Groq is None:
        logger.warning("[OCR] Groq não configurado, retornando vazio")
        return "{}" if json_mode else ""

    client = Groq(api_key=GROQ_API_KEY)
    
    # Modelos em ordem de preferência (usando modelos disponíveis no Groq)
    models = [
        GROQ_MODEL or "qwen/qwen3.6-27b",
        # Add other models if needed, but qwen/qwen3.6-27b is the only one with image support right now
    ]
    logger.info(f"[OCR] Modelos a tentar: {models}")
    
    # Preparar conteúdo do usuário (limita a 3 imagens, máximo suportado pelo modelo)
    content = [{"type": "text", "text": user_prompt}]
    # Pega apenas as primeiras 3 imagens
    limited_images = images[:3]
    logger.info(f"[OCR] Total de imagens recebidas: {len(images)}, usando apenas as primeiras {len(limited_images)}")
    for idx, img in enumerate(limited_images):
        b64 = base64.b64encode(img).decode("ascii")
        logger.info(f"[OCR] Imagem {idx+1} codificada em base64, tamanho: {len(b64)} chars")
        content.append({
            "type": "image_url", 
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    last_error = None

    for attempt in range(retries + 1):
        logger.info(f"[OCR] Tentativa {attempt+1}/{retries+1}")
        for model in models:
            logger.info(f"[OCR] Tentando modelo: {model}")
            try:
                # Adicionar timeout para evitar travamentos
                async def call_api():
                    kwargs = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": content}
                        ],
                        "temperature": 0.1, 
                        "max_completion_tokens": 1024,
                    }
                    
                    if json_mode:
                        kwargs["response_format"] = {"type": "json_object"}
                    
                    # Groq client é síncrono, então rodamos em executor
                    loop = asyncio.get_running_loop()
                    resp = await loop.run_in_executor(
                        None,
                        lambda: client.chat.completions.create(**kwargs)
                    )
                    return resp.choices[0].message.content or ("{}" if json_mode else "")
                
                # Aplicar timeout
                result = await asyncio.wait_for(call_api(), timeout=timeout_seconds)
                logger.info(f"[OCR] Sucesso com modelo {model}! Resultado: {result[:200]}...")
                return result
                
            except asyncio.TimeoutError:
                last_error = f"Timeout ({timeout_seconds}s)"
                logging.warning(f"Groq vision timeout (tentativa {attempt+1}, modelo {model})")
                continue
                
            except Exception as e:
                last_error = e
                logging.warning(f"Groq vision falhou (tentativa {attempt+1}, modelo {model}): {type(e).__name__}: {e}", exc_info=True)
                continue # Tenta próximo modelo
        
        # Se falhou com todos os modelos, espera um pouco antes do próximo retry
        if attempt < retries:
            wait_time = 2 ** attempt
            logger.info(f"[OCR] Aguardando {wait_time}s antes da próxima tentativa...")
            await asyncio.sleep(wait_time)  # Backoff exponencial: 1s, 2s, 4s

    logging.error(f"Todas as tentativas de OCR falharam. Último erro: {last_error}")
    return "{}" if json_mode else ""


async def extrair_campos_por_imagem(image_bytes: bytes) -> dict:
    """
    Extrai SA, GPON, Serial Modem e Mesh de uma imagem.
    """
    # Tenta extração via JSON mode
    response_text = await _call_groq_vision(OCR_SYSTEM_DEFAULT, OCR_USER_DEFAULT, [image_bytes], json_mode=True)
    
    data = {}
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        # Fallback: tentar extrair JSON de texto sujo se o modo JSON falhar silenciosamente
        try:
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
        except json.JSONDecodeError:
            logger.warning(f"[OCR] extrair_campos_por_imagem: fallback JSON também falhou. Resposta: {response_text[:200]!r}")

    # Normalização e Validação
    sa = str(data.get("sa") or "").strip().upper()
    gpon = str(data.get("gpon") or "").strip().upper()
    serial = str(data.get("serial_do_modem") or "").strip().upper()
    mesh_raw = data.get("mesh") or []
    
    if isinstance(mesh_raw, str): mesh_raw = [mesh_raw]
    mesh = [str(m).strip().upper() for m in mesh_raw if is_valid_serial(str(m).strip().upper())]

    # Validação final com Regex (Fallback se a IA alucinar formatos)
    if sa and re.match(r"^\d+$", sa): sa = f"SA-{sa}" # Adiciona prefixo se faltar
    if not is_valid_sa(sa): sa = None
    
    if not is_valid_gpon(gpon): gpon = None
    
    if not is_valid_serial(serial): serial = None
    
    # Se a IA falhou completamente (tudo None), tentar Regex bruto no texto da imagem?
    # A API de visão não retorna texto bruto facilmente sem OCR específico.
    # Vamos confiar que se a IA falhou no JSON, o Regex de fallback no texto bruto seria complexo de implementar sem uma chamada de "descreva a imagem".
    # Mas podemos fazer uma segunda chamada pedindo texto bruto se tudo falhar. Por enquanto, vamos manter simples.

    return {
        "sa": sa,
        "gpon": gpon,
        "serial_do_modem": serial,
        "mesh": mesh
    }


async def extrair_campos_por_imagens(images: list) -> dict:
    """
    Processa múltiplas imagens e agrega os resultados.
    """
    agg = {"sa": None, "gpon": None, "serial_do_modem": None, "mesh": []}
    
    # Processa cada imagem individualmente (poderíamos enviar todas juntas, mas a resolução pode cair)
    # Para economizar tokens/chamadas, se tivermos muitas imagens, talvez enviar juntas seja melhor.
    # O código original fazia loop. Vamos manter loop para garantir qualidade máxima por print.
    
    for img in images:
        d = await extrair_campos_por_imagem(img)
        
        # Merge inteligente: Prioriza valores válidos sobre Nones
        if d.get("sa") and not agg["sa"]: agg["sa"] = d["sa"]
        if d.get("gpon") and not agg["gpon"]: agg["gpon"] = d["gpon"]
        if d.get("serial_do_modem") and not agg["serial_do_modem"]: agg["serial_do_modem"] = d["serial_do_modem"]
        
        # Merge de listas sem duplicatas
        for m in d.get("mesh", []):
            if m not in agg["mesh"] and m != agg["gpon"] and m != agg["serial_do_modem"]:
                agg["mesh"].append(m)
                
    return agg


async def extrair_campo_especifico(images: List[bytes], campo: str) -> dict:
    """
    Extrai um campo específico de uma ou mais imagens com prompt focado.
    """
    user_prompt = OCR_PROMPTS_ESPECIFICOS.get(campo, f"Extraia o campo {campo}. Retorne JSON.")
    system_prompt = "Você é um especialista em OCR. Extraia apenas o dado solicitado. Se não encontrar, retorne null no JSON."

    response_text = await _call_groq_vision(system_prompt, user_prompt, images, json_mode=True)
    
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.warning(f"[OCR] extrair_campo_especifico '{campo}': falha ao parsear JSON. Erro: {e}. Resposta: {response_text[:200]!r}")
        return {}

    # Validação específica
    result = {}
    if campo == "sa":
        val = str(data.get("sa") or "").strip().upper()
        if re.match(r"^\d+$", val): val = f"SA-{val}"
        if is_valid_sa(val): result["sa"] = val
        
    elif campo == "gpon":
        val = str(data.get("gpon") or "").strip().upper()
        if is_valid_gpon(val): result["gpon"] = val
        
    elif campo == "serial_do_modem":
        val = str(data.get("serial_do_modem") or "").strip().upper()
        if is_valid_serial(val): result["serial_do_modem"] = val
        
    elif campo == "mesh":
        raw = data.get("mesh") or []
        if isinstance(raw, str): raw = [raw]
        valid_mesh = [str(m).strip().upper() for m in raw if is_valid_serial(str(m).strip().upper())]
        if valid_mesh: result["mesh"] = valid_mesh

    return result

async def extrair_dados_completos(images: List[bytes], tipo_mascara: str = None) -> dict:
    """
    Extrai todos os dados possíveis de uma ou mais imagens para preenchimento de máscaras.
    Se tipo_mascara for fornecido, foca nos campos específicos daquela máscara.
    """

    
    # Instruções detalhadas para cada campo

    
    # Personalização por tipo de máscara para máximo foco
    if tipo_mascara == 'Batimento CDOE':
        campos_requeridos = ['atividade', 'estacao', 'cdo', 'porta', 'gpon']
        instrucoes_extras = (
            "\n⚠️ CRÍTICO para Batimento CDOE:\n"
            "- ATIVIDADE: Identifique o tipo de serviço/atividade\n"
            "- ESTAÇÃO: Localize código da estação/armário\n"
            "- CDOE: ESSENCIAL - Código da caixa de distribuição\n"
            "- PORTA: ESSENCIAL - Número da porta na CDO\n"
            "- GPON: Código de acesso GPON/designação\n"
        )
    elif tipo_mascara == 'Pendência':
        campos_requeridos = ['atividade', 'sa', 'documento', 'gpon', 'cliente', 'telefone', 'endereco']
        instrucoes_extras = (
            "\n⚠️ CRÍTICO para Pendência:\n"
            "- ATIVIDADE: Tipo de serviço (Instalação/Reparo/etc)\n"
            "- SA: ESSENCIAL - Número da SA/Ordem de Serviço\n"
            "- DOCUMENTO: ESSENCIAL - CPF/CNPJ (procure 'Doc. Assoc.')\n"
            "- GPON: Acesso/Designação GPON\n"
            "- CLIENTE: Nome completo do cliente\n"
            "- TELEFONE: Número de contato\n"
            "- ENDEREÇO: Endereço completo (rua, número, bairro)\n"
        )
    elif tipo_mascara == 'Cancelamento':
        campos_requeridos = ['sa', 'documento', 'telefone', 'cliente']
        instrucoes_extras = (
            "\n⚠️ CRÍTICO para Cancelamento:\n"
            "- SA: ESSENCIAL - Número do Pedido/SA\n"
            "- DOCUMENTO: ESSENCIAL - CPF/CNPJ/Doc. Assoc.\n"
            "- TELEFONE: Número de contato\n"
            "- CLIENTE: Nome do cliente\n"
        )
    elif tipo_mascara == 'Repasse':
        campos_requeridos = ['sa', 'gpon', 'documento', 'cdo', 'porta', 'endereco', 'cliente', 'telefone']
        instrucoes_extras = (
            "\n⚠️ CRÍTICO para Repasse:\n"
            "- SA: ESSENCIAL - Número da SA\n"
            "- GPON: ESSENCIAL - Acesso GPON\n"
            "- DOCUMENTO: ESSENCIAL - Doc. Assoc./CPF (campo muito importante!)\n"
            "- CDO: Código da caixa CDO\n"
            "- PORTA: Número da porta\n"
            "- ENDEREÇO: Endereço completo\n"
            "- CLIENTE: Nome do cliente\n"
            "- TELEFONE: Contato\n"
        )
    else:
        campos_requeridos = ['sa', 'gpon', 'cliente', 'documento', 'telefone', 'endereco', 'cdo', 'porta', 'estacao', 'atividade']
        instrucoes_extras = "\n⚠️ Extraia TODOS os campos disponíveis nas imagens."
    
    # Construir prompt com instruções detalhadas
    instrucoes_campos = "\n".join([f"- {campo}: {CAMPO_INSTRUCOES[campo]}" for campo in campos_requeridos if campo in CAMPO_INSTRUCOES])
    
    user = (
        f"🎯 TAREFA: Extrair dados para máscara '{tipo_mascara or 'Geral'}'\n\n"
        f"📋 CAMPOS OBRIGATÓRIOS:{instrucoes_extras}\n\n"
        f"🔍 ONDE PROCURAR CADA CAMPO:\n{instrucoes_campos}\n\n"
        "💡 DICAS ESPECÍFICAS PARA ESSE APP:\n"
        "- As imagens são ABAS DIFERENTES DE UM MESMO TICKET (INFO, CLIENTE, REDE, etc.)\n"
        "- Analise TODAS as imagens e COMBINE as informações delas\n"
        "- Procure em títulos, labels, campos, tabelas\n"
        "- Se encontrar apenas parte da informação, use-a\n"
        "- Converta tudo para MAIÚSCULAS\n"
        "- Remove espaços extras, mas mantenha formatação de CPF/telefone se houver\n"
        "- Se um campo realmente não existir na imagem, use string vazia\n\n"
        "📤 FORMATO DE SAÍDA (JSON):\n"
        "{\n"
        '  "sa": "...",\n'
        '  "gpon": "...",\n'
        '  "cliente": "...",\n'
        '  "documento": "...",\n'
        '  "telefone": "...",\n'
        '  "endereco": "...",\n'
        '  "cdo": "...",\n'
        '  "porta": "...",\n'
        '  "estacao": "...",\n'
        '  "atividade": "..."\n'
        "}"
    )

    response_text = await _call_groq_vision(OCR_SYSTEM_MASK, user, images, json_mode=True)
    
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"[OCR] extrair_dados_completos: falha ao parsear JSON da resposta. Erro: {e}. Resposta recebida: {response_text[:300]!r}")
        return {}
        
    # Limpeza e normalização
    result = {}
    for k, v in data.items():
        if v is None or v == "null":
            result[k] = ""
        else:
            # Manter formatação original em telefone e documento (CPF pode ter pontuação)
            if k in ['telefone', 'documento']:
                result[k] = str(v).strip()
            else:
                result[k] = str(v).strip().upper()
    
    return result
