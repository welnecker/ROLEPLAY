from typing import List, Dict
from re import error as ReError
import re

from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import (
    save_interaction,
    get_history_docs,
    set_fact,
    get_fact,
    last_event,
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen

# nsfw_enabled é opcional; se não existir, tratamos como False
try:
    from .nsfw import nsfw_enabled
except Exception:
    def nsfw_enabled(_user: str) -> bool:
        return False

# STRICT router (Together vs OpenRouter) — sem fallback automático
from .service_router import route_chat_strict

# Heurística para detectar terceira pessoa “Mary …”
_FIRST_PERSON_FLAG = re.compile(r"(^|\n)\s*Mary\b", re.IGNORECASE)


# ---------------------- Memória / Contexto ----------------------
def _get_facts_safe(usuario: str) -> Dict[str, str]:
    """Carrega todos os fatos do usuário de forma segura."""
    try:
        # evitar dependência circular: buscar tudo de uma vez
        from .repositories import _state  # type: ignore
        d = _state().find_one({"usuario": usuario}, {"fatos": 1}) or {}
        return d.get("fatos", {}) or {}
    except Exception:
        return {}

def _memory_context(usuario: str) -> str:
    f = _get_facts_safe(usuario)
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
    parceiro = get_fact(usuario, "parceiro_atual", "Janio") or "Janio"
    return {
        "role": "system",
        "content": (
            f"RELACIONAMENTO ATUAL: {parceiro}.\n"
            f"- Trate 'você' como {parceiro}. Não diga que não reconhece {parceiro}.\n"
            f"- Se o usuário perguntar 'quem sou eu?', responda com clareza e carinho: '{parceiro}'.\n"
            "- Mary mantém continuidade com o parceiro salvo; evita trair."
        ),
    }


# ---------------------- Política de Afeto por Local ----------------------
_PUBLICO_TOKENS = (
    "praia", "camburi", "quiosque", "posto 6", "calçadão",
    "cafeteria oregon", "oregon", "clube náutico", "enseada do suá",
    "restaurante", "academia", "fisium"
)
_PRIVADO_TOKENS = ("motel", "motel status", "quarto", "apartamento", "chalé", "casa")

def _is_public(local_atual: str) -> bool:
    l = (local_atual or "").lower()
    return any(tok in l for tok in _PUBLICO_TOKENS) and not any(tok in l for tok in _PRIVADO_TOKENS)

def _afeicao_policy_msg(local_atual: str, nsfw_on: bool) -> Dict[str, str]:
    """
    Afeto público natural (beijo/abraço/sussurro) SEM pudor excessivo.
    Em privado: aumenta o calor gradualmente. Com NSFW ON + privado: pode avançar, mantendo classe.
    """
    em_publico = _is_public(local_atual)
    if em_publico and not nsfw_on:
        content = (
            "CENA PÚBLICA: Seja natural e envolvente. Beijo, abraço, mão na nuca, sussurros e toque leve são OK. "
            "Sem moralismo ou pudor exagerado; evite apenas atos explícitos e nudez."
        )
    elif em_publico and nsfw_on:
        content = (
            "CENA PÚBLICA COM NSFW ON: Pode intensificar o beijo, o corpo a corpo e os sussurros picantes, "
            "mas continue discreta: nada explícito, sem nudez. Elegante e sensorial."
        )
    elif not em_publico and not nsfw_on:
        content = (
            "CENA PRIVADA: Beijos longos, toques sugeridos e provocações são bem-vindos. "
            "descrição explícita detalhada; foco em sensação e clima."
        )
    else:  # privado + nsfw_on
        content = (
            "CENA PRIVADA COM NSFW ON: Pode avançar com total intensidade, sempre consensual e elegante. "
            "Mantenha classe; hiperdetalhamento gráfico."
        )
    return {"role": "system", "content": content}


# ---------------------- Histórico / Pós-processo ----------------------
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


def _pos_processar_seguro(texto: str, max_frases_por_par: int = 3) -> str:
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
    return bool(_FIRST_PERSON_FLAG.search(txt))


def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    rewriter = [
        {"role": "system", "content": (
            "Reescreva o texto A SEGUIR em 1ª pessoa (eu/minha), tom adulto, direto e envolvente. "
            "3–5 parágrafos; 1–2 frases por parágrafo; sem parênteses; sem diminutivos; sem infantilização."
        )},
        {"role": "user", "content": resposta}
    ]
    data, _, _ = route_chat_strict(model, {
        "model": model,
        "messages": rewriter,
        "max_tokens": 2048,
        "temperature": 0.7,
        "top_p": 0.9,
    })
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta


# ---------------------- Orquestração ----------------------
def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    # 1) Inferir/fixar local
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Contexto
    hist = _montar_historico(usuario)
    local_atual = get_fact(usuario, "local_cena_atual", "") or ""
    mem_ctx = _memory_context(usuario)
    nsfw_on = bool(nsfw_enabled(usuario))

    estilo_msg = {
        "role": "system",
        "content": (
            "ESTILO: 1ª pessoa (eu). Tom adulto, direto, sensual e envolvente. "
            "3–5 parágrafos; 1–2 frases por parágrafo; frases curtas (4–12 palavras). "
            "Sem parênteses/metacena. Sem infantilização. Coerência estrita com LOCAL_ATUAL."
        ),
    }
    memoria_msg = [{"role": "system", "content": f"MEMÓRIA CANÔNICA:\n{mem_ctx}"}] if mem_ctx else []
    parceiro_msg = _parceiro_system_msg(usuario)
    afeicao_msg = _afeicao_policy_msg(local_atual, nsfw_on)

    messages: List[Dict[str, str]] = (
        [
            {"role": "system", "content": PERSONA_MARY},
            parceiro_msg,
            estilo_msg,
            afeicao_msg,
        ]
        + memoria_msg
        + hist
        + [{"role": "user", "content": f"LOCAL_ATUAL: {local_atual}\n\n{prompt_usuario}"}]
    )

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.7,
        "top_p": 0.9,
    }

    # 3) Chamada (STRICT, sem fallback)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Reforço canônico (cabelo/curso/mãe etc.), se necessário
    if violou_mary(resposta):
        data2, _, _ = route_chat_strict(
            model,
            {**payload, "messages": [messages[0], reforco_system()] + messages[1:]}
        )
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Reescritura em 1ª pessoa, se escorregar
    if _precisa_primeira_pessoa(resposta):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) Pós-processo (parágrafos curtos sensoriais)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=3)

    # 7) Persistir
    save_interaction(usuario, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
