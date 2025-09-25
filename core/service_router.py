# core/service_router.py
from typing import Dict
from .openrouter import chat as openrouter_chat
from .together import chat as together_chat

TOGETHER_PREFIX = "together/"

def route_chat_strict(payload: Dict, model: str) -> Dict:
    """
    - Se o modelo começa com 'together/', dispara a Together (sem fallback).
    - Caso contrário, usa OpenRouter (sem fallback).
    """
    if model.startswith(TOGETHER_PREFIX):
        real_model = model[len(TOGETHER_PREFIX):]  # remove 'together/'
        return together_chat({**payload, "model": real_model})
    return openrouter_chat(payload)

