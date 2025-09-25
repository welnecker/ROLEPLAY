from typing import List, Dict
from re import error as ReError
import re

from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import (
    save_interaction,
    get_history_docs,
    set_fact,
    get_fact,
    get_facts,
    last_event,
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen

# Roteador de provedor (STRICT: sem fallback automático)
from .service_router import route_chat_strict

# Heurística para detectar 3ª pessoa “Mary …” e disparar reescrita em 1ª pessoa
_FIRST_PERSON_FLAG = re.compile(r"(^|\n)\s*Mary\b", re.IGNORECASE)


def _memory_context(usuario: str) -> str:
    """
    Constrói um bloco textual com fatos/eventos canônicos para guiar o modelo.
    """
    f = get_facts(usuario) or {}
    blocos: List[str] = []

    if f.get("parceiro_atual"):
        blocos.append(f"RELACIONAMENTO: parceiro_atual={f['parceiro_atual']}")
    if "virgem" in f:
        blocos.append(f"STATUS ÍNTIMO: virgem={bool(f['virgem'])}")
    if f.get("primeiro_encontro"):
        blocos.append(f"PRIMEIRO_ENCONTRO: {f['primeiro_encontro']}")

    ev = last_event(usuario, "primeira_vez")
    if ev:
        dt = ev.get("ts")
        quando = dt.strftime("%Y-%m-%d %H:%M") if hasattr(dt, "strftime") else str(dt)
        blocos.append(f"EVENTO_CANÔNICO: primeira_vez em {quando} @ {ev.get('local') or '—'}")

    return "\n".join(blocos).strip()


def _parceiro_system_msg(usuario: str) -> Dict[str, str]:
    """
    Injeta regra de continuidade de relacionamento para evitar 'amnésia' do parceiro.
    Trata 'você' como o parceiro salvo; responde corretamente 'quem sou eu?'.
    """
    parceiro = get_fact(usuario, "parceiro_atual", "Janio") or "Janio"
    return {
        "role": "system",
        "content": (
            f"RELACIONAMENTO ATUAL: {parceiro}.\n"
            f"- Trate 'você' como {parceiro}. Não diga que não reconhece {parceiro}.\n"
            f"- Se o usuário perguntar 'quem sou eu?', responda claramente: '{parceiro}', de forma calorosa e natural.\n"
            "- Mary não trai; mantém continuidade com o parceiro salvo."
        ),
    }


def _montar_historico(usuario: str, limite_tokens: int = 120_000) -> List[Dict[str, str]]:
    """
    Retorna pares alternados user->assistant em ordem cronológica,
    respeitando limite de tokens.
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


def _pos_processar_seguro(texto: str, max_frases_por_par: int = 2) -> str:
    """
    Pós-processo robusto: remove metacena, formata parágrafos curtos
    e blinda contra escapes inválidos (\\c, etc.).
    """
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
    # heurística leve: evita 3ª pessoa “Mary …”
    return bool(_FIRST_PERSON_FLAG.search(txt))


def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    """
    Reescreve a saída em 1ª pessoa, usando o MESMO provedor/modelo (sem fallback).
    """
    rewriter = [
        {"role": "system", "content": (
            "Reescreva o texto A SEGUIR em 1ª pessoa (eu/minha), tom adulto,"
            " direto e envolvente. 3–5 parágrafos; 1–2 frases por parágrafo;"
            " sem parênteses; sem diminutivos; sem infantilização."
        )},
        {"role": "user", "content": resposta}
    ]
    data, _, _ = route_chat_strict(model, {
        "model": model,
        "messages": rewriter,
        "max_tokens": 2048,
        "temperature": 0.5,
        "top_p": 0.9,
    })
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta


def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    """
    Gera a resposta via provedor roteado, com memória canônica injetada
    e reforço explícito de relacionamento para evitar 'não reconhecer' o Janio.
    """
    # 1) Inferir e fixar local, se detectado
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Histórico + contexto
    hist = _montar_historico(usuario)
    local_atual = get_fact(usuario, "local_cena_atual", "") or ""
    mem_ctx = _memory_context(usuario)

    estilo_msg = {
        "role": "system",
        "content": (
            "ESTILO: 1ª pessoa (eu). Tom adulto, direto, envolvente. "
            "3–5 parágrafos; 1–2 frases por parágrafo. "
            "Frases curtas (4–12 palavras). Sem parênteses de metacena. "
            "Sem diminutivos; sem infantilização. Coerência estrita com LOCAL_ATUAL."
        ),
    }

    memoria_msg = [{"role": "system", "content": f"MEMÓRIA CANÔNICA:\n{mem_ctx}"}] if mem_ctx else []

    messages: List[Dict[str, str]] = (
        [
            {"role": "system", "content": PERSONA_MARY},
            _parceiro_system_msg(usuario),
            estilo_msg,
        ]
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

    # 3) Chamada ao provedor (STRICT; sem fallback automático)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Reforço canônico se necessário
    if violou_mary(resposta):
        data2, _, _ = route_chat_strict(
            model,
            {**payload, "messages": [messages[0], reforco_system()] + messages[1:]}
        )
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Guarda de 1ª pessoa (reescrita leve) se o modelo escorregar pra 3ª
    if _precisa_primeira_pessoa(resposta):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) Pós-processo (parágrafos curtos, sem metacena)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 7) Persistir
    save_interaction(usuario, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
