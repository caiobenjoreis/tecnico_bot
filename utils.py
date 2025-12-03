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

async def extrair_campos_por_imagem(image_bytes: bytes) -> dict:
    if not USE_GROQ or not GROQ_API_KEY or Groq is None:
        return {}
    b64 = base64.b64encode(image_bytes).decode("ascii")
    client = Groq(api_key=GROQ_API_KEY)
    system = (
        "Você extrai dados de prints técnicos. Retorne somente JSON válido com as chaves: "
        "sa, gpon, serial_do_modem, mesh. Use maiúsculas. Para mesh retorne lista. "
        "Se não houver valor, use null (ou [] para mesh)."
    )
    user_text = (
        "Extraia SA, Acesso GPON, Número de série da ONT (modem) e seriais de equipamentos mesh. "
        "Retorne exatamente no esquema solicitado."
    )
    content = [
        {"type": "text", "text": user_text},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
    ]
    models = [
        GROQ_MODEL or "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "llama-3.2-90b-vision-preview",
    ]
    data = {}
    txt_last = ""
    for m in models:
        try:
            resp = client.chat.completions.create(
                model=m,
                temperature=0,
                response_format={"type": "json_object"},
                max_completion_tokens=512,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
            )
            txt = resp.choices[0].message.content if resp and resp.choices else "{}"
            txt_last = txt or ""
            try:
                data = json.loads(txt)
            except Exception:
                data = {}
            break
        except Exception as e:
            logging.error(f"Groq vision falhou com modelo {m}: {e}")
            continue
    if not data:
        text = txt_last
        sa_match = re.search(r"SA[-\s:]?\s*(\d{5,})", text, re.I)
        gpon_match = re.search(r"Acesso\s*GPON\s*[:]?\s*([A-Z0-9]{6,16})", text, re.I)
        serial_match = re.search(r"(Número\s*de\s*série|Serial)\s*[:]?\s*([A-Z0-9]{8,20})", text, re.I)
        mesh_matches = re.findall(r"MESH[^\n]*?([A-Z0-9]{8,20})", text, re.I)
        sa = (f"SA-{sa_match.group(1)}" if sa_match else None)
        gpon = (gpon_match.group(1).upper() if gpon_match else None)
        serial = (serial_match.group(2).upper() if serial_match else None)
        sa = sa if is_valid_sa(sa) else None
        gpon = gpon if is_valid_gpon(gpon) else None
        serial = serial if is_valid_serial(serial) else None
        mesh = [m.upper() for m in mesh_matches if is_valid_serial(m) and (not gpon or m.upper() != gpon)]
        return {"sa": sa, "gpon": gpon, "serial_do_modem": serial, "mesh": mesh}
    def pick(d, keys):
        for k in keys:
            v = d.get(k)
            if v:
                return v
        return None
    sa_val = pick(data, ["sa", "sa_number", "service_order", "ordem_de_servico"]) or ""
    gpon_val = pick(data, ["gpon", "acesso_gpon", "id_gpon"]) or ""
    serial_val = pick(data, ["serial_do_modem", "serial_modem", "numero_de_serie", "ont_serial"]) or ""
    mesh_raw = pick(data, ["mesh", "mesh_list", "mesh_serials"]) or []
    sa = str(sa_val).strip().upper() or None
    gpon = str(gpon_val).strip().upper() or None
    serial = str(serial_val).strip().upper() or None
    if isinstance(mesh_raw, str):
        mesh_list = [mesh_raw]
    else:
        mesh_list = list(mesh_raw)
    mesh = []
    for m in mesh_list:
        s = str(m).strip().upper()
        if not s:
            continue
        if not is_valid_serial(s):
            continue
        if gpon and s == gpon:
            continue
        mesh.append(s)
    if sa and re.fullmatch(r"\d{5,}", sa):
        sa = f"SA-{sa}"
    sa = sa if is_valid_sa(sa) else None
    gpon = gpon if is_valid_gpon(gpon) else None
    serial = serial if is_valid_serial(serial) else None
    return {
        "sa": sa,
        "gpon": gpon,
        "serial_do_modem": serial,
        "mesh": mesh,
    }

async def extrair_campos_por_imagens(images: list) -> dict:
    agg = {"sa": None, "gpon": None, "serial_do_modem": None, "mesh": []}
    for img in images:
        try:
            d = await extrair_campos_por_imagem(img)
        except Exception:
            d = {}
        for k in ["sa", "gpon", "serial_do_modem"]:
            v = d.get(k)
            if not v: continue
            if k == "sa" and not is_valid_sa(v):
                continue
            if k == "gpon" and not is_valid_gpon(v):
                continue
            if k == "serial_do_modem" and not is_valid_serial(v):
                continue
            if not agg[k]:
                agg[k] = v
        ms = d.get("mesh") or []
        for m in ms:
            if not is_valid_serial(m):
                continue
            if m not in agg["mesh"]:
                agg["mesh"].append(m)
    return agg

async def extrair_campo_especifico(images: List[bytes], campo: str) -> dict:
    if not USE_GROQ or not GROQ_API_KEY or Groq is None:
        return {}
    client = Groq(api_key=GROQ_API_KEY)
    models = [
        GROQ_MODEL or "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "llama-3.2-90b-vision-preview",
    ]
    prompt_json = {
        "sa": "Retorne apenas JSON {\"sa\": \"SA-<digitos>\"}.",
        "gpon": "Retorne apenas JSON {\"gpon\": \"<alfa-num 6-16 maiusculas>\"}.",
        "serial_do_modem": "Retorne apenas JSON {\"serial_do_modem\": \"<alfa-num 8-20 maiusculas>\"}.",
        "mesh": "Retorne apenas JSON {\"mesh\": [\"<seriais mesh>\"]}.",
    }
    prompt_text = {
        "sa": "Retorne apenas SA-<digitos> encontrado na imagem.",
        "gpon": "Retorne apenas o valor do Acesso GPON (6-16 A-Z0-9).",
        "serial_do_modem": "Procure 'Número de série', 'SÉRIE' ou 'Serial' e retorne apenas o valor (8-20 A-Z0-9).",
        "mesh": "Retorne apenas os seriais do mesh (8-20 A-Z0-9), um por linha.",
    }
    key = campo
    txt_last = ""
    for m in models:
        try:
            contents = [{"type": "text", "text": prompt_json.get(campo, "Retorne JSON do campo solicitado.")}]
            for img in images:
                b64 = base64.b64encode(img).decode("ascii")
                contents.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            resp = client.chat.completions.create(
                model=m,
                temperature=0,
                response_format={"type": "json_object"},
                max_completion_tokens=256,
                messages=[{"role": "user", "content": contents}],
            )
            txt = resp.choices[0].message.content if resp and resp.choices else "{}"
            txt_last = txt or ""
            data = {}
            try:
                data = json.loads(txt)
            except Exception:
                data = {}
            if campo == "mesh":
                vals = [str(x).strip().upper() for x in (data.get("mesh") or [])]
                vals = [v for v in vals if is_valid_serial(v)]
                if vals:
                    return {"mesh": vals}
            else:
                val = str(data.get(key) or "").strip().upper() or None
                ok = False
                if campo == "sa":
                    ok = bool(val and is_valid_sa(val))
                elif campo == "gpon":
                    ok = bool(val and is_valid_gpon(val))
                else:
                    ok = bool(val and is_valid_serial(val))
                if ok:
                    return {key: val}
            # Segundo intento em modo texto
            contents2 = [{"type": "text", "text": prompt_text.get(campo, "Retorne apenas o valor solicitado.")}]
            for img in images:
                b64 = base64.b64encode(img).decode("ascii")
                contents2.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
            resp2 = client.chat.completions.create(
                model=m,
                temperature=0,
                max_completion_tokens=256,
                messages=[{"role": "user", "content": contents2}],
            )
            t2 = resp2.choices[0].message.content if resp2 and resp2.choices else ""
            txt_last = t2 or txt_last
            t = txt_last or ""
            if campo == "sa":
                m_sa = re.search(r"SA[-\s:]?\s*(\d{5,})", t, re.I)
                if m_sa:
                    return {"sa": f"SA-{m_sa.group(1)}"}
            elif campo == "gpon":
                m_gp = re.search(r"GPON\s*[:]?\s*([A-Z0-9]{6,16})|\b([A-Z0-9]{6,16})\b", t, re.I)
                gp = (m_gp.group(1) or m_gp.group(2)) if m_gp else None
                gp = gp.upper() if gp else None
                if gp and is_valid_gpon(gp):
                    return {"gpon": gp}
            elif campo == "serial_do_modem":
                m_se = re.search(r"(Número\s*de\s*série|Serial|SÉRIE)\s*[:]?\s*([A-Z0-9]{8,20})", t, re.I)
                se = m_se.group(2).upper() if m_se else None
                if se and is_valid_serial(se):
                    return {"serial_do_modem": se}
            elif campo == "mesh":
                ms = re.findall(r"([A-Z0-9]{8,20})", t, re.I)
                ms = [x.upper() for x in ms if is_valid_serial(x)]
                if ms:
                    return {"mesh": ms}
        except Exception as e:
            logging.error(f"Groq vision targeted falhou com modelo {m}: {e}")
            continue
    return {}
