# core/bootstrap.py
from datetime import datetime
from .repositories import get_fact, set_fact, register_event, last_event

def ensure_default_context(usuario: str) -> None:
    # parceiro padrão
    if not get_fact(usuario, "parceiro_atual", None):
        set_fact(usuario, "parceiro_atual", "Janio", {"fonte": "bootstrap"})
    # primeiro encontro (se ainda não houver)
    if not last_event(usuario, "primeiro_encontro"):
        register_event(
            usuario, "primeiro_encontro",
            "Mary e Janio se conheceram oficialmente.",
            local="praia de Camburi",
            meta={"origin": "bootstrap"},
        )
        set_fact(usuario, "primeiro_encontro", "Janio - Praia de Camburi", {"fonte": "bootstrap"})
