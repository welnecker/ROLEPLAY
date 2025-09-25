# core/service_router.py
from typing import Tuple, Dict, Any

# Importa clientes dos provedores
from .openrouter import chat as openrouter_chat

try:
    from .together import chat as together_chat
except Exception as e:
    together_chat = None
    _together_import_error = e

def route_chat_strict(model: str, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    """
    Roteia a chamada sem fallback silencioso:
    - Se começar com 'together/', envia para Together (removendo o prefixo).
    - Caso contrário, envia para OpenRouter.
    Retorna: (data, used_model, provider)
    """
    if model.startswith("together/"):
        if together_chat is None:
            raise RuntimeError(f"Together indisponível: {_together_import_error}")
        used = model[len("together/"):]
        pl = dict(payload)
        pl["model"] = used
        data = together_chat(pl)
        return data, used, "Together"
    # OpenRouter
    data = openrouter_chat(payload)
    return data, model, "OpenRouter"
