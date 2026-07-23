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
    
    # Comprime e redimensiona imagens — equilíbrio entre qualidade OCR e limite de tokens do Groq.
    # 800px / qualidade 70 → ~80-120KB → ~3500-5000 tokens. Deixa margem para o prompt e resposta.
    def compress_image(img_bytes: bytes, max_size: int = 800, quality: int = 70) -> bytes:
        """Redimensiona e comprime imagem para caber no limite de tokens do Groq."""
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(img_bytes))
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            out = _io.BytesIO()
            img.save(out, format='JPEG', quality=quality, optimize=True)
            compressed = out.getvalue()
            logger.info(f"[OCR] Imagem comprimida: {len(img_bytes)//1024}KB → {len(compressed)//1024}KB")
            return compressed
        except Exception as e:
            logger.warning(f"[OCR] Falha ao comprimir imagem: {e} — usando original")
            return img_bytes

    # 1 imagem por chamada para controlar tokens
    limited_images = images[:1]
    compressed_images = [compress_image(img) for img in limited_images]
    logger.info(f"[OCR] Imagens: {len(images)} recebidas, enviando {len(compressed_images)} ao Groq")

    content = [{"type": "text", "text": user_prompt}]
    for idx, img in enumerate(compressed_images):
        b64 = base64.b64encode(img).decode("ascii")
        est_tokens = len(b64) // 750
        logger.info(f"[OCR] Imagem {idx+1}: {len(b64)} chars base64 (~{est_tokens} tokens)")
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
                    # Para o modelo qwen/qwen3.6-27b com visão, a documentação oficial do Groq
                    # recomenda incluir as instruções diretamente no user message junto com a imagem,
                    # em vez de usar um system message separado. Isso evita o erro 400 json_validate_failed.
                    # Ref: https://console.groq.com/docs/vision
                    user_content_with_system = [
                        {"type": "text", "text": f"{system_prompt}\n\n{content[0]['text']}"}
                    ] + content[1:]  # mantém as imagens

                    kwargs = {
                        "model": model,
                        "messages": [
                            {"role": "user", "content": user_content_with_system}
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
    # Prompt curto e direto com labels exatos do app para cada tipo de máscara.
    if tipo_mascara == 'Batimento CDOE':
        campos_json = '"atividade":"","estacao":"","cdo":"","porta":"","gpon":""'
        foco = (
            "SA (no topo da tela, ex: SA-37285421), "
            "atividade (campo 'Atividade' na aba INFO, ex: INSTALAÇÃO BL FIBRA), "
            "estação/armário (campo 'Estação', 'EST' ou 'Central'), "
            "CDO/CDOE (campos 'CDO', 'CDOE', 'CDOPath' ou 'Caixa'), "
            "porta (campo 'Porta', 'Port' ou número após 'PTP.FO.O:'), "
            "GPON (campo 'Acesso GPON', ex: A0002VH1E)"
        )
    elif tipo_mascara == 'Pendência':
        campos_json = '"atividade":"","sa":"","documento":"","gpon":"","cliente":"","telefone":"","endereco":""'
        foco = (
            "SA (no topo da tela, ex: SA-37285421), "
            "atividade (campo 'Atividade' na aba INFO, ex: INSTALAÇÃO BL FIBRA), "
            "documento (campo 'Doc. Assoc.' na aba INFO), "
            "GPON (campo 'Acesso GPON' na aba Rede, ex: A0002VH1E), "
            "cliente (campo 'Cliente'), "
            "telefone (campo 'Contato 1' ou 'Contato Principal'), "
            "endereço completo (campo 'Endereço')"
        )
    elif tipo_mascara == 'Cancelamento':
        campos_json = '"sa":"","documento":"","telefone":"","cliente":""'
        foco = (
            "SA (no topo da tela, ex: SA-37285421), "
            "documento (campo 'Doc. Assoc.' na aba INFO), "
            "telefone (campo 'Contato 1' ou 'Contato Principal'), "
            "cliente (campo 'Cliente')"
        )
    elif tipo_mascara == 'Repasse':
        campos_json = '"sa":"","gpon":"","documento":"","cdo":"","porta":"","endereco":"","cliente":"","telefone":""'
        foco = (
            "SA (no topo da tela, ex: SA-37285421), "
            "GPON (campo 'Acesso GPON', ex: A0002VH1E), "
            "documento (campo 'Doc. Assoc.' na aba INFO), "
            "CDO (campo 'CDOPath', use apenas a parte antes de '.PTP', ex: CDOI-1220.2), "
            "porta (campo 'CDOPath', use o número após 'PTP.FO.O:', ex: 1), "
            "endereço completo (campo 'Endereço'), "
            "cliente (campo 'Cliente'), "
            "telefone (campo 'Contato 1' ou 'Contato Principal')"
        )
    else:
        campos_json = '"sa":"","gpon":"","cliente":"","documento":"","telefone":"","endereco":"","cdo":"","porta":"","estacao":"","atividade":""'
        foco = (
            "SA (no topo, ex: SA-37285421), GPON (campo 'Acesso GPON'), "
            "cliente (campo 'Cliente'), documento (campo 'Doc. Assoc.'), "
            "telefone (campo 'Contato 1'), endereço (campo 'Endereço'), "
            "CDO, porta, estação, atividade"
        )

    system = "Você é um OCR especializado em extrair dados de prints de sistemas de telecomunicações. Retorne APENAS JSON válido."

    user = (
        f"Extraia do print: {foco}.\n"
        f"Retorne exatamente este JSON preenchido com os valores encontrados (string vazia se não encontrar):\n"
        f"{{{campos_json}}}"
    )

    def normalizar(data: dict) -> dict:
        result = {}
        for k, v in data.items():
            if v is None or str(v).strip().lower() in ("null", "n/a", ""):
                result[k] = ""
            elif k in ['telefone', 'documento']:
                result[k] = str(v).strip()
            else:
                result[k] = str(v).strip().upper()
        return result

    def merge(base: dict, novo: dict) -> dict:
        for k, v in novo.items():
            if v and not base.get(k):
                base[k] = v
        return base

    # Processa cada imagem individualmente e agrega — cada aba do app vira 1 chamada separada.
    agregado = {}
    for i, img in enumerate(images):
        logger.info(f"[OCR] Processando imagem {i+1}/{len(images)}...")
        response_text = await _call_groq_vision(system, user, [img], json_mode=True)
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"[OCR] Imagem {i+1}: JSON inválido. Erro: {e}. Resposta: {response_text[:200]!r}")
            continue
        norm = normalizar(data)
        logger.info(f"[OCR] Imagem {i+1} extraiu: {norm}")
        agregado = merge(agregado, norm)

    logger.info(f"[OCR] Resultado agregado final: {agregado}")
    return agregado
