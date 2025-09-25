# core/service.py
from typing import List, Dict
from re import error as ReError
import re

# >>> pega a persona dinamicamente
from .personas import get_persona

from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .service_router import route_chat_strict  # roteador estrito (Together/OpenRouter)

_FIRST_PERSON_FLAG = re.compile(r"(^|\n)\s*Mary\b", re.IGNORECASE)

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

def _precisa_primeira_pessoa(txt: str) -> bool:
    # heurística leve: evita 3ª pessoa “Mary …”
    return bool(_FIRST_PERSON_FLAG.search(txt))

def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    """Reescreve em 1ª pessoa usando o MESMO provedor/modelo."""
    rewriter = [
        {"role": "system", "content": (
            "Reescreva o texto A SEGUIR em 1ª pessoa (eu/minha), tom adulto, direto e envolvente. "
            "3–5 parágrafos; 1–2 frases por parágrafo; sem parênteses; sem diminutivos; sem infantilização."
        )},
        {"role": "user", "content": resposta}
    ]
    data, used_model, provider = route_chat_strict(model, {
        "model": model,
        "messages": rewriter,
        "max_tokens": 2048,
        "temperature": 0.5,
        "top_p": 0.9,
    })
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

def gerar_resposta(usuario: str, prompt_usuario: str, model: str, character: str = "Mary") -> str:
    """
    - Mary usa `usuario` puro (compatibilidade com dados antigos).
    - Outras personagens usam `usuario::<personagem>` para isolar histórico/memória.
    """
    char = (character or "Mary").strip()
    persona_text, history_boot = get_persona(char)

    usuario_key = usuario if char.lower() == "mary" else f"{usuario}::{char.lower()}"

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

    # 4) reforço canônico (apenas se a personagem for Mary e violar regras duras)
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) garantir 1ª pessoa se cair em 3ª (ocorre às vezes)
    if _precisa_primeira_pessoa(resposta):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) pós-processo (curto, sem metacena)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 7) persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
