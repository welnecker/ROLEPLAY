# core/service.py
from typing import List, Dict
from re import error as ReError
import re

from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import (
    save_interaction, get_history_docs, set_fact, get_fact,
    get_facts, last_event
)
from .rules import violou_mary, reforco_system  # strip_bordoes é opcional aqui
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .service_router import route_chat_strict  # roteamento sem fallback oculto

# Heurística simples: evitar saída em 3ª pessoa “Mary …” abrindo parágrafo
_FIRST_PERSON_FLAG = re.compile(r"(^|\n)\s*Mary\b", re.IGNORECASE)


def _memory_context(usuario: str) -> str:
    f = get_facts(usuario) or {}
    blocos = []
    if "parceiro_atual" in f:
        blocos.append(f"RELACIONAMENTO: parceiro_atual={f['parceiro_atual']}")
    if "virgem" in f:
        blocos.append(f"STATUS ÍNTIMO: virgem={bool(f['virgem'])}")
    if "primeiro_encontro" in f:
        blocos.append(f"PRIMEIRO_ENCONTRO: {f['primeiro_encontro']}")

    ev = last_event(usuario, "primeira_vez")
    if ev:
        dt = ev.get("ts")
        quando = dt.strftime("%Y-%m-%d %H:%M") if hasattr(dt, "strftime") else str(dt)
        blocos.append(f"EVENTO_CANÔNICO: primeira_vez em {quando} @ {ev.get('local') or '—'}")

    return "\n".join(blocos).strip()


def _montar_historico(usuario: str, limite_tokens: int = 120_000) -> List[Dict[str, str]]:
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


def _pos_processar_seguro(texto: str, max_frases_por_par: int = 2) -> str:
    """Sanitiza barras e garante parágrafos 1–2 frases, mantendo espaço para detalhes sensoriais."""
    if not texto:
        return texto
    s = texto.replace("\\", "\\\\")
    try:
        s = strip_metacena(s)
        # (opcional) se estiver usando strip_bordoes do rules.py, aplique aqui:
        # from .rules import strip_bordoes
        # s = strip_bordoes(s)
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        s = s.replace("\\\\", "\\")
        # garante parágrafos em Markdown
        s = re.sub(r"\n(?!\n)", "\n\n", s.strip())
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s
    except ReError:
        return texto


def _precisa_primeira_pessoa(txt: str) -> bool:
    return bool(_FIRST_PERSON_FLAG.search(txt))


def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    """Reescreve a saída em 1ª pessoa (mesmo provedor/modelo)."""
    rewriter = [
        {
            "role": "system",
            "content": (
                "Reescreva o texto a seguir em 1ª pessoa (eu/minha), tom adulto,"
                " direto e envolvente. 3–5 parágrafos; 1–2 frases por parágrafo;"
                " sem parênteses; sem diminutivos; sem infantilização."
            ),
        },
        {"role": "user", "content": resposta},
    ]
    data, used_model, provider = route_chat_strict(
        model,
        {"model": model, "messages": rewriter, "max_tokens": 2048, "temperature": 0.5, "top_p": 0.9},
    )
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta


def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    # 1) Inferir e fixar local (se detectado)
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Histórico + estilo + memória
    hist = _montar_historico(usuario)
    local_atual = get_fact(usuario, "local_cena_atual", "") or ""
    memoria = _memory_context(usuario)
    memoria_msg = [{"role": "system", "content": "MEMÓRIA:\n" + memoria}] if memoria else []

    estilo_msg = {
        "role": "system",
        "content": (
            "ESTILO: 1ª pessoa (eu). Tom adulto, seguro e sensorial, sem exagero. "
            "3–5 parágrafos; 1–2 frases por parágrafo; frases curtas (4–12 palavras). "
            "Permita 0–1 detalhe sensorial marcante por parágrafo (ex.: meus cabelos negros volumosos, "
            "pele aquecida ao toque, perfume discreto, respiração perto da orelha), somente quando fizer sentido. "
            "Sem parênteses de metacena. Sem diminutivos/infantilização. "
            "Coerência estrita com LOCAL_ATUAL e com a memória canônica."
        ),
    }

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": PERSONA_MARY}, estilo_msg]
        + memoria_msg
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

    # 3) Chamada (STRICT — Together/OpenRouter sem fallback oculto)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Reforço canônico, se necessário
    if violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) 1ª pessoa (se detectar 3ª pessoa “Mary …”)
    if _precisa_primeira_pessoa(resposta):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) Pós-processo: garantir parágrafos e preservar sensualidade
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 7) Persistir
    save_interaction(usuario, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
