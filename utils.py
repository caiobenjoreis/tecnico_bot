from datetime import datetime
from config import TZ, PONTOS_SERVICO, TABELA_FAIXAS, USE_GROQ, GROQ_API_KEY, GROQ_MODEL
import base64
import json
import re
import logging
from typing import List

def is_valid_sa(sa: str) -> bool:
    try:
        return bool(re.fullmatch(r"SA-\d{5,}", sa or ""))
    except Exception:
        return False

def is_valid_gpon(gpon: str) -> bool:
    try:
        return bool(re.fullmatch(r"[A-Z0-9]{6,16}", gpon or ""))
    except Exception:
        return False

def is_valid_serial(s: str) -> bool:
    try:
        if not s: return False
        if s.upper().startswith("SA-"): return False
        return bool(re.fullmatch(r"[A-Z0-9]{8,20}", s))
    except Exception:
        return False
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
    retries: int = 2
) -> str:
    """
    Função centralizada para chamar a API de visão da Groq com retry e fallback de modelos.
    """
    if not USE_GROQ or not GROQ_API_KEY or Groq is None:
        return "{}" if json_mode else ""

    client = Groq(api_key=GROQ_API_KEY)
    
    # Modelos em ordem de preferência
    models = [
        GROQ_MODEL or "llama-3.2-90b-vision-preview",
        "llama-3.2-11b-vision-preview",
        "meta-llama/llama-3.2-90b-vision-preview" 
    ]
    
    # Preparar conteúdo do usuário
    content = [{"type": "text", "text": user_prompt}]
    for img in images:
        b64 = base64.b64encode(img).decode("ascii")
        content.append({
            "type": "image_url", 
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    last_error = None

    for attempt in range(retries + 1):
        for model in models:
            try:
                kwargs = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": content}
                    ],
                    "temperature": 0.1, # Leve temperatura para criatividade controlada se necessário, mas 0 é melhor para OCR estrito
                    "max_completion_tokens": 1024,
                }
                
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                
                resp = client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ("{}" if json_mode else "")
                
            except Exception as e:
                last_error = e
                logging.warning(f"Groq vision falhou (tentativa {attempt+1}, modelo {model}): {e}")
                continue # Tenta próximo modelo
        
        # Se falhou com todos os modelos, espera um pouco antes do próximo retry (se houver)
        # Mas como já iteramos modelos, talvez não precise de sleep explícito, apenas continue o loop de retries
        pass

    logging.error(f"Todas as tentativas de OCR falharam. Último erro: {last_error}")
    return "{}" if json_mode else ""


async def extrair_campos_por_imagem(image_bytes: bytes) -> dict:
    """
    Extrai SA, GPON, Serial Modem e Mesh de uma imagem.
    """
    system = (
        "Você é um assistente especializado em OCR de dados técnicos de telecomunicações. "
        "Sua tarefa é extrair EXATAMENTE os dados solicitados de prints de tela de sistemas técnicos. "
        "Retorne APENAS um JSON válido."
    )
    
    user = (
        "Analise a imagem e extraia os seguintes dados:\n"
        "1. SA (Service Order): Formato geralmente numérico ou SA-números.\n"
        "2. GPON (Acesso): Código alfanumérico (ex: ABCD123456).\n"
        "3. Serial do Modem (ONT/ONU): Código alfanumérico longo (ex: ZTEGC8..., ALCLB...). Procure por 'Serial', 'S/N', 'SN', 'ONT ID'.\n"
        "4. Seriais Mesh: Códigos alfanuméricos de extensores/roteadores mesh. Retorne uma lista.\n\n"
        "Regras:\n"
        "- Ignore dados que não sejam claramente identificáveis.\n"
        "- Converta tudo para MAIÚSCULAS.\n"
        "- Remova espaços em branco extras.\n"
        "- Se não encontrar, retorne null.\n\n"
        "Retorne o JSON no seguinte formato:\n"
        "{\n"
        '  "sa": "...",\n'
        '  "gpon": "...",\n'
        '  "serial_do_modem": "...",\n'
        '  "mesh": ["..."]\n'
        "}"
    )

    # Tenta extração via JSON mode
    response_text = await _call_groq_vision(system, user, [image_bytes], json_mode=True)
    
    data = {}
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        # Fallback: tentar extrair JSON de texto sujo se o modo JSON falhar silenciosamente
        try:
            match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
        except:
            pass

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
    prompts = {
        "sa": "Extraia apenas o número da SA (Service Order). Retorne JSON: {\"sa\": \"valor\"}",
        "gpon": "Extraia apenas o código GPON/Acesso. Retorne JSON: {\"gpon\": \"valor\"}",
        "serial_do_modem": "Extraia apenas o Serial Number (S/N) do modem/ONT. Retorne JSON: {\"serial_do_modem\": \"valor\"}",
        "mesh": "Extraia apenas os Seriais de equipamentos Mesh. Retorne JSON: {\"mesh\": [\"valor1\", \"valor2\"]}"
    }
    
    user_prompt = prompts.get(campo, f"Extraia o campo {campo}. Retorne JSON.")
    system_prompt = "Você é um especialista em OCR. Extraia apenas o dado solicitado. Se não encontrar, retorne null no JSON."

    response_text = await _call_groq_vision(system_prompt, user_prompt, images, json_mode=True)
    
    try:
        data = json.loads(response_text)
    except:
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
