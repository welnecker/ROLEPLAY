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
from .service_router import route_chat_strict
from .nsfw import nsfw_enabled

# -----------------------
# Heurísticas de estilo
# -----------------------

def _make_third_person_flag(name: str) -> re.Pattern:
    safe = re.escape((name or "").strip())
    return re.compile(rf"(^|\n)\s*{safe}\b", re.IGNORECASE)

# amacia tom autoritário/sarcástico
_SOFT_REWRITES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bespera\s+sentado\b", re.IGNORECASE), "me espera com calma"),
    (re.compile(r"\bfica\s+quieta\b", re.IGNORECASE), "chega mais perto de mim"),
    (re.compile(r"\bcal(a|e)-se\b", re.IGNORECASE), "vem aqui e me beija"),
    (re.compile(r"\ba\s+conta\s+é\s+sua\b", re.IGNORECASE), "a gente vê a conta juntos"),
    (re.compile(r"\bnão\s+me\s+faça\b", re.IGNORECASE), "não quero te pressionar"),
]

def _amaciar_tom(txt: str) -> str:
    out = txt
    for pat, repl in _SOFT_REWRITES:
        out = pat.sub(repl, out)
    return out

# -----------------------
# Memória e histórico
# -----------------------

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

# -----------------------
# NSFW: privado/deserto
# -----------------------

_PRIV_TOKENS = {
    "apartamento", "apto", "quarto", "cama", "motel", "chalé", "cabana",
    "carro estacionado", "carro parado", "garagem", "casa vazia", "banheiro",
    "praia deserta", "praia vazia", "trilha deserta"
}

def _nsfw_on(usuario_key: str, local_atual: str, prompt: str) -> bool:
    # se já liberado por evento/fato
    if nsfw_enabled(usuario_key):
        return True
    t = f"{local_atual} {prompt}".lower()
    if any(tok in t for tok in _PRIV_TOKENS):
        return True
    return False

def _style_guide_for(character: str, nsfw: bool) -> str:
    base = (
        "ESTILO: primeira pessoa (eu). Tom adulto, direto e envolvente. "
        "3–5 parágrafos; 1–2 frases por parágrafo; frases curtas (4–12 palavras). "
        "FALA DIRETA obrigatória em todo parágrafo (use travessão ou aspas). "
        "Nada de metacena entre parênteses; nada de *asteriscos* narrativos. "
        "Use verbos sensoriais: tocar, sussurrar, morder, lamber, apertar. "
        "Engaje diretamente com 'você'. Mantenha coerência com LOCAL_ATUAL."
    )
    persona_adj = (
        "Para LAURA: zero sarcasmo e zero autoritarismo; convites e perguntas gentis."
    )
    if nsfw:
        gate = (
            "MODO_NSFW_LIBERADO: conteúdo sexual explícito adulto é permitido, "
            "com consentimento claro e linguagem natural; pode usar 'foder', 'me come', 'gozar', etc. "
            "Evite violência, humilhação, coerção, ilegalidades ou termos degradantes."
        )
    else:
        gate = (
            "MODO_SEGURO: sem sexo explícito; foque em química, flerte, beijo, toque insinuado."
        )
    if (character or "").strip().lower() == "laura":
        return f"{base}\n{persona_adj}\n{gate}"
    return f"{base}\n{gate}"

def _fewshot_for(character: str, nsfw: bool) -> List[Dict[str, str]]:
    name = (character or "Mary").strip().lower()
    if name == "laura":
        if nsfw:
            return [
                {"role": "assistant", "content": "— Fecha a porta, vem cá. Eu te beijo devagar e guio tua mão pra minha cintura."},
                {"role": "assistant", "content": "— Fala menos e me beija mais. Eu te puxo pro sofá e mordo teu lábio."},
            ]
        return [
            {"role": "assistant", "content": "— Cheguei. Bora sentar ali? Eu quero te ouvir com calma."},
            {"role": "assistant", "content": "— Traz um café pra mim? Eu prometo compensar com um sorriso."},
        ]
    # Mary: mantém seu histórico/estilo original; sem fewshots extras.
    return []

# -----------------------
# Reescritas de garantia
# -----------------------

def _count_quotes(text: str) -> int:
    # conta aspas e travessões que iniciam fala
    quotes = text.count('"') + text.count("“") + text.count("”")
    dashes = len(re.findall(r"(?:^|\n)\s*[—-]\s*", text))
    return quotes + dashes

def _precisa_primeira_pessoa(txt: str, character: str) -> bool:
    # se aparece "Mary ..." ou "Laura ..." iniciando frase, é sinal de 3ª pessoa
    flag = _make_third_person_flag(character or "Mary")
    return bool(flag.search(txt))

def _reforcar_dialogo_e_primeira_pessoa(model: str, resposta: str) -> str:
    rewriter = [
        {"role": "system", "content": (
            "Reescreva em 1ª pessoa (eu), foco em FALA DIRETA. "
            "Cada parágrafo deve conter fala com travessão ou aspas. "
            "Sem parênteses/metacena; sem asteriscos. "
            "Se for adulto, mantenha sensual e natural, sem pornografia mecânica."
        )},
        {"role": "user", "content": resposta}
    ]
    data, used_model, provider = route_chat_strict(model, {
        "model": model,
        "messages": rewriter,
        "max_tokens": 1200,
        "temperature": 0.5,
        "top_p": 0.9,
    })
    return (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

# -----------------------
# Pós-processamento
# -----------------------

def _pos_processar_seguro(texto: str, max_frases_por_par: int = 2) -> str:
    if not texto:
        return texto
    s = texto.replace("\\", "\\\\")
    try:
        s = strip_metacena(s)  # remove [LOCAL], (metacena) etc.
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        s = s.replace("\\\\", "\\")
        s = _amaciar_tom(s)
        return s
    except ReError:
        return texto

# -----------------------
# Entrada principal
# -----------------------

def gerar_resposta(usuario: str, prompt_usuario: str, model: str, character: str = "Mary") -> str:
    """
    - Mary usa `usuario` puro (compat com dados antigos).
    - Outras personagens usam `usuario::<personagem>` para isolar histórico/memória.
    - Respostas em 1ª pessoa, com fala direta por parágrafo; NSFW sensorial quando permitido.
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

    nsfw = _nsfw_on(usuario_key, local_atual, prompt_usuario)
    estilo_msg = {"role": "system", "content": _style_guide_for(char, nsfw)}
    few = _fewshot_for(char, nsfw)

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
        "temperature": 0.65,
        "top_p": 0.95,
    }

    # 3) chamada (STRICT, sem fallback escondido)
    data, used_model, provider = route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Reforço canônico apenas para Mary
    if char.lower() == "mary" and violou_mary(resposta):
        data2, _, _ = route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Garantias de estilo: 1ª pessoa + diálogo
    need_i = _precisa_primeira_pessoa(resposta, char)
    need_quotes = (_count_quotes(resposta) < 2)
    if need_i or need_quotes:
        try:
            resposta = _reforcar_dialogo_e_primeira_pessoa(model, resposta)
        except Exception:
            pass

    # 6) Pós-processo (quebra parágrafos + amaciar tom)
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=2)

    # 7) Persistir
    save_interaction(usuario_key, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
