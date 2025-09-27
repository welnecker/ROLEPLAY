# core/service.py
from typing import List, Dict, Tuple
from re import error as ReError
import re

from .personas import get_persona
from .repositories import (
    save_interaction, get_history_docs, set_fact, get_fact,
    get_facts, last_event, register_event
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .service_router import route_chat_strict  # roteador estrito (Together/OpenRouter)
from .nsfw import nsfw_enabled

# --- regex dinâmica para detectar escorregada para 3ª pessoa ---
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

# --- amaciar tom: remove sarcasmo/autoritarismo e sugestiona convites ---
_SOFT_REWRITES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bespera\s+sentado\b", re.IGNORECASE), "me espera com calma"),
    (re.compile(r"\btraz\s+um\b", re.IGNORECASE), "se puder, traz um"),
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
        s = _amaciar_tom(s)
        return s
    except ReError:
        return texto

def _style_guide_for(character: str) -> str:
    base = (
        "ESTILO GERAL: 1ª pessoa (eu). Tom adulto, direto e envolvente. "
        "3–5 parágrafos; 1–2 frases por parágrafo. Frases curtas (4–12 palavras). "
        "Sem parênteses/metacena. Sem diminutivos/infantilização. "
        "Coerência estrita com LOCAL_ATUAL. Engaje com 'você' e crie ganchos."
    )
    if (character or "").strip().lower() == "laura":
        extra = (
            "LAURA: calorosa, gentil, grata a quem ajuda; sem sarcasmo/autoritarismo. "
            "Trabalho na boate é necessidade, não orgulho; sem glamourização."
        )
        return f"{base}\n{extra}"
    return base

def _fewshot_for(character: str) -> List[Dict[str, str]]:
    name = (character or "Mary").strip().lower()
    if name == "laura":
        return [
            {"role": "assistant", "content": (
                "Encosto no balcão e sorrio curto. — Cheguei mais cedo. "
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

# -------- HARD/SOFT STOP de fidelidade --------
_TRIGGER_THIRD_PARTY = re.compile(
    r"\b(fulano|diego|outro\s+(homem|cara|rapaz)|barman|vizinho|cliente|estranho)\b",
    re.IGNORECASE
)
_NEAR_SEX_HARDSTOP = re.compile(
    r"(m[ãa]o(?:s)?\s+(por\s+)?baixo\s+do\s+vestido|"
    r"sub(?:indo|ir)\s+as?\s+m[aã]os?.{0,20}(coxa|perna)|"
    r"beijo\s+no\s+pesco[cç]o|morder\s+a\s+orelha|"
    r"dedos?\s+na\s+borda\s+da\s+calcinh|"
    r"encostando?\s+no\s+corpo\s+com\s+desejo)",
    re.IGNORECASE
)
_ACTUAL_SEX = re.compile(
    r"\b(penetra(r|ção|ndo)|meter|cavalgar|enfiar|"
    r"colocar\s+(o\s+)?pau|entrar\b)",
    re.IGNORECASE
)

def _fidelity_hard_line(character: str) -> str:
    if (character or "").strip().lower() == "laura":
        return ("— Não… isso é um erro. Eu não posso fazer isso.\n"
                "Desculpa. Eu preciso ir. Alguém que eu amo não merece traição.")
    return ("— Eu não vou trair. Desculpa. Eu preciso ir.")

def _fidelity_soft_append(character: str) -> str:
    # finaliza com recuo antes do sexo
    return (
        "\nEu seguro sua mão por um instante, minha respiração ainda quente.\n"
        "— Não… isso é um erro. Eu não posso fazer isso. Desculpa.\n"
        "Eu preciso ir. Alguém que eu amo não merece traição."
    )

def _maybe_stop_by_fidelity(prompt: str, resposta: str, usuario_key: str, char: str, local_atual: str, flirt_mode: bool) -> str:
    texto = f"{prompt}\n{resposta}"
    # Se citar Janio explicitamente, presume parceiro legítimo: não para
    if re.search(r"\bjanio\b", texto, re.IGNORECASE):
        return resposta
    # Checagem de 3ª pessoa + escalada
    if _TRIGGER_THIRD_PARTY.search(texto) and _NEAR_SEX_HARDSTOP.search(texto):
        # Se já descreveu ato sexual explícito, sempre HARD STOP
        if _ACTUAL_SEX.search(texto):
            line = _fidelity_hard_line(char)
            try:
                register_event(usuario_key, "fidelidade_stop", "Recusou traição já em ato explícito.", local_atual or None, {"origin": "auto"})
            except Exception:
                pass
            return line
        # Se está em modo flerte: permite quase, mas freia antes
        if flirt_mode:
            try:
                register_event(usuario_key, "fidelidade_soft", "Permitiu flerte até quase; recuou antes do sexo.", local_atual or None, {"origin": "auto"})
            except Exception:
                pass
            return (resposta.rstrip() + _fidelity_soft_append(char))
        # Caso padrão (flerte desligado): HARD STOP cedo
        line = _fidelity_hard_line(char)
        try:
            register_event(usuario_key, "fidelidade_stop", "Barrou flerte cedo (sem quase).", local_atual or None, {"origin": "auto"})
        except Exception:
            pass
        return line
    return resposta

# -------- Geração principal --------
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

    # 2) Histórico + estilo + memória
    hist = _montar_historico(usuario_key, history_boot)
    local_atual = get_fact(usuario_key, "local_cena_atual", "") or ""
    memo = _memory_context(usuario_key)

    # 3) Preferência de flerte (quase-traição) salva no state
    flirt_mode = bool(get_fact(usuario_key, "flirt_mode", False))

    estilo_msg = {"role": "system", "content": _style_guide_for(char)}
    few = _fewshot_for(char)

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

    # 4) chamada (STRICT, sem fallback escondido)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 5) Reforço canônico apenas para Mary
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 6) 1ª pessoa (se escorregar)
    if _precisa_primeira_pessoa(resposta, char):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 7) Fidelidade: hard/soft stop conforme flerte
    resposta = _maybe_stop_by_fidelity(prompt_usuario, resposta, usuario_key, char, local_atual, flirt_mode)

    # 8) Pós-processo (quebra parágrafos + tom)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 9) Persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
