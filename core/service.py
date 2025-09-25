# core/service.py
from typing import List, Dict
from re import error as ReError
import re

from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen

# Roteador estrito (Together vs OpenRouter) — sem fallback silencioso
from .service_router import route_chat_strict

def _montar_historico(usuario_key: str, history_boot: List[Dict[str, str]], limite_tokens: int = 120_000) -> List[Dict[str, str]]:
    docs = get_history_docs(usuario_key)
    if not docs:
        return history_boot[:]
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
    return list(reversed(out)) if out else history_boot[:]

def _pos_processar_seguro(texto: str, max_frases_por_par: int = 2) -> str:
    if not texto:
        return texto
    s = texto.replace("\\", "\\\\")
    try:
        s = strip_metacena(s)
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        return s.replace("\\\\", "\\")
    except ReError:
        return texto

def gerar_resposta(usuario: str, prompt_usuario: str, model: str, character: str = "Mary") -> str:
    """
    Compat total com Mary: para Mary usamos o mesmo 'usuario' de antes.
    Para outras personagens, usamos 'usuario::<personagem>'.
    """
    char = (character or "Mary").strip()
    usuario_key = usuario if char.lower() == "mary" else f"{usuario}::{char.lower()}"

    # Persona e histórico base (Mary padrão)
    persona_text = PERSONA_MARY
    history_boot = HISTORY_BOOT

    # 1) Inferir e fixar local
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario_key, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Histórico + estilo + local
    hist = _montar_historico(usuario_key, history_boot)
    local_atual = get_fact(usuario_key, "local_cena_atual", "") or ""

    estilo_msg = {
        "role": "system",
        "content": (
            "ESTILO: 1ª pessoa (eu). Tom adulto, direto e envolvente. "
            "3–5 parágrafos; 1–2 frases por parágrafo. Frases curtas (4–12 palavras). "
            "Sem parênteses/metacena. Sem diminutivos/infantilização. "
            "Mantenha coerência estrita com o LOCAL_ATUAL."
        ),
    }

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": persona_text}, estilo_msg]
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

    # 3) chamada (STRICT, sem fallback)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) reforço canônico (Mary)
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) pós-processo (curto, sem metacena)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 6) persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
