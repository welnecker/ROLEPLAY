from .repositories import get_fact, last_event

def nsfw_enabled(usuario: str) -> bool:
    virgem = bool(get_fact(usuario, "virgem", True))
    if not virgem:
        return True
    return bool(last_event(usuario, "primeira_vez"))
