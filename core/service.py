# core/service.py
from typing import List, Dict, Tuple
from re import error as ReError
import re

from .personas import get_persona
from .repositories import (
    save_interaction, get_history_docs, set_fact, get_fact,
    get_facts, last_event,  # <- se não existir no seu repos, crie usando o padrão já adotado
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .service_router import route_chat_strict  # roteador estrito (Together/OpenRouter)

# --- regex dinâmica para detectar deslize para 3ª pessoa (Mary/Laura) ---
def _make_third_person_flag(name: str) -> re.Pattern:
    # Ex.: detecta "Mary ..." ou "Laura ..." como início de frase/parágrafo
    safe = re.escape((name or "").strip())
    return re.compile(rf"(^|\n)\s*{safe}\b", re.IGNORECASE)

# --- memória canônica enxuta para dar sentido de continuidade ---
def _memory_context(usuario_key: str) -> str:
    try:
        f = get_facts(usuario_key) or {}
    except Exception:
        f = {}
    blocos: List[str] = []

    if f.get("parceiro_atual"):
        blocos.append(f"RELACIONAMENTO: parceiro_atual={f['parceiro_atual']}")
    if "virgem" in f:
        blocos.append(f"STATUS ÍNTIMO: virgem={bool(f['virgem'])}")
    if f.get("primeiro_encontro"):
        blocos.append(f"PRIMEIRO_ENCONTRO: {f['primeiro_encontro']}")

    try:
        ev = last_event(usuario_key, "primeira_vez")
    except Exception:
        ev = None
    if ev:
        dt = ev.get("ts")
        quando = dt.strftime("%Y-%m-%d %H:%M") if hasattr(dt, "strftime") else str(dt)
        blocos.append(f"EVENTO_CANÔNICO: primeira_vez em {quando} @ {ev.get('local') or '—'}")

    return "\n".join(blocos).strip()

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

def _style_guide_for(character: str) -> str:
    """
    Guia de estilo conciso, focado em engajamento direto e continuidade.
    """
    base = (
        "ESTILO GERAL: 1ª pessoa (eu). Tom adulto, direto e envolvente. "
        "3–5 parágrafos; 1–2 frases por parágrafo. Frases curtas (4–12 palavras). "
        "Sem parênteses/metacena. Sem diminutivos/infantilização. "
        "Mantenha coerência estrita com o LOCAL_ATUAL. "
        "Engaje diretamente com 'você' e crie ganchos no final."
    )
    if (character or "").strip().lower() == "laura":
        # Ajuste de Laura: ação + fala + pensamento em *itálico* quando fizer sentido;
        # cenário cotidiano com sensualidade adulta e humor.
        extra = (
            "LAURA: alternar ação, fala e *pensamentos em itálico* quando natural. "
            "Flertar com humor, tocar de leve, aproximar fisicamente. "
            "Reconhecer o usuário em locais públicos com naturalidade. "
            "Nunca presumir transação. Priorizar conversa, curiosidade e química."
        )
        return f"{base}\n{extra}"
    return base

def _fewshot_for(character: str) -> List[Dict[str, str]]:
    """
    Poucos exemplos curtos para estabilizar o 'tom' da personagem sem engessar.
    """
    name = (character or "Mary").strip().lower()
    if name == "laura":
        return [
            {"role": "assistant", "content": (
                "Encosto no balcão e te encaro com um sorriso breve. "
                "— Coincidência boa te ver aqui. *Curiosa… você vai fingir que não me conhece?*"
            )},
            {"role": "assistant", "content": (
                "Inclino um pouco o corpo. — Relaxa, não tô te cobrando nada. "
                "Só um café e conversa. *Talvez mais tarde… se a química pedir.*"
            )},
        ]
    return []

def _precisa_primeira_pessoa(txt: str, character: str) -> bool:
    flag = _make_third_person_flag(character or "Mary")
    return bool(flag.search(txt))

def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    """
    Usa o mesmo provedor/modelo para reescrever em 1ª pessoa, curto e adulto.
    """
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
    - Mary usa `usuario` puro (compat com dados antigos).
    - Outras personagens usam `usuario::<personagem>` para isolar histórico/memória.
    """
    char = (character or "Mary").strip()
    persona_text, history_boot = get_persona(char)

    usuario_key = usuario if char.lower() == "mary" else f"{usuario}::{char.lower()}"

    # 1) Inferir e fixar local (se detectado)
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario_key, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Histórico + estilo + contexto
    hist = _montar_historico(usuario_key, history_boot)
    local_atual = get_fact(usuario_key, "local_cena_atual", "") or ""
    memo = _memory_context(usuario_key)

    estilo_msg = {"role": "system", "content": _style_guide_for(char)}

    # Few-shot específico (curto) para estabilizar a persona, se houver
    few = _fewshot_for(char)

    # Montagem final
    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": persona_text}, estilo_msg]
        + (few if few else [])
        + hist
        + [{
            "role": "user",
            "content": (
                f"LOCAL_ATUAL: {local_atual}\n"
                f"CONTEXTO_PERSISTENTE:\n{memo}\n\n"
                f"{prompt_usuario}"
            )
        }]
    )

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.6,
        "top_p": 0.9,
    }

    # 3) chamada (STRICT, sem fallback escondido)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Reforço canônico apenas para Mary (regras duras cabelo/curso/mãe etc.)
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Garantir 1ª pessoa se escorregar pra 3ª
    if _precisa_primeira_pessoa(resposta, char):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) Pós-processo (quebra em parágrafos curtos; remove metacena entre parênteses)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 7) Persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
