# core/service.py
from typing import List, Dict, Tuple
from re import error as ReError
import re

from .personas import get_persona
from .repositories import (
    save_interaction, get_history_docs, set_fact, get_fact,
    get_facts, last_event,
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .service_router import route_chat_strict  # roteador estrito (Together/OpenRouter)
from .nsfw import nsfw_enabled


# --- regex dinâmica para detectar escorregada para 3ª pessoa (Mary/Laura) ---
def _make_third_person_flag(name: str) -> re.Pattern:
    safe = re.escape((name or "").strip())
    return re.compile(rf"(^|\n)\s*{safe}\b", re.IGNORECASE)


# --- memória canônica enxuta para dar continuidade ---
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


def _montar_historico(
    usuario_key: str,
    history_boot: List[Dict[str, str]],
    limite_tokens: int = 120_000
) -> List[Dict[str, str]]:
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


# --- amaciar tom: remove sarcasmo/autoritarismo e sugestiona convites ---
_SOFT_REWRITES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bespera\s+sentado\b", re.IGNORECASE), "me espera com calma"),
    (re.compile(r"\bespera!\b", re.IGNORECASE), "me espera um pouquinho"),
    (re.compile(r"\btraz\s+um\b", re.IGNORECASE), "se puder, traz um"),
    (re.compile(r"\btraz\s+pra\s+mim\b", re.IGNORECASE), "se puder, traz pra mim"),
    (re.compile(r"\ba\s+conta\s+é\s+sua\b", re.IGNORECASE), "a gente vê a conta juntos"),
    (re.compile(r"\bpaga\s+a\s+conta\b", re.IGNORECASE), "a gente combina a conta"),
    (re.compile(r"\bnão\s+me\s+faça\b", re.IGNORECASE), "não quero te pressionar"),
    (re.compile(r"\bagora!\b", re.IGNORECASE), "agora, se você quiser"),
]


def _amaciar_tom(txt: str) -> str:
    out = txt
    for pat, repl in _SOFT_REWRITES:
        out = pat.sub(repl, out)
    return out


def _pos_processar_seguro(texto: str, max_frases_por_par: int = 2) -> str:
    if not texto:
        return texto
    s = texto.replace("\\", "\\\\")
    try:
        s = strip_metacena(s)
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        s = s.replace("\\\\", "\\")
        s = _amaciar_tom(s)  # <= amacia tom autoritário/sarcástico (não mexe em vocabulário sexual)
        return s
    except ReError:
        return texto


def _style_guide_for(character: str) -> str:
    base = (
        "ESTILO GERAL: 1ª pessoa (eu). Tom adulto, direto e envolvente. "
        "3–5 parágrafos; 1–2 frases por parágrafo. Frases curtas (4–12 palavras). "
        "Sem parênteses/metacena. Sem diminutivos/infantilização. "
        "Coerência estrita com LOCAL_ATUAL. Engaje diretamente com 'você' e crie ganchos."
    )
    if (character or "").strip().lower() == "laura":
        extra = (
            "LAURA: calorosa e gentil; sem sarcasmo; sem tom autoritário. "
            "Prefira convites e perguntas suaves ('vamos', 'que tal'). "
            "Flerte com humor leve e *pensamentos em itálico* quando natural. "
            "Nunca insinuar cobrança/mercadoria; nunca impor tarefas."
        )
        return f"{base}\n{extra}"
    return base


def _fewshot_for(character: str) -> List[Dict[str, str]]:
    name = (character or "Mary").strip().lower()
    if name == "laura":
        return [
            {"role": "assistant", "content": (
                "Apoio o cotovelo no balcão e sorrio curto. — Cheguei mais cedo. "
                "*Bom ter companhia sem pressa.* Que tal a gente pegar um café e sentar ali?"
            )},
            {"role": "assistant", "content": (
                "Olho tua mensagem e respondo encostando na porta. — Tô a caminho. "
                "Se der, pede um suco pra mim? *Hoje só quero conversar e te ouvir.*"
            )},
        ]
    return []


def _precisa_primeira_pessoa(txt: str, character: str) -> bool:
    flag = _make_third_person_flag(character or "Mary")
    return bool(flag.search(txt))


def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
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
    - NSFW sensorial liberado quando nsfw_enabled(usuario_key) == True:
        permite vocabulário explícito (ex.: 'foder', 'me come', 'gozar', 'meter').
        Sempre com consentimento; sem menores; sem violência sexual; sem bestialidade; sem conteúdos ilegais.
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
    few = _fewshot_for(char)

    # 2.1) Gate NSFW -> mensagem explícita de modo
    try:
        nsfw_on = bool(nsfw_enabled(usuario_key))
    except Exception:
        nsfw_on = False

    if nsfw_on:
        mode_text = (
            "MODO_NSFW_LIBERADO: Cenas sexuais explícitas permitidas; linguagem direta e sensorial. "
            "É permitido usar termos como 'foder', 'me come', 'meter', 'gozar', 'gozo', 'porra', 'meter fundo', etc. "
            "Priorize contato físico, sensações, ritmo, respiração, calor, texturas e diálogo quente. "
            "Consentimento explícito. Proibido menores, incesto, violência sexual, bestialidade e atividades ilegais. "
            "Evite gore e hiper-detalhe clínico; foque em prazer mútuo e química adulta."
        )
    else:
        mode_text = (
            "MODO_SEGURO: Sem cenas sexuais explícitas; foque em tensão, clima, diálogo e toques sugeridos."
        )

    mode_msg = {"role": "system", "content": mode_text}

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": persona_text}, estilo_msg, mode_msg]
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

    # 4) Reforço canônico apenas para Mary
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Garantir 1ª pessoa se escorregar pra 3ª
    if _precisa_primeira_pessoa(resposta, char):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) Pós-processo (quebra parágrafos + amaciar tom) — não altera vocabulário sexual permitido
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 7) Persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
