# core/service.py
from typing import List, Dict, Optional, Tuple
from re import error as ReError
import re

from .personas import get_persona  # retorna (persona_text, history_boot) p/ Mary/Laura
from .repositories import (
    save_interaction, get_history_docs, set_fact, get_fact,
    get_facts, last_event, register_event,
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .service_router import route_chat_strict  # roteador estrito (Together/OpenRouter)
from .nsfw import nsfw_enabled


# ===== Helpers de coerência de pessoa/voz =====
def _make_third_person_flag(name: str) -> re.Pattern:
    safe = re.escape((name or "").strip())
    return re.compile(rf"(^|\n)\s*{safe}\b", re.IGNORECASE)


# ===== Memória canônica enxuta =====
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


# ===== Histórico =====
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


# ===== Amaciador de tom (tira sarcasmo/autoritarismo) =====
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


# ===== Pós-processo seguro (quebra em parágrafos curtos) =====
def _pos_processar_seguro(texto: str, max_frases_por_par: int = 2) -> str:
    if not texto:
        return texto
    s = texto.replace("\\", "\\\\")  # evita "bad escape \c" em regex
    try:
        s = strip_metacena(s)
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        s = s.replace("\\\\", "\\")
        s = _amaciar_tom(s)
        return s
    except ReError:
        return texto


# ===== Estilo / guia por personagem + flags =====
def _style_guide_for(character: str, nsfw_on: bool, flirt_mode: bool) -> str:
    base = (
        "ESTILO GERAL: primeira pessoa (eu). Tom adulto, direto e envolvente. "
        "3–5 parágrafos; 1–2 frases por parágrafo. Frases curtas (4–12 palavras). "
        "Sem parênteses/metacena. Sem diminutivos/infantilização. "
        "Coerência estrita com LOCAL_ATUAL. Engaje com 'você' e crie ganchos. "
    )
    nsfw = (
        "NSFW PERMITIDO: linguagem explícita liberada (ex.: foder, me comer, gozar), "
        "sempre com consentimento; sem menores; sem violência sexual; sem bestialidade. "
        if nsfw_on else
        "MODO SEGURO: sem cenas sexuais explícitas; foque em clima, química e diálogo. "
    )
    if (character or "").strip().lower() == "laura":
        extra = (
            "LAURA: calorosa, gentil e grata; flerte adulto respeitoso; "
            "preferir convites a comandos. Não ostentar orgulho de ser stripper; "
            "é trabalho por necessidade, com desejo de mudar. "
            f"{'Flerte com terceiros pode chegar ao quase e recuar por fidelidade.' if flirt_mode else 'Sem flerte com terceiros além de cortesia.'}"
        )
        return base + nsfw + extra
    return base + nsfw


# ===== Few-shots específicos (Laura: quase-traição) =====
def _fewshot_for(character: str, flirt_mode: bool, nsfw_on: bool) -> List[Dict[str, str]]:
    """
    Few-shots específicos para Laura:
    - Quando flirt_mode=True: permite flerte com terceiro até quase sexo e recua (sem deus ex machina).
    - Quando flirt_mode=False: barra cedo, com fala de fidelidade.
    """
    name = (character or "Mary").strip().lower()
    if name != "laura":
        return []

    shots: List[Dict[str, str]] = []

    if flirt_mode:
        # FS1 — Porta do apê: escalada sensorial até quase, depois recuo explícito
        shots += [
            {"role": "user", "content": "Na porta do meu apê, o vizinho encosta e sobe a mão pela minha coxa, por baixo do vestido."},
            {"role": "assistant", "content": (
                "Eu seguro o pulso dele, sentindo meus quadris largos buscar instintivamente o encaixe. "
                "Meu bumbum firme roça a porta quando ele encosta mais. Meus seios firmes pesam sob o tecido. "
                "O calor sobe quando ele beija meu pescoço e acha a borda da calcinha.\n\n"
                "— Não… isso é um erro. Eu não posso fazer isso. Desculpa. Eu preciso ir. "
                "Alguém que eu amo não merece traição."
            )},
        ]

        # FS2 — Bar: beijo/pegação, sem penetração; recuo por fidelidade (sem inventar pizza/telefone)
        shots += [
            {"role": "user", "content": "No bar, um cara me puxa pela cintura e tenta me beijar. Eu deixo por um momento."},
            {"role": "assistant", "content": (
                "Deixo a boca encostar na dele, minhas coxas grossas apertando sua perna só o suficiente. "
                "Meu cabelo ruivo cai no ombro dele; sinto o corpo responder e o peito subir, firme, contra sua camisa.\n\n"
                "Eu paro, respiro perto da boca dele. — Chega. Eu tenho alguém. "
                "Eu não vou trair. Desculpa."
            )},
        ]

        # FS3 — Motel (quase): mão por baixo do vestido, linguagem NSFW permitida, recuo antes do sexo
        shots += [
            {"role": "user", "content": "Ele desliza os dedos por baixo do meu vestido e sussurra que me quer agora."},
            {"role": "assistant", "content": (
                "Arqueio quando os dedos chegam na borda da calcinha. Meus seios firmes balançam quando prendo o ar. "
                f"{'— Me fode…' if nsfw_on else '— Eu te quero…'} quase sai, mas seguro. "
                "Seguro a mão dele com força. — Não. Eu escolhi ser fiel. Eu tô indo."
            )},
        ]
    else:
        # FS4 — Flerte OFF: barra cedo, sem quase
        shots += [
            {"role": "user", "content": "Um cliente antigo encosta em mim no corredor da loja e tenta me beijar."},
            {"role": "assistant", "content": (
                "Afasto devagar, a palma no peito dele, firme. — Não. Eu tenho um relacionamento. "
                "Eu não vou trair. Boa tarde."
            )},
        ]

    return shots


# ===== Primeira pessoa guardrail =====
def _precisa_primeira_pessoa(txt: str, character: str) -> bool:
    flag = _make_third_person_flag(character or "Mary")
    return bool(flag.search(txt))


def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    rewriter = [
        {"role": "system", "content": (
            "Reescreva o texto a seguir em 1ª pessoa (eu/minha), tom adulto e direto. "
            "3–5 parágrafos; 1–2 frases por parágrafo; sem parênteses; sem diminutivos."
        )},
        {"role": "user", "content": resposta}
    ]
    data, used_model, provider = route_chat_strict(model, {
        "model": model, "messages": rewriter, "max_tokens": 2048, "temperature": 0.5, "top_p": 0.9
    })
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta


# ===== Filtros de “derailer” (sem pizza/telefone salvador) =====
_DERAILERS = re.compile(r"\b(pizza|telefone|cell|celular|campainha|porteiro|entrega|delivery)\b", re.IGNORECASE)

def _strip_derailers(txt: str) -> str:
    sent = re.split(r"(?<=[.!?])\s+", txt)
    keep = [s for s in sent if not _DERAILERS.search(s)]
    return " ".join(keep).strip() if keep else txt


# ===== Detectores de terceiro/quase/sexo =====
_TRIGGER_THIRD_PARTY = re.compile(r"\b(vizinho|cliente|cara|homem|garçom|seguran[çc]a|barman|motorista|colega|chefe)\b", re.IGNORECASE)
_NEAR_SEX_HARDSTOP = re.compile(
    r"(m[aã]o\s+por\s+baixo\s+do\s+vestido|por\s+baixo\s+da\s+saia|na\s+borda\s+da\s+calcinha|abr(indo|ir)\s+z[ií]per|"
    r"apertando\s+seio|m[aã]o\s+na\s+bunda|entre\s+as\s+pernas|ro[cç]ando|tes[aã]o)", re.IGNORECASE
)
_ACTUAL_SEX = re.compile(
    r"\b(penetra(r|ção)|meter|enfiar|me\s+come(r|u)?|colocar\s+(o|a)\s+(pau|p[êe]nis)|meter\s+no|gozar\s+dentro)\b",
    re.IGNORECASE
)


# ===== Fidelidade (soft/hard stop) =====
def _fidelity_hard_line(character: str) -> str:
    if (character or "").strip().lower() == "laura":
        return ("— Não… isso é um erro. Eu não posso fazer isso.\n"
                "Desculpa. Eu preciso ir. Alguém que eu amo não merece traição.")
    return ("— Eu não vou trair. Desculpa. Eu preciso ir.")


def _fidelity_soft_append(_character: str) -> str:
    return (
        "\nEu seguro sua mão por um instante, minha respiração ainda quente.\n"
        "— Não… isso é um erro. Eu não posso fazer isso. Desculpa.\n"
        "Eu preciso ir. Alguém que eu amo não merece traição."
    )


def _maybe_stop_by_fidelity(
    prompt: str, resposta: str, usuario_key: str, char: str, local_atual: str, flirt_mode: bool
) -> str:
    texto = f"{prompt}\n{resposta}"
    # se o texto cita Janio, assumimos contexto do parceiro presente e não aplicamos “terceiro”
    if re.search(r"\bjanio\b", texto, re.IGNORECASE):
        return resposta

    if _TRIGGER_THIRD_PARTY.search(texto) and _NEAR_SEX_HARDSTOP.search(texto):
        # sexo explícito já ocorreu -> HARD STOP
        if _ACTUAL_SEX.search(texto):
            line = _fidelity_hard_line(char)
            try:
                register_event(usuario_key, "fidelidade_stop", "Recusou traição já em ato explícito.", local_atual or None, {"origin": "auto"})
            except Exception:
                pass
            return line

        # quase-traição permitida -> SOFT STOP no final
        if flirt_mode:
            try:
                register_event(usuario_key, "fidelidade_soft", "Permitiu flerte até quase; recuou antes do sexo.", local_atual or None, {"origin": "auto"})
            except Exception:
                pass
            return (resposta.rstrip() + _fidelity_soft_append(char))

        # flerte desligado -> barra cedo
        line = _fidelity_hard_line(char)
        try:
            register_event(usuario_key, "fidelidade_stop", "Barrou flerte cedo (sem quase).", local_atual or None, {"origin": "auto"})
        except Exception:
            pass
        return line

    return resposta


# ===== Geração principal =====
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

    # 2) Histórico + contexto
    hist = _montar_historico(usuario_key, history_boot)
    local_atual = get_fact(usuario_key, "local_cena_atual", "") or ""
    memo = _memory_context(usuario_key)

    # 3) Flags
    flirt_mode = bool(get_fact(usuario_key, "flirt_mode", False))
    nsfw_on = bool(nsfw_enabled(usuario_key))

    estilo_msg = {"role": "system", "content": _style_guide_for(char, nsfw_on, flirt_mode)}
    few = _fewshot_for(char, flirt_mode, nsfw_on)

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

    # 4) Chamada (STRICT, sem fallback escondido)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 5) Reforço canônico apenas para Mary
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 6) Garantir 1ª pessoa se escorregar pra 3ª
    if _precisa_primeira_pessoa(resposta, char):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 7) Anti-“deus ex machina” quando flerte ligado e há terceiro
    if flirt_mode and _TRIGGER_THIRD_PARTY.search(f"{prompt_usuario}\n{resposta}"):
        resposta = _strip_derailers(resposta)

    # 8) Fidelidade (soft/hard stop)
    resposta = _maybe_stop_by_fidelity(prompt_usuario, resposta, usuario_key, char, local_atual, flirt_mode)

    # 9) Pós-processo (parágrafos curtos + tom suave)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 10) Persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
