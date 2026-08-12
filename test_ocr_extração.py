# -*- coding: utf-8 -*-
"""Teste da extração OCR.space com textos reais dos logs de produção (2026-08-11, ticket SA-39574545)."""
import asyncio
import sys

import utils

# ParsedText real das 5 imagens (logs Render 2026-08-11) — \t e \r\n são os caracteres reais devolvidos pela API
TEXTS = [
    "64\t\r\nSA-39574545\t\r\nFTTH\tCAMINHO DA FIBRA\t\r\nAddressPath\t\r\nRUA BERNARDO REITER, 2510, CASA 1,\t\r\nPASSO MANSO, BLUMENAU - SC\t\r\n89046304\t\r\nLongitudePath\t\r\n-49.1511965\t\r\nLatitudePath\t\r\n-26.9172643\t\r\nCDOPath\t\r\nCDOE-1607-PTP.FO.0:6\t\r\nCDOPath\t\r\nCDOE-1607-PTP.FO.I:S8_1-S8_1/IN 1\t\r\nCEOSPath\t\r\nCEOS-16-PTP.FO.O:S8_2-S8_2/OUT 3\t\r\nCEOSPath\t\r\nCEOS-16-PTP.FO.I:S8_2-S8_2/IN 1\t\r\nAtividade\tRede\tAções\t\r\nO\t\r\n",
    "64\t\r\nSA-39574545\t\r\nFTTH\tCAMINHO DA FIBRA\t\r\nAcesso GPON\t\r\nA0001C05C\t\r\nID HSI\t\r\nH0001C0J7\t\r\nVel. de Upload\t\r\n350\t\r\nVel. de Down\t\r\n700\t\r\nPlano HSI\t\r\nNio Fibra 700 Mega\t\r\nQuantidade de Pontos\t\r\n0\t\r\nCaixa Postal?\t\r\nSim\t\r\nBina?\t\r\nSim\t\r\nChamada Espera?\t\r\nSim\t\r\nConferência?\t\r\nSim\t\r\nAtividade\tRede\tAções\t\r\n",
    "64\t\r\nSA-39574545\t\r\nINFO\tDETALHES\tCLIENTE\tNOTAS\t1\t\r\nIDContrato\t\r\n800U600000MmColIAF\t\r\nRazão Social\t\r\na0mN400000fOTsT\t\r\nEndereço\t\r\nRua Bernardo Reiter, 2546 CEP: 89046304 Passo\t\r\nManso, Blumenau - SC Complementos: null null\t\r\nSolicitante 3\t\r\nOLNEI ALEXANDRE ABEGG\t\r\nSolicitante\t\r\nOLNEI ALEXANDRE ABEGG\t\r\nCliente\t\r\nOLNEI ALEXANDRE ABEGG\t\r\nContato 1\t\r\n47991832481 %\t\r\nContato 2\t\r\n47991832481 L\t\r\nContato 3\t\r\n47991832481\t\r\nSolicitante 2\t\r\nOLNEI ALEXANDRE ABEGG\t\r\nAtividade\tRede\tAções\t\r\nO\t\r\n",
    "64\t\r\nSA-39574545\t\r\nINFO\tDETALHES\tCLIENTE\tNOTAS\t\r\nAgendamento\t\r\n11/08 13:00 a 11/08 18:00\t\r\nDoc. Assoc.\t\r\n86404416\t\r\nAcesso GPON\t\r\nA0001C05C\t\r\nTecnologia\t\r\nONT\t\r\nQuantidade de Pontos\t\r\n0\t\r\nAtividade\tRede\tAções\t\r\nO\t\r\n",
    "64\t\r\nSA-39574545\t\r\nINFO\tDETALHES\tCLIENTE\tNOTAS\t\r\nIDCompanhia\t\r\nNIO\t\r\nAtividade\t\r\nREPARO FIBRA\t\r\nDoc. Assoc.\t\r\n86404416\t\r\nEndereço\t\r\nRua Bernardo Reiter, 2546 CEP: 89046304 Passo\t\r\nManso, Blumenau - SC Complementos: null null\t\r\nTp. Terminal\t\r\nFTTH\t\r\nAgendamento\t\r\n11/08 13:00 a 11/08 18:00\t\r\nCliente\t\r\nOLNEI ALEXANDRE ABEGG\t\r\nReinc.\t\r\n0\t\r\nContato\t\r\nSim\t\r\nClasse do Produto\t\r\nWHITELABEL\t\r\nAtividade\tRede\tAções\t\r\nO\t\r\n",
]

_contador = 0


async def fake_ocr_space(img_bytes):
    global _contador
    idx = _contador
    _contador += 1
    return TEXTS[idx]


async def fake_groq_vazio(system_prompt, user_prompt, images, json_mode=True, retries=2, timeout_seconds=30):
    return "{}"


async def fake_groq_parcial(system_prompt, user_prompt, images, json_mode=True, retries=2, timeout_seconds=30):
    # Simula Groq funcionando: devolve sa + gpon no primeiro lote
    return '{"sa": "SA-39574545", "gpon": "A0001C05C", "cliente": "", "telefone": "", "endereco": "", "cdo": "", "porta": "", "documento": ""}'


def checar(nome, obtido, esperado):
    ok = obtido == esperado
    print(f"  [{'OK' if ok else 'FALHOU'}] {nome}: esperado={esperado!r} obtido={obtido!r}")
    return ok


async def main():
    global _contador
    falhas = []

    # ---- Teste 1: extrair_dados_ocr_space direto (campos brutos, sem normalização) ----
    print("TESTE 1 — extrair_dados_ocr_space (Repasse):")
    utils._call_ocr_space = fake_ocr_space
    _contador = 0
    r = await utils.extrair_dados_ocr_space([b'x'] * 5, 'Repasse')
    for k, v in {
        'sa': '39574545',
        'gpon': 'A0001C05C',
        'documento': '86404416',
        'cdo': 'CDOE-1607',
        'porta': 'S8_2',
        'cliente': 'OLNEI ALEXANDRE ABEGG',
        'telefone': '47991832481',
        'endereco': 'RUA BERNARDO REITER, 2546 CEP: 89046304 PASSO MANSO, BLUMENAU - SC',
    }.items():
        if not checar(k, r.get(k), v):
            falhas.append(k)

    # ---- Teste 2: fluxo completo com Groq vazio ({} → bail → fallback OCR.space) ----
    print("TESTE 2 — extrair_dados_completos com Groq devolvendo {} (deve cair no fallback):")
    utils._call_groq_vision = fake_groq_vazio
    _contador = 0
    r2 = await utils.extrair_dados_completos([b'x'] * 5, 'Repasse')
    for k, v in {
        'sa': 'SA-39574545',  # normalização final adiciona o prefixo
        'gpon': 'A0001C05C',
        'documento': '86404416',
        'cdo': 'CDOE-1607',
        'porta': 'S8_2',
        'cliente': 'OLNEI ALEXANDRE ABEGG',
        'telefone': '47991832481',
        'endereco': 'RUA BERNARDO REITER, 2546 CEP: 89046304 PASSO MANSO, BLUMENAU - SC',
    }.items():
        if not checar(k, r2.get(k), v):
            falhas.append(k)

    # ---- Teste 3: Groq funcionando — não deve cair no fallback e preserva campos do Groq ----
    print("TESTE 3 — extrair_dados_completos com Groq OK (não deve chamar OCR.space):")
    utils._call_groq_vision = fake_groq_parcial

    async def fake_ocr_nao_deve_ser_chamado(img_bytes):
        falhas.append("OCR.space foi chamado mesmo com Groq funcionando!")
        return ""

    utils._call_ocr_space = fake_ocr_nao_deve_ser_chamado
    r3 = await utils.extrair_dados_completos([b'x'] * 5, 'Repasse')
    checar('sa (Groq)', r3.get('sa'), 'SA-39574545')
    checar('gpon (Groq)', r3.get('gpon'), 'A0001C05C')
    checar('cliente (vazio, Groq não preencheu)', r3.get('cliente', ''), '')

    if falhas:
        print("\nTESTE FALHOU:", falhas)
        sys.exit(1)
    print("\nTODOS OS TESTES PASSARAM ✓")


asyncio.run(main())
