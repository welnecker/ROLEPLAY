# core/service.py
from __future__ import annotations
from typing import List, Dict
from re import error as ReError
import re

from .personas import get_persona
from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system  # regras duras só para Mary
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen

from .service_router import route_chat_strict

_FIRST_PERSON_HEUR = re.compile(r"(^|\n)\s*Mary\b", re.IGNORECASE)

def _montar_historico(usuario: str, history_boot: List[Dict[str, str]], limite_tokens: int = 120_000) -> List[Dict[str, str]]:
    docs = get_history_docs(usuario)
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

def _precisa_primeira_pessoa(txt: str) -> bool:
    return bool(_FIRST_PERSON_HEUR.search(txt))

def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    rewriter = [
        {"role": "system", "content":
         "Reescreva em 1ª pessoa (eu/minha), tom adulto, direto e envolvente. "
         "3–5 parágrafos; 1–2 frases por parágrafo; sem parênteses; sem diminutivos."},
        {"role": "user", "content": resposta},
    ]
    data, used_model, provider = route_chat_strict(model, {
        "model": model, "messages": rewriter, "max_tokens": 2048, "temperature": 0.5, "top_p": 0.9
    })
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

def gerar_resposta(usuario: str, prompt_usuario: str, model: str, character: str = "Mary") -> str:
    # 1) persona
    persona_system, history_boot = get_persona(character)

    # 2) local
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 3) histórico + estilo
    hist = _montar_historico(usuario, history_boot)
    local_atual = get_fact(usuario, "local_cena_atual", "") or ""
    estilo_msg = {
        "role": "system",
        "content": (
            "ESTILO: 1ª pessoa (eu). Tom adulto, natural e envolvente. "
            "3–5 parágrafos; 1–2 frases por parágrafo; frases curtas (4–12 palavras). "
            "Detalhes sensoriais pontuais. Manter coerência com LOCAL_ATUAL."
        ),
    }
    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": persona_system}, estilo_msg]
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

    # 4) chamada (STRICT provider; sem fallback oculto)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 5) reforço canônico (apenas Mary usa regra dura antiga)
    if character.strip().title() == "Mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 6) guarda de 1ª pessoa (heurística leve)
    if _precisa_primeira_pessoa(resposta):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 7) pós-processo
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 8) persistir
    save_interaction(usuario, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
