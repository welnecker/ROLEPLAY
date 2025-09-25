# core/service_router.py
from typing import Dict, Tuple
from .openrouter import chat as openrouter_chat
from .together import chat as together_chat

TOGETHER_PREFIX = "together/"

def route_chat_strict(model: str, payload: Dict) -> Tuple[Dict, str, str]:
    """
    Roteamento sem fallback.
    - Se o modelo começar com 'together/', envia para a Together
      (remoção do prefixo antes de chamar a API).
    - Caso contrário, envia para o OpenRouter.
    Retorna: (data, used_model, provider)
    """
    if model.startswith(TOGETHER_PREFIX):
        real_model = model[len(TOGETHER_PREFIX):]  # ex.: "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo"
        p = {**payload, "model": real_model}
        data = together_chat(p)  # levanta exceção se falhar (sem fallback)
        return data, real_model, "together"

    # OpenRouter por padrão (sem fallback)
    data = openrouter_chat(payload)
    return data, model, "openrouter"
