# core/service.py
from typing import List, Dict, Tuple, Optional, Set
from re import error as ReError
import re

from .personas import get_persona
from .repositories import (
    save_interaction, get_history_docs, set_fact, get_fact,
    get_facts, last_event,
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional, strip_think_blocks
from .tokens import toklen
from .service_router import route_chat_strict  # roteador estrito (Together/OpenRouter)
from .nsfw import nsfw_enabled


# =========================
# Cena/Local — vocabulário
# =========================

SCENE_TOKENS: Dict[str, Set[str]] = {
    # classes de cenário → regex tokens (sem \c, tudo seguro)
    "praia": {
        r"praia", r"areia", r"mar\b", r"ondas?", r"quiosque", r"guarda-?sol",
        r"orla", r"coco\b", r"sunga", r"biqu[ií]ni", r"posto\s*6"
    },
    "boate": {
        r"\bboate\b", r"balada", r"pista\b", r"dj\b", r"camarote", r"neon", r"seguran[çc]a"
    },
    "cafeteria": {
        r"caf[eé]\b", r"cafeteria", r"capuccino", r"expresso", r"balc[aã]o\b", r"barista"
    },
    "academia": {
        r"academia", r"halter", r"anilha", r"esteira", r"supino", r"agachamento", r"aparelho"
    },
    "restaurante": {
        r"restaurante", r"gar[cç]om", r"mesa\b", r"card[aá]pio", r"reserv[a|e]"
    },
    "motel": {
        r"\bmotel\b", r"su[ií]te\b", r"hidro", r"espelho no teto", r"neon\b"
    },
    "apartamento": {
        r"apartamento", r"sof[aá]", r"quarto", r"cozinha", r"sala\b", r"varanda"
    },
    "chalé": {
        r"chal[eé]\b", r"lenha", r"lareira", r"serra\b", r"montanha[s]?"
    },
}

LOCAL_TO_CLASS: Dict[str, str] = {
    "praia de camburi": "praia",
    "clube náutico": "boate",
    "cafeteria oregon": "cafeteria",
    "academia fisium body": "academia",
    "restaurante partido alto": "restaurante",
    "motel status": "motel",
    "chalé rota do lagarto": "chalé",
    "apartamento": "apartamento",
}


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _scene_class_for_local(local: str) -> Optional[str]:
    if not local:
        return None
    key = _norm(local)
    return LOCAL_TO_CLASS.get(key) or (
        "praia" if "praia" in key else
        "boate" if "clube" in key or "boate" in key else
        "cafeteria" if "cafe" in key or "cafeteria" in key or "oregon" in key else
        "motel" if "motel" in key else
        "academia" if "academia" in key or "fisium" in key else
        "apartamento" if "aparta" in key or "sala" in key or "varanda" in key else
        "chalé" if "chal" in key or "lareira" in key else
        None
    )


def _detect_classes_in_text(txt: str) -> Set[str]:
    t = (txt or "").lower()
    found: Set[str] = set()
    for cls, toks in SCENE_TOKENS.items():
        for pat in toks:
            if re.search(rf"\b{pat}\b", t, flags=re.IGNORECASE):
                found.add(cls)
                break
    return found


def _violou_cena(txt: str, local_atual: str) -> bool:
    """Detecta se a resposta mistura classe de cena diferente do LOCAL_ATUAL."""
    if not local_atual:
        return False
    clazz = _scene_class_for_local(local_atual)
    if not clazz:
        return False
    classes = _detect_classes_in_text(txt)
    if not classes:
        return False
    # se aparecer classe de cena diferente da atual → violou
    return any(c != clazz for c in classes)


def _strip_foreign_scene_sentences(txt: str, local_atual: str) -> str:
    """Remove frases que pertencem a outras classes de cena."""
    if not local_atual:
        return txt
    clazz = _scene_class_for_local(local_atual)
    if not clazz:
        return txt
    ban = {c for c in SCENE_TOKENS.keys() if c != clazz}
    sents = re.split(r"(?<=[.!?])\s+", txt)
    keep: List[str] = []
    for s in sents:
        s_low = s.lower()
        bad = False
        for c in ban:
            for pat in SCENE_TOKENS[c]:
                if re.search(rf"\b{pat}\b", s_low, flags=re.IGNORECASE):
                    bad = True
                    break
            if bad:
                break
        if not bad:
            keep.append(s)
    return " ".join(keep).strip()


# =========================
# Tom e 1ª pessoa
# =========================

def _make_third_person_flag(name: str) -> re.Pattern:
    safe = re.escape((name or "").strip())
    return re.compile(rf"(^|\n)\s*{safe}\b", re.IGNORECASE)

def _precisa_primeira_pessoa(txt: str, character: str) -> bool:
    flag = _make_third_person_flag(character or "Mary")
    return bool(flag.search(txt))

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


# =========================
# Memória canônica
# =========================

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

    # Laura: canon do filho
    if f.get("guilherme_pai"):
        blocos.append(f"GUILHERME_PAI: {f['guilherme_pai']}")
    if "guilherme_idade" in f:
        blocos.append(f"GUILHERME_IDADE: {f['guilherme_idade']}")

    try:
        ev = last_event(usuario_key, "primeira_vez")
    except Exception:
        ev = None
    if ev:
        dt = ev.get("ts")
        quando = dt.strftime("%Y-%m-%d %H:%M") if hasattr(dt, "strftime") else str(dt)
        blocos.append(f"EVENTO_CANÔNICO: primeira_vez em {quando} @ {ev.get('local') or '—'}")

    # participantes “presentes” — por padrão, o parceiro_atual
    participantes = []
    if f.get("parceiro_atual"):
        participantes.append(f.get("parceiro_atual"))
    if participantes:
        blocos.append(f"PERSONAGENS_PRESENTES: você e {', '.join(participantes)}")

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


# =========================
# Pós-processo seguro
# =========================

def _pos_processar_seguro(texto: str, local_atual: str, max_frases_por_par: int = 2) -> str:
    if not texto:
        return texto
    s = texto.replace("\\", "\\\\")
    try:
        s = strip_think_blocks(s)
        s = strip_metacena(s)
        # remove frases que pertencem a outras cenas
        s = _strip_foreign_scene_sentences(s, local_atual)
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        s = s.replace("\\\\", "\\")
        s = _amaciar_tom(s)
        return s
    except ReError:
        return texto


# =========================
# Estilo / retry canônico
# =========================

def _style_guide_for(character: str) -> str:
    base = (
        "CONTINUIDADE DE CENA: NÃO mude de local/cenário sem o usuário indicar explicitamente. "
        "Mantenha LOCAL_ATUAL e PERSONAGENS_PRESENTES. "
        "ESTILO: 1ª pessoa (eu). Adulto, direto e envolvente. "
        "3–5 parágrafos; 1–2 frases por parágrafo; frases curtas (4–12 palavras). "
        "Sem parênteses/metacena. Sem infantilização. Coerência estrita com LOCAL_ATUAL."
    )
    name = (character or "").strip().lower()
    if name == "laura":
        extra = (
            "LAURA: calorosa, gentil, sem sarcasmo/autoritarismo. Prefira convites a comandos. "
            "Não insinuar cobrança; sem mercantilização. Sensualidade com classe."
        )
        return f"{base}\n{extra}"
    return base


def _fewshot_for(character: str) -> List[Dict[str, str]]:
    name = (character or "Mary").strip().lower()
    if name == "laura":
        return [
            {"role": "assistant", "content": (
                "Encosto no balcão e sorrio curto. — Cheguei mais cedo. "
                "Que tal um café e a gente senta ali?"
            )},
            {"role": "assistant", "content": (
                "Leio tua mensagem encostada na porta. — Tô a caminho. "
                "Se der, pede um suco pra mim? Hoje eu só quero te ouvir."
            )},
        ]
    return []


def _retry_fix_scene(model: str, messages: List[Dict[str, str]], local_atual: str, resposta_ruim: str) -> str:
    """Reescreve mantendo o LOCAL_ATUAL e sem teleporte de cenário."""
    sys_fix = {
        "role": "system",
        "content": (
            "CORREÇÃO DE CENA: Reescreva mantendo exatamente o LOCAL_ATUAL. "
            "Não introduza elementos de outras cenas (boate/cafeteria/academia etc.). "
            "Mantenha 1ª pessoa, o mesmo clima e o conteúdo essencial."
        ),
    }
    usr_fix = {
        "role": "user",
        "content": f"LOCAL_ATUAL: {local_atual}\n\nRESPOSTA_ANTERIOR:\n{resposta_ruim}\n\nREESCREVA mantendo o cenário."
    }
    payload = {
        "model": messages and messages[0] and messages[0].get("model") or "",
        "messages": [messages[0] if messages else {"role": "system", "content": ""}, sys_fix, usr_fix],
        "max_tokens": 2048,
        "temperature": 0.5,
        "top_p": 0.9,
    }
    data, used_model, provider = route_chat_strict(model, payload)
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta_ruim


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


# =========================
# Principal
# =========================

def gerar_resposta(usuario: str, prompt_usuario: str, model: str, character: str = "Mary") -> str:
    """
    - Mary usa `usuario` puro (compat com dados antigos).
    - Outras personagens usam `usuario::<personagem>` para isolar histórico/memória.
    """
    char = (character or "Mary").strip()
    persona_text, history_boot = get_persona(char)
    usuario_key = usuario if char.lower() == "mary" else f"{usuario}::{char.lower()}"

    # 1) Inferir e (só então) fixar local — não mude local se já houver um e o usuário não mandou mudar
    inferred = infer_from_prompt(prompt_usuario) or ""
    local_atual = get_fact(usuario_key, "local_cena_atual", "") or ""
    if inferred:
        if not local_atual:
            set_fact(usuario_key, "local_cena_atual", inferred, {"fonte": "service"})
            local_atual = inferred
        else:
            # só troca se o usuário indicar movimento explícito
            move = bool(re.search(r"\b(vamos|ir(?![a-z])|indo|partir|sair|entrar|chegar|mudar|seguir)\b", prompt_usuario, re.IGNORECASE))
            if move:
                set_fact(usuario_key, "local_cena_atual", inferred, {"fonte": "service/move"})
                local_atual = inferred
            # senão, mantém o local atual (evita teleporte)

    # 2) Histórico + estilo + contexto
    hist = _montar_historico(usuario_key, history_boot)
    memo = _memory_context(usuario_key)

    estilo_msg = {"role": "system", "content": _style_guide_for(char)}
    few = _fewshot_for(char)

    nsfw_on = nsfw_enabled(usuario_key)
    gate_msg = {"role": "system", "content": (
        "MODO_NSFW_LIBERADO: sexo explícito adulto, consensual e sensorial; linguagem natural permitida com parcimônia; sem conteúdo ilegal."
        if nsfw_on else
        "MODO_SEGURO: sem cenas sexuais explícitas; foque em clima, química, diálogo e carinho."
    )}

    scene_guard = {"role": "system", "content": (
        "NÃO mude de cenário. Se a última cena estava no LOCAL_ATUAL, permaneça nele. "
        "Se precisar mover de cenário, só faça quando o usuário pedir explicitamente."
    )}

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": persona_text}, estilo_msg, gate_msg, scene_guard]
        + (few if few else [])
        + hist
        + [{
            "role": "user",
            "content": (
                f"LOCAL_ATUAL: {local_atual or '—'}\n"
                f"CONTEXTO_PERSISTENTE:\n{memo}\n\n"
                f"{prompt_usuario}"
            )
        }]
    )

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 2048,
        "temperature": 0.55,
        "top_p": 0.9,
    }

    # 3) chamada (STRICT, sem fallback escondido)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Reforço canônico:
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 4b) Travar cenário — se resposta trouxe tokens de outra cena, reescreve
    if _violou_cena(resposta, local_atual):
        try:
            resposta = _retry_fix_scene(model, messages, local_atual, resposta)
        except Exception:
            # fallback mínimo: limpa frases fora do cenário
            resposta = _strip_foreign_scene_sentences(resposta, local_atual)

    # 5) Garantir 1ª pessoa se escorregar pra 3ª
    if _precisa_primeira_pessoa(resposta, char):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) Pós-processo (quebra parágrafos + amaciar tom + remove <think> + limpa mistura)
    resposta = _pos_processar_seguro(resposta, local_atual, max_frases_por_par=2)

    # 7) Persistir (salva já com a chave/personagem)
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
