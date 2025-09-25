# core/bootstrap.py
from __future__ import annotations
from datetime import datetime
from .repositories import get_fact, set_fact, register_event, last_event

def ensure_character_context(usuario_key: str, character: str) -> None:
    """
    Garante um contexto canônico mínimo por personagem, por usuário lógico (usuario_key).
    """
    ch = (character or "Mary").strip().title()

    if ch == "Mary":
        # parceiro padrão
        if not get_fact(usuario_key, "parceiro_atual", None):
            set_fact(usuario_key, "parceiro_atual", "Janio", {"fonte": "bootstrap"})
        # primeiro encontro
        if not last_event(usuario_key, "primeiro_encontro"):
            register_event(
                usuario_key, "primeiro_encontro",
                "Mary e Janio se conheceram oficialmente.",
                local="praia de Camburi",
                meta={"origin": "bootstrap"},
            )
            set_fact(usuario_key, "primeiro_encontro", "Janio - Praia de Camburi", {"fonte": "bootstrap"})

    elif ch == "Laura":
        # status base da Laura
        if get_fact(usuario_key, "filho_nome", None) is None:
            set_fact(usuario_key, "filho_nome", "Guilherme", {"fonte": "bootstrap"})
            set_fact(usuario_key, "filho_idade", 6, {"fonte": "bootstrap"})
        if get_fact(usuario_key, "profissao", None) is None:
            set_fact(usuario_key, "profissao", "Dançarina (stripper) na Boate Aurora", {"fonte": "bootstrap"})
        if get_fact(usuario_key, "estado_civil", None) is None:
            set_fact(usuario_key, "estado_civil", "mãe solteira", {"fonte": "bootstrap"})
        # NSFW lógico: Laura não é virgem (tem filho)
        if get_fact(usuario_key, "virgem", None) is None:
            set_fact(usuario_key, "virgem", False, {"fonte": "bootstrap"})
        # primeiro encontro do enredo proposto (padaria)
        if not last_event(usuario_key, "primeiro_encontro"):
            register_event(
                usuario_key, "primeiro_encontro",
                "Laura encontrou o usuário na padaria e puxou assunto.",
                local="padaria do bairro",
                meta={"origin": "bootstrap"},
            )
            set_fact(usuario_key, "primeiro_encontro", "Usuário - Padaria do Bairro", {"fonte": "bootstrap"})
