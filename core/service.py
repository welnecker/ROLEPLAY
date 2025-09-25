# core/service.py
from typing import List, Dict
from re import error as ReError

from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .openrouter import chat
from .tokens import toklen


def _montar_historico(usuario: str, limite_tokens: int = 120_000) -> List[Dict[str, str]]:
    """
    Constrói o histórico user/assistant respeitando o limite de tokens.
    Retorna HISTORY_BOOT se não houver histórico.
    """
    docs = get_history_docs(usuario)
    if not docs:
        return HISTORY_BOOT[:]

    total = 0
    out: List[Dict[str, str]] = []
    for d in reversed(docs):
        u = d.get("mensagem_usuario") or ""
        a = d.get("resposta_mary") or ""
        t = toklen(u) + toklen(a)
        if total + t > limite_tokens:
            break
        out.append({"role": "user", "content": u})
        out.append({"role": "assistant", "content": a})
        total += t

    return list(reversed(out)) if out else HISTORY_BOOT[:]


def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    """
    Gera a resposta via OpenRouter, aplica pós-processamentos seguros,
    formata em parágrafos curtos e persiste a interação.
    """
    # 1) Inferir e fixar local, se detectado
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Histórico + estilo + contexto de local
    hist = _montar_historico(usuario)
    local_atual = get_fact(usuario, "local_cena_atual", "") or ""

    estilo_msg = {
        "role": "system",
        "content": (
            "ESTILO: adulto e direto; parágrafos curtos (até 3 frases); "
            "desejo com classe; manter coerência estrita com o LOCAL_ATUAL."
        ),
    }

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": PERSONA_MARY}, estilo_msg]
        + hist
        + [{"role": "user", "content": f"LOCAL_ATUAL: {local_atual}\n\n{prompt_usuario}"}]
    )

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.6,
        "top_p": 0.9,
    }

    # 3) Chamada ao provedor
    data = chat(payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Retry leve se violar regras duras (cabelo/curso/mãe etc.)
    if violou_mary(resposta):
        payload_retry = {**payload, "messages": [messages[0], reforco_system()] + messages[1:]}
        data2 = chat(payload_retry)
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Pós-processamento SEGURO contra escapes inválidos (\c, \x, etc.)
    try:
        resposta = strip_metacena(resposta)
        resposta = formatar_roleplay_profissional(resposta, max_frases_por_par=3)
    except ReError:
        # Neutraliza barras e tenta novamente
        safe = (resposta or "").replace("\\", "\\\\")
        try:
            safe = strip_metacena(safe)
            safe = formatar_roleplay_profissional(safe, max_frases_por_par=3)
            resposta = safe
        except ReError:
            # No pior caso, retorna sem pós-processo
            pass

    # 6) Persistir
    save_interaction(usuario, prompt_usuario, resposta, model)

    return resposta
