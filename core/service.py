# core/service.py
import re
from re import error as ReError
from typing import List, Dict
from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .openrouter import chat
from .tokens import toklen

def _montar_historico(usuario: str, limite_tokens: int = 120_000) -> List[Dict[str, str]]:
    docs = get_history_docs(usuario)
    if not docs: return HISTORY_BOOT[:]
    total, out = 0, []
    for d in reversed(docs):
        u = d.get("mensagem_usuario") or ""
        a = d.get("resposta_mary") or ""
        t = toklen(u) + toklen(a)
        if total + t > limite_tokens: break
        out.append({"role": "user", "content": u})
        out.append({"role": "assistant", "content": a})
        total += t
    return list(reversed(out)) if out else HISTORY_BOOT[:]

def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    # 1) Inferir e fixar local
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Montar mensagens
    hist = _montar_historico(usuario)
    local_atual = get_fact(usuario, "local_cena_atual", "")
    estilo = {"role": "system", "content":
        ("ESTILO: adulto e direto; parágrafos curtos; desejo com classe; "
         "coerência estrita com o local atual.")}

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": PERSONA_MARY}, estilo]
        + hist
        + [{"role": "user", "content": f"LOCAL_ATUAL: {local_atual}\n\n{prompt_usuario}"}]
    )

    # 3) Chamada
    payload = {"model": model, "messages": messages, "max_tokens": 2048, "temperature": 0.6, "top_p": 0.9}
    data = chat(payload)
    resposta = data["choices"][0]["message"]["content"]

    # 4) Pós-processamento com fallback contra '\c' e afins
    try:
        resposta = strip_metacena(resposta)
        resposta = formatar_roleplay_profissional(resposta, max_frases_por_par=3)
    except ReError:
        # Se o modelo devolveu sequências tipo "\c" que explodem no re,
        # neutralizamos as barras e tentamos novamente.
        safe = resposta.replace("\\", "\\\\")
        try:
            safe = strip_metacena(safe)
            safe = formatar_roleplay_profissional(safe, max_frases_por_par=3)
            resposta = safe
        except ReError:
            # Se ainda assim falhar, devolve sem formatar (melhor que quebrar)
            pass

    # 5) Coerência
    if violou_mary(resposta):
        data2 = chat({**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = data2["choices"][0]["message"]["content"]
        # repete ajuste leve, sem quebrar se vier lixo novamente
        try:
            resposta = strip_metacena(resposta)
            resposta = formatar_roleplay_profissional(resposta, max_frases_por_par=3)
        except ReError:
            pass

    save_interaction(usuario, prompt_usuario, resposta, model)
    return resposta

    try:
    resposta = strip_metacena(resposta)
    resposta = formatar_roleplay_profissional(resposta, max_frases_por_par=3)
except ReError:
    # Se vier lixo com barras, neutraliza e tenta de novo
    safe = (resposta or "").replace("\\", "\\\\")
    try:
        safe = strip_metacena(safe)
        safe = formatar_roleplay_profissional(safe, max_frases_por_par=3)
        resposta = safe
    except ReError:
        # No pior caso, devolve sem pós-processar (não quebra o app)
        pass

