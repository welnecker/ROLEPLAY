# core/service.py
from typing import List, Dict
from re import error as ReError

from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen

# provedores
from .openrouter import chat as openrouter_chat
try:
    from .together import chat as together_chat
except Exception:
    together_chat = None  # fallback se Together não estiver disponível


def _route_chat(model: str, payload: dict) -> dict:
    """
    Decide o provedor:
      - 'together/<slug>' → Together (remove o prefixo antes de enviar)
      - qualquer outro     → OpenRouter
    """
    if model.startswith("together/"):
        if not together_chat:
            raise RuntimeError("Together não configurado (together_chat indisponível).")
        true_model = model.split("/", 1)[1]
        return together_chat({**payload, "model": true_model})
    return openrouter_chat(payload)


def _montar_historico(usuario: str, limite_tokens: int = 120_000) -> List[Dict[str, str]]:
    """Constrói o histórico user/assistant respeitando o limite de tokens."""
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
    """
    Pipeline de regex com saneamento de barras invertidas para evitar
    erros do tipo 'bad escape \\c'.
    """
    if not texto:
        return texto

    # Sanear antes de aplicar regex
    s = texto.replace("\\", "\\\\")
    try:
        s = strip_metacena(s)
        s = formatar_roleplay_profissional(s, max_frases_por_par=max_frases_por_par)
        return s.replace("\\\\", "\\")  # restaura para exibição
    except ReError:
        # Tentativa extra; se falhar, retorna original
        try:
            s2 = strip_metacena(s)
            s2 = formatar_roleplay_profissional(s2, max_frases_por_par=max_frases_por_par)
            return s2.replace("\\\\", "\\")
        except ReError:
            return texto


def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    """
    Gera a resposta via provedor (OpenRouter/Together), aplica pós-processos
    seguros, formata em parágrafos curtos e persiste a interação.
    """
    # 1) Inferir e fixar local, se detectado
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Histórico + estilo + contexto de local
    hist = _montar_historico(usuario)
    local_atual = get_fact(usuario, "local_cena_atual", "") or ""

    estilo_msg = {
        "role": "system",
        "content": (
            "ESTILO: adulto e direto; parágrafos curtos (até 3 frases); "
            "desejo com classe; manter coerência estrita com o LOCAL_ATUAL."
        ),
    }

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": PERSONA_MARY}, estilo_msg]
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

    # 3) Chamada ao provedor (roteada)
    data = _route_chat(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Retry leve se violar regras duras (cabelo/curso/mãe etc.)
    if violou_mary(resposta):
        payload_retry = {**payload, "messages": [messages[0], reforco_system()] + messages[1:]}
        data2 = _route_chat(model, payload_retry)
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Pós-processamento SEGURO
    resposta = _pos_processar_seguro(resposta, max_frases_por_par=3)

    # 6) Persistir
    save_interaction(usuario, prompt_usuario, resposta, model)

    return resposta
