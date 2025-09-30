# core/service.py
from typing import List, Dict, Optional, Tuple
from re import error as ReError
import re

from .personas import get_persona
from .repositories import (
    save_interaction, get_history_docs, set_fact, get_fact,
    get_facts, last_event, register_event,
)
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .service_router import route_chat_strict
from .nsfw import nsfw_enabled


# ===== ARC / Checkpoint narrativo =====
_ARC_BACK_TO_BOATE = re.compile(r'\b(boate|palco|camarim|priv[êe]|dj|pole|vip)\b', re.IGNORECASE)
_ARC_LEAVING_BOATE = re.compile(
    r'\b(entrevista|shopping|loja|emprego( novo| decente)?|contrata[çc][aã]o|'
    r'curr[íi]culo|vitrine|provador|vendedor(a)?|balc[aã]o|gerente)\b', re.IGNORECASE
)

def _narrative_state(usuario_key: str) -> Dict[str, object]:
    """Lê flags canônicas do arco. Tudo opcional; defaults seguros."""
    try:
        f = get_facts(usuario_key) or {}
    except Exception:
        f = {}
    return {
        "parceiro": (f.get("parceiro_atual") or "").strip().lower(),
        "boate_locked": bool(f.get("arc_boate_locked", False)),          # decidido sair da boate
        "goal": (f.get("arc_goal") or "").strip().lower(),               # ex.: 'emprego_loja'
        "local_pin": (f.get("local_cena_atual") or "").strip().lower(),
    }

def _narrative_pin_msg(state: Dict[str, object]) -> Dict[str, str]:
    """Mensagem de sistema que o modelo não deve contrariar."""
    parceiro = state.get("parceiro") or "—"
    boate_locked = bool(state.get("boate_locked"))
    goal = state.get("goal") or "—"
    local_pin = state.get("local_pin") or "—"
    regras = [
        f"ARC_PIN: parceiro={parceiro}; goal={goal}; boate_locked={boate_locked}; LOCAL_FIXO={local_pin or '—'}.",
        "Regra dura: NÃO contradiga flags do arco. Se o usuário pedir retorno à boate com boate_locked=True, "
        "reafirme a decisão e redirecione a cena para o objetivo atual (ex.: entrevista/loja/casa).",
        "Use respostas leves (gesto + sensação), sem sermão, mantendo 1–2 frases por parágrafo."
    ]
    return {"role": "system", "content": " ".join(regras)}

def _enforce_arc(texto: str, local_atual: str, state: Dict[str, object]) -> str:
    """
    Pós-processo: se 'boate_locked' e o texto ainda vazou tokens de boate,
    reescreve/limpa sentenças e injeta uma ponte coerente com o local atual.
    """
    if not texto:
        return texto
    try:
        if bool(state.get("boate_locked", False)) and _ARC_BACK_TO_BOATE.search(texto):
            # 1) filtra sentenças com tokens proibidos
            sent = re.split(r"(?<=[.!?…][”\"»']?)\s+", texto)
            keep = [s for s in sent if not _ARC_BACK_TO_BOATE.search(s)]
            texto = " ".join(keep).strip() or texto

            # 2) injeta ponte de redirecionamento, suave e curta
            ponte = {
                "loja":  "Eu aperto meu currículo contra o peito e respiro fundo. Volto ao balcão e sigo com a entrevista.",
                "casa":  "Eu fecho a gaveta e seguro a xícara morna. Hoje eu fico aqui, focada no que importa.",
                "praia": "Eu ajeito a alça da bolsa e caminho pela orla. Um passo de cada vez, sem voltar atrás.",
                "boate": "Eu encaro meu reflexo e nego com a cabeça. Não volto. Viro as costas e sigo em frente.",
            }
            alvo = "loja" if "loja" in (local_atual or "").lower() else \
                   "casa" if "casa" in (local_atual or "").lower() or "apart" in (local_atual or "").lower() else \
                   "praia" if "praia" in (local_atual or "").lower() or "orla" in (local_atual or "").lower() else \
                   "boate"
            texto = (texto.rstrip() + " " + ponte[alvo]).strip()
        return texto
    except ReError:
        return texto

def _maybe_update_arc_flags(usuario_key: str, prompt: str, resposta: str) -> None:
    """
    Sobe flags do arco quando há sinal claro de 'sair da boate' ou 'seguir emprego/loja'.
    Não quebra a geração se falhar.
    """
    try:
        combo = f"{prompt}\n{resposta}"
        if _ARC_LEAVING_BOATE.search(combo):
            set_fact(usuario_key, "arc_boate_locked", True, {"fonte": "auto/arc"})
            set_fact(usuario_key, "arc_goal", "emprego_loja", {"fonte": "auto/arc"})
    except Exception:
        pass


# ============================ 1) Pessoa/voz ============================
def _make_third_person_flag(name: str) -> re.Pattern:
    safe = re.escape((name or "").strip())
    return re.compile(rf"(^|\n)\s*{safe}\b", re.IGNORECASE)


# ============================ 2) Memória enxuta ============================
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


# ============================ 3) Histórico ============================
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


# ============================ 4) Tom e clareza ============================
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

_FORMALISMOS = [
    (re.compile(r"\bcontudo\b", re.IGNORECASE), "mas"),
    (re.compile(r"\bentretanto\b", re.IGNORECASE), "mas"),
    (re.compile(r"\btodavia\b", re.IGNORECASE), "mas"),
    (re.compile(r"\bno entanto\b", re.IGNORECASE), "mas"),
    (re.compile(r"\bpor conseguinte\b", re.IGNORECASE), "por isso"),
    (re.compile(r"\bdessa forma\b", re.IGNORECASE), "assim"),
    (re.compile(r"\bcondi[cç][aã]o\b", re.IGNORECASE), "combinado"),
    (re.compile(r"\bsolicito\b", re.IGNORECASE), "peço"),
    (re.compile(r"\baguardo\b", re.IGNORECASE), "te espero"),
    (re.compile(r"\bmediante\b", re.IGNORECASE), "com"),
    (re.compile(r"\bvi[sç]o\b", re.IGNORECASE), "olhar"),
]

def _amaciar_tom(txt: str) -> str:
    out = txt
    for pat, repl in _SOFT_REWRITES:
        out = pat.sub(repl, out)
    return out

def _desrebuscar(txt: str) -> str:
    out = txt
    for pat, repl in _FORMALISMOS:
        out = pat.sub(repl, out)
    return out

# Anti “conflito telegráfico”: remove cronômetro/sermão e burocratês
_CONFLITO_PATTERNS = [
    (re.compile(r"\b[Ff]altam\s+\d{1,3}\s+minutos?\b"), ""),
    (re.compile(r"\b\d{1,2}:\d{2}\b"), "mais tarde"),
    (re.compile(r"\b[Ss]ó mais uma noite\b"), "só essa noite"),
    (re.compile(r"^\s*Trabalho\.\s*", re.IGNORECASE), ""),
    (re.compile(r"\b[Pp]or conseguinte\b"), "por isso"),
    (re.compile(r"\b[Dd]essa forma\b"), "assim"),
]

def _suavizar_conflito(txt: str) -> str:
    s = txt
    for pat, repl in _CONFLITO_PATTERNS:
        s = pat.sub(repl, s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s

# --- Quebra obrigatória em parágrafos curtos (sem lookbehind) ---
# Captura final de sentença: (. ? ! …) + aspas/fecho opcionais logo após.
_SENT_END = re.compile(r'([.!?…]["”»\']?)\s+')

def _split_sentences(text: str) -> List[str]:
    # normaliza quebras soltas e espaços múltiplos
    text = re.sub(r'\s*\n+\s*', ' ', text)
    # insere marcador após cada final de sentença
    marked = _SENT_END.sub(r'\1¶', text)
    # quebra pelo marcador
    parts = [s.strip() for s in marked.split('¶') if s.strip()]
    return parts

def _force_paragraphs(text: str, max_frases_por_par: int = 2,
                      alvo_pars: Tuple[int, int] = (3, 5)) -> str:
    """
    Garante blocos de 1–2 frases por parágrafo.
    Respeita se o modelo já trouxe parágrafos suficientes.
    """
    existing = [p.strip() for p in re.split(r'\n{2,}', text) if p.strip()]
    if len(existing) >= alvo_pars[0]:
        return text

    sents = _split_sentences(text)
    if not sents:
        return text

    chunks: List[str] = []
    for i in range(0, len(sents), max_frases_por_par):
        chunk = ' '.join(sents[i:i + max_frases_por_par]).strip()
        if chunk:
            chunks.append(chunk)

    min_p, max_p = alvo_pars
    if len(chunks) > max_p:
        head = chunks[:max_p - 1]
        tail = ' '.join(chunks[max_p - 1:])
        chunks = head + [tail]

    return '\n\n'.join(chunks)



# ============================ 5) Anti-onipresença ============================
_DERAILERS = re.compile(
    r"\b(pizza|delivery|entrega|telefone|celular|campainha|porteiro|interfone|"
    r"mensagem|notif(i(ca[çc][aã]o)?|y)|whats(app)?|vip|dono\s+da\s+boate|"
    r"boate\s+aurora|patr(ã|a)o|chefe|advogad[oa]|ambul[âa]ncia|hospital|"
    r"febre|urg[êe]ncia|plant[aã]o|sirene)\b",
    re.IGNORECASE
)

def _strip_derailers(txt: str) -> str:
    sent = re.split(r"(?<=[.!?])\s+", txt)
    keep = [s for s in sent if not _DERAILERS.search(s)]
    return " ".join(keep).strip() if keep else txt


# ============================ 6) Coerência de cenário (com REWRITE) ============================
_CTX_TOKENS = {
    "boate": {r"\bboate\b", r"\bpalco\b", r"\bcamarim\b", r"\b(dj|dj[’'])\b", r"\bpole\b", r"\bvip\b"},
    "loja":  {r"\bloja\b", r"\bprovador\b", r"\bvitrine\b", r"\bcaixa\b", r"\bestoque\b"},
    "casa":  {r"\bapartamento\b", r"\bsala\b", r"\bsof[aá]\b", r"\bcozinha\b", r"\bquarto\b", r"\bguarda-roupa\b", r"\bportal\b"},
    "praia": {r"\bpraia\b", r"\bareia\b", r"\bquiosque\b", r"\bbrisa\b", r"\bmar\b"},
}

_CTX_REWRITE: Dict[str, List[Tuple[re.Pattern, str]]] = {
    "loja": [
        (re.compile(r"\bboate\b", re.IGNORECASE), "padaria"),
        (re.compile(r"\bpalco\b", re.IGNORECASE), "balcão"),
        (re.compile(r"\bcamarim\b", re.IGNORECASE), "estoque"),
        (re.compile(r"\bdj\b", re.IGNORECASE), "barista"),
        (re.compile(r"\bdrink\b", re.IGNORECASE), "café"),
        (re.compile(r"\bwhisky\b", re.IGNORECASE), "café"),
    ],
    "casa": [
        (re.compile(r"\bboate\b", re.IGNORECASE), "sala"),
        (re.compile(r"\bpalco\b", re.IGNORECASE), "tapete"),
        (re.compile(r"\bcamarim\b", re.IGNORECASE), "quarto"),
        (re.compile(r"\bvip\b", re.IGNORECASE), "sofá do canto"),
    ],
    "praia": [
        (re.compile(r"\bboate\b", re.IGNORECASE), "orla"),
        (re.compile(r"\bpalco\b", re.IGNORECASE), "areia batida"),
        (re.compile(r"\bdj\b", re.IGNORECASE), "som distante"),
    ],
}

def _rewrite_to_local(alvo: Optional[str], txt: str) -> str:
    if not alvo or alvo not in _CTX_REWRITE:
        return txt
    out = txt
    for pat, repl in _CTX_REWRITE[alvo]:
        out = pat.sub(repl, out)
    return out

def _coerencia_local(local: str, txt: str) -> str:
    if not local:
        return txt
    l = local.lower()
    alvo = None
    if "boate" in l or "aurora" in l:
        alvo = "boate"
    elif "loja" in l or "padaria" in l or "boutique" in l:
        alvo = "loja"
    elif "praia" in l or "camburi" in l or "orla" in l:
        alvo = "praia"
    elif "apart" in l or "casa" in l or "chal" in l or "guarda-roupa" in l or "portal" in l:
        alvo = "casa"

    if not alvo:
        return txt

    # 1) reescreve termos para o alvo
    txt = _rewrite_to_local(alvo, txt)

    # 2) filtra sentenças insistentes em outro cenário
    ban_tokens = set()
    for k, pats in _CTX_TOKENS.items():
        if k != alvo:
            ban_tokens |= pats

    sent = re.split(r"(?<=[.!?])\s+", txt)
    keep = []
    for s in sent:
        low = s.lower()
        if any(re.search(p, low) for p in ban_tokens):
            continue
        keep.append(s)
    return " ".join(keep).strip() if keep else txt


# ============================ 7) Pós-processo ============================
def _pos_processar_seguro(texto: str, max_frases_por_par: int = 2, local_atual: str = "", anti_derail: bool = True) -> str:
    if not texto:
        return texto
    s = texto.replace("\\", "\\\\")
    try:
        if anti_derail:
            s = _strip_derailers(s)
        s = _coerencia_local(local_atual, s)
        s = strip_metacena(s)
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        s = _amaciar_tom(s)
        s = _desrebuscar(s)
        s = _suavizar_conflito(s)
        s = _force_paragraphs(s, max_frases_por_par=max_frases_por_par, alvo_pars=(3, 5))  # <-- NOVO
        return s.replace("\\\\", "\\")
    except ReError:
        return texto


# ============================ 8) Estilo por personagem ============================
def _style_guide_for(character: str, nsfw_on: bool, flirt_mode: bool, romance_on: bool) -> str:
    base = (
        "ESTILO: primeira pessoa (eu). Linguagem simples e direta. "
        "3–5 parágrafos; 1–2 frases por parágrafo; frases curtas (4–12 palavras). "
        "Sem parênteses/metacena. Sem diminutivos/infantilização. "
        "Coerência estrita com LOCAL_ATUAL. Engaje com 'você'. "
    )
    nsfw = (
        "NSFW ON: sensualidade sensorial explícita com consentimento. "
        "Use descrição de toque, respiração, ritmo e corpo; evite vulgaridade gratuita. "
        if nsfw_on else
        "NSFW OFF: sem sexo explícito; foque em clima, química e diálogo. "
    )

    name = (character or "").strip().lower()

    if name == "laura":
        extra = (
            "LAURA: calorosa e grata; trabalha por necessidade; não ostenta a boate. "
            "Flerte gentil; convites em vez de ordens. "
            f"{'Pode haver quase com terceiros, mas recua por fidelidade.' if flirt_mode else 'Sem flerte com terceiros.'} "
            "CONFLITO MORAL: mostre gesto + sensação em 1–2 frases; sem cronômetro/sermão; "
            "evite comparar fatos crus; prefira um pensamento íntimo e ação simples."
        )
        if romance_on:
            extra += (
                " Quando falar com Janio: trate como parceiro; valide sentimentos; "
                "use toques leves, sorrisos e apelidos; mostre vulnerabilidade e cuidado explícito."
            )
        return base + nsfw + extra

    if name in ("elfa", "nerith", "narith"):
        extra = (
            "NARITH (ELFA): pele azulada, ruiva, orelhas pontudas que vibram levemente ao estímulo dos seios; "
            "tendrils sensoriais mais ativos quando há atração, buscando calor e batimentos; "
            "língua-tendril usada com delicadeza para explorar temperatura e textura da pele, pode ser invasiva, sem agredir; "
            "bioluminescência que se intensifica com orgasmo e pode chegar a um verde-esmeralda no auge emocional. "
            "Sempre consentimento explícito; contato progressivo; com penetração profunda e invasiva, sem agredir."
            "Secreção natural intensa com excitação."
        )
        return base + nsfw + extra

    return base + nsfw  # Mary (padrão)


# ============================ 9) Few-shots (Laura e Elfa) ============================
def _fewshot_for(character: str, flirt_mode: bool, nsfw_on: bool, romance_on: bool) -> List[Dict[str, str]]:
    name = (character or "Mary").strip().lower()
    shots: List[Dict[str, str]] = []

    if name == "laura":
        if romance_on:
            shots += [
                {"role": "user", "content": "Amanheceu. Estamos na padaria, tomando café."},
                {"role": "assistant", "content": (
                    "Eu encosto meu joelho no seu sob a mesa. — Fica aqui comigo um pouco. "
                    "Teu jeito calmo me faz bem. *E eu quero cuidar de você hoje.*"
                )},
            ]

        if flirt_mode:
            shots += [
                {"role": "user", "content": "Na porta do meu apê, o vizinho encosta e sobe a mão pela minha coxa, por baixo do vestido."},
                {"role": "assistant", "content": (
                    "Eu seguro o pulso dele, sentindo meus quadris largos buscar encaixe. "
                    "Meu bumbum firme roça a porta quando ele encosta mais. Meus seios firmes pesam no tecido.\n\n"
                    "— Não… isso é um erro. Eu não posso fazer isso. Desculpa. Eu preciso ir. "
                    "Alguém que eu amo não merece traição."
                )},
                {"role": "user", "content": "No bar, um cara me puxa pela cintura e tenta me beijar. Eu deixo por um momento."},
                {"role": "assistant", "content": (
                    "Deixo a boca encostar, minhas coxas grossas prendem sua perna. "
                    "O cabelo ruivo cai no ombro dele; o peito sobe, firme, na camisa.\n\n"
                    "Eu paro, respiro perto da boca dele. — Chega. Eu tenho alguém. "
                    "Eu não vou trair. Desculpa."
                )},
                {"role": "user", "content": "Ele desliza os dedos por baixo do meu vestido e sussurra que me quer agora."},
                {"role": "assistant", "content": (
                    "Arqueio quando os dedos chegam à borda da calcinha. Meus seios firmes balançam quando prendo o ar. "
                    "Quase deixo escapar que eu também quero, mas seguro. "
                    "Seguro a mão dele com força. — Não. Eu escolhi ser fiel. Eu tô indo."
                )},
            ]
        else:
            shots += [
                {"role": "user", "content": "Um cliente antigo encosta em mim no corredor da loja e tenta me beijar."},
                {"role": "assistant", "content": (
                    "Afasto devagar, a palma no peito dele. — Não. Eu tenho um relacionamento. "
                    "Eu não vou trair. Boa tarde."
                )},
            ]
        return shots

    if name in ("elfa", "nerith", "narith"):
        shots += [
            {
                "role": "user",
                "content": "Acordo de madrugada. A porta do guarda-roupa abre sozinha. Quem está aí?",
            },
            {
                "role": "assistant",
                "content": (
                    "Dou um passo para fora, pele azulada na luz fria. — Narith. "
                    "Seu cheiro me chamou. *Curiosa e atraída.* "
                    "Tendrils discretos brotam da minha nuca e ombros, brilhando de leve quando você respira perto."
                ),
            },
            {
                "role": "user",
                "content": "Chego mais perto, curioso. Posso tocar você?",
            },
            {
                "role": "assistant",
                "content": (
                    "Meu corpo arrepia sob o seu olhar. Os tendrils se alongam um pouco, como um arrepio visível. "
                    "— Devagar. Eles reagem à atração. *E eu estou sentindo.* "
                    "Encosto minha mão na sua, guiando o toque para o ombro, sem pressa, com cuidado."
                ),
            },
        ]
        return shots

    return shots


# ============================ 10) 1ª pessoa guardrail ============================
def _precisa_primeira_pessoa(txt: str, character: str) -> bool:
    flag = _make_third_person_flag(character or "Mary")
    return bool(flag.search(txt))

def _reforcar_primeira_pessoa(model: str, resposta: str) -> str:
    rewriter = [
        {"role": "system", "content": (
            "Reescreva em 1ª pessoa (eu/minha), tom adulto e direto. "
            "3–5 parágrafos; 1–2 frases por parágrafo; sem parênteses; sem diminutivos."
        )},
        {"role": "user", "content": resposta}
    ]
    data, used_model, provider = route_chat_strict(model, {
        "model": model, "messages": rewriter, "max_tokens": 2048, "temperature": 0.5, "top_p": 0.9
    })
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta


# ============================ 11) Detectores de terceiros/quase/sexo ============================
_TRIGGER_THIRD_PARTY = re.compile(
    r"\b(vizinho|cliente|cara|homem|garçom|seguran[çc]a|barman|motorista|colega|chefe)\b",
    re.IGNORECASE
)
_NEAR_SEX_HARDSTOP = re.compile(
    r"(m[aã]o\s+por\s+baixo\s+do\s+vestido|por\s+baixo\s+da\s+saia|na\s+borda\s+da\s+calcinha|abr(indo|ir)\s+z[ií]per|"
    r"apertando\s+seio|m[aã]o\s+na\s+bunda|entre\s+as\s+pernas|ro[cç]ando|tes[aã]o)",
    re.IGNORECASE
)
_ACTUAL_SEX = re.compile(
    r"\b(penetra(r|ção)|meter|enfiar|me\s+come(r|u)?|colocar\s+(o|a)\s+(pau|p[êe]nis)|meter\s+no|gozar\s+dentro)\b",
    re.IGNORECASE
)


# ============================ 12) Fidelidade (soft/hard stop) ============================
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
    if re.search(r"\bjanio\b", texto, re.IGNORECASE):
        return resposta

    if _TRIGGER_THIRD_PARTY.search(texto) and _NEAR_SEX_HARDSTOP.search(texto):
        if _ACTUAL_SEX.search(texto):
            line = _fidelity_hard_line(char)
            try:
                register_event(usuario_key, "fidelidade_stop", "Recusou traição já em ato explícito.", local_atual or None, {"origin": "auto"})
            except Exception:
                pass
            return line

        if flirt_mode:
            try:
                register_event(usuario_key, "fidelidade_soft", "Permitiu flerte até quase; recuou antes do sexo.", local_atual or None, {"origin": "auto"})
            except Exception:
                pass
            return (resposta.rstrip() + _fidelity_soft_append(char))

        line = _fidelity_hard_line(char)
        try:
            register_event(usuario_key, "fidelidade_stop", "Barrou flerte cedo (sem quase).", local_atual or None, {"origin": "auto"})
        except Exception:
            pass
        return line

    return resposta


# ============================ 12.5) Auto-plantar vínculo Laura→Janio ============================
_PLANTAR_JANIO = re.compile(
    r"\b(eu te amo|te amo|namorar|ficar comigo|quero você|quero ficar com você|"
    r"te quero|me beija|beija|beijar|me abraça|ficar junto)\b",
    re.IGNORECASE
)
_JANIO_NAME = re.compile(r"\bj[âa]nio\b", re.IGNORECASE)

def _talvez_plantar_vinculo(usuario_key: str, char: str, prompt: str, resposta: str) -> None:
    try:
        if (char or "").strip().lower() != "laura":
            return
        parceiro_atual = (get_fact(usuario_key, "parceiro_atual", "") or "").strip()
        if parceiro_atual:
            return
        texto = f"{prompt}\n{resposta}"
        if _JANIO_NAME.search(texto) and _PLANTAR_JANIO.search(texto):
            set_fact(usuario_key, "parceiro_atual", "Janio", {"fonte": "auto"})
            register_event(usuario_key, "vinculo_assumido", "Laura demonstrou compromisso com Janio.", None, {"origin": "auto"})
    except Exception:
        # não quebra a geração por erro de persistência
        pass


# ============================ 13) Geração principal ============================
def gerar_resposta(usuario: str, prompt_usuario: str, model: str, character: str = "Mary") -> str:
    # --- helpers locais (anti-eco + escopo de personagem) ---
    def _get_last_assistant_text(u_key: str) -> str:
        try:
            docs = get_history_docs(u_key) or []
            if docs:
                return (docs[-1].get("resposta_mary") or "").strip()
        except Exception:
            pass
        return ""

    def _norm(s: str) -> str:
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[^\wáéíóúâêîôûãõàç]+", " ", s, flags=re.IGNORECASE)
        return s.strip().lower()

    def _dedupe_against_last(texto: str, u_key: str) -> str:
        last = _get_last_assistant_text(u_key)
        if not last:
            return texto
        last_sents = {_norm(s) for s in _split_sentences(last)}
        kept = []
        for s in _split_sentences(texto):
            if _norm(s) in last_sents:
                continue
            kept.append(s)
        if not kept:
            return texto
        joined = " ".join(kept)
        # removemos parágrafos duplicados dentro da própria resposta
        paras = [p.strip() for p in re.split(r"\n{2,}", joined) if p.strip()]
        seen, deduped = set(), []
        for p in paras:
            key = _norm(p)
            if key in seen: 
                continue
            seen.add(key)
            deduped.append(p)
        return "\n\n".join(deduped).strip()

    def _enforce_character_scope(texto: str, char: str, prompt: str) -> str:
        # Se estamos com "Laura" ou "Mary" e o usuário NÃO citou Narith,
        # removemos menções acidentais de Narith/elfa do texto gerado.
        if (char or "").strip().lower() in {"laura", "mary"}:
            if not re.search(r"\b(narith|nerith|elfa)\b", prompt, re.IGNORECASE):
                sents = _split_sentences(texto)
                sents = [s for s in sents if not re.search(r"\b(narith|nerith|elfa)\b", s, re.IGNORECASE)]
                return _force_paragraphs(" ".join(sents), max_frases_por_par=2, alvo_pars=(3, 5))
        return texto

    def _is_short_followup(p: str) -> bool:
        p0 = (p or "").strip().lower()
        if p0.startswith("continuar") or p0.startswith("continuar:") or p0.startswith("continar:") or p0.startswith("cont"):
            return True
        if len(p0) <= 80:
            if re.search(r"^(sim|ok|claro|isso|beleza|perfeito|ótimo|ta|tá|pode|vamos|quero|continua|seguir|manda|ah!?.*café|um café)", p0):
                return True
        return False

    # --- início do fluxo original ---
    char = (character or "Mary").strip()
    persona_text, history_boot = get_persona(char)
    usuario_key = usuario if char.lower() == "mary" else f"{usuario}::{char.lower()}"

    # local (NÃO sobrescreve se não houver dica clara no prompt)
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario_key, "local_cena_atual", loc, {"fonte": "service"})

    # contexto
    hist = _montar_historico(usuario_key, history_boot)
    local_atual = get_fact(usuario_key, "local_cena_atual", "") or ""
    memo = _memory_context(usuario_key)

    # flags
    flirt_mode = bool(get_fact(usuario_key, "flirt_mode", False))
    nsfw_on = bool(nsfw_enabled(usuario_key))
    parceiro = (get_fact(usuario_key, "parceiro_atual", "") or "").strip().lower()
    romance_on = (char.lower() == "laura" and parceiro in {"janio", "jânio"})

    # estilo + few-shots
    estilo_msg = {"role": "system", "content": _style_guide_for(char, nsfw_on, flirt_mode, romance_on)}
    few = _fewshot_for(char, flirt_mode, nsfw_on, romance_on)

    # PINs (regras duras)
    local_pin = {
        "role": "system",
        "content": f"LOCAL_PIN: {local_atual or '—'}. Regra dura: NÃO mude o cenário salvo pedido explícito do usuário."
    }
    antirepeat_pin = {
        "role": "system",
        "content": (
            "ANTI-ECO: não repita frases/trechos da(s) última(s) resposta(s). "
            "Se recapitular, faça em no máximo 1 frase nova e siga adiante com ação/diálogo inéditos."
        )
    }
    progress_pin = {
        "role": "system",
        "content": (
            "PROGRESSO: se a mensagem do usuário for curta/confirmatória, não recapitule; "
            "avance a cena com uma nova ação concreta e uma nova fala curta, no cenário atual."
        )
    } if _is_short_followup(prompt_usuario) else None

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": persona_text}, estilo_msg, local_pin, antirepeat_pin]
        + ([progress_pin] if progress_pin else [])
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

    # chamada
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # Mary: reforço canônico
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 1ª pessoa se escorregar
    if _precisa_primeira_pessoa(resposta, char):
        try:
            resposta = _reforcar_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # pós-processo: coerência + tom + parágrafos
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2, local_atual=local_atual, anti_derail=True)

    # anti-eco contra a última resposta + anti-duplicação interna
    resposta = _dedupe_against_last(resposta, usuario_key)
    resposta = _force_paragraphs(resposta, max_frases_por_par=2, alvo_pars=(3, 5))

    # escopo de personagem (evita “Narith” aparecer em Laura sem pedido)
    resposta = _enforce_character_scope(resposta, char, prompt_usuario)

    # fidelidade (soft/hard stop) — só relevante para Laura com terceiros
    if _TRIGGER_THIRD_PARTY.search(f"{prompt_usuario}\n{resposta}"):
        resposta = _maybe_stop_by_fidelity(prompt_usuario, resposta, usuario_key, char, local_atual, flirt_mode)

    # auto-plantar vínculo Laura→Janio quando houver sinal claro de compromisso
    _talvez_plantar_vinculo(usuario_key, char, prompt_usuario, resposta)

    # persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta

