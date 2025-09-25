# core/service.py (apenas partes relevantes)
from typing import List, Dict, Tuple
from re import error as ReError

from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .tokens import toklen
from .openrouter import chat as or_chat

# Together
try:
    from .together import chat as tg_chat, ProviderError
except Exception:
    tg_chat, ProviderError = None, RuntimeError

TOGETHER_ALIASES = {
    "together/meta-llama/llama-405b": "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
    "together/meta-llama/llama-70b":  "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
    "together/qwen/72b":              "Qwen/Qwen2.5-72B-Instruct",
    "together/google/gemma-27b":      "google/gemma-2-27b-it",
}

def _norm_together_model(name: str) -> str:
    if not name:
        return name
    if name.startswith("together/"):
        # mantém alias inteiro para busca (case-insensitive)
        alias = TOGETHER_ALIASES.get(name.lower())
        return alias or name.split("/", 1)[1]  # remove "together/"
    return name

def _route_chat_strict(model: str, payload: dict) -> Tuple[dict, str, str]:
    """
    STRICT MODE:
    - Se modelo começa com "together/", usa somente Together.
    - Se Together falhar, levanta ProviderError (NÃO cai em OpenRouter).
    - Se modelo NÃO é together/, usa OpenRouter.
    Retorna: (data_json, used_model, provider)
    """
    if model.startswith("together/"):
        if tg_chat is None:
            raise ProviderError("Together indisponível (módulo não carregado).")
        real = _norm_together_model(model)

        # candidates: modelo pedido + (eventuais fallbacks dentro da Together)
        fallbacks = {
            "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": [
                "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                "Qwen/Qwen2.5-72B-Instruct",
            ]
        }.get(real, [])
        attempts = [real] + fallbacks

        errs = []
        for m in attempts:
            try:
                data = tg_chat({**payload, "model": m})
                return data, m, "together"
            except ProviderError as e:
                errs.append(f"{m}: {e}")
                continue
        # nada deu certo → propaga erro explícito
        raise ProviderError(" / ".join(errs) or f"Together falhou para {real}")

    # modelo OpenRouter normal
    data = or_chat(payload)
    return data, model, "openrouter"

# ... (demais funções iguais)

def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    # 1) Inferir e fixar local
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    # 2) Histórico e estilo
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

    # 3) Chamada STRICT (pode levantar ProviderError)
    data, used_model, provider = _route_chat_strict(model, payload)
    resposta = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or ""

    # 4) Retry leve com reforço se violar canônico
    if violou_mary(resposta):
        data2, used_model, provider = _route_chat_strict(model, {**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = (data2.get("choices", [{}])[0].get("message", {}) or {}).get("content", "") or resposta

    # 5) Pós-processo seguro
    try:
        resposta = strip_metacena(resposta.replace("\\", "\\\\"))
        resposta = formatar_roleplay_profissional(resposta, max_frases_por_par=3).replace("\\\\", "\\")
    except ReError:
        pass

    # 6) Persistir (modelo efetivo aparece com provedor)
    save_interaction(usuario, prompt_usuario, resposta, f"{provider}:{used_model}")
    return resposta
