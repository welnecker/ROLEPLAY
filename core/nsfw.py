# core/nsfw.py
from .repositories import get_fact, set_fact, last_event, register_event

def nsfw_enabled(user: str) -> bool:
    try:
        virgem = bool(get_fact(user, "virgem", True))
    except Exception:
        virgem = True
    if virgem is False:
        return True
    try:
        return bool(last_event(user, "primeira_vez"))
    except Exception:
        return False

def enable_nsfw(user: str):
    # marca virgem=False e garante o evento canônico
    set_fact(user, "virgem", False, {"fonte": "sidebar"})
    if not last_event(user, "primeira_vez"):
        register_event(
            user,
            "primeira_vez",
            "Mary e Janio tiveram sua primeira vez.",
            "motel status",
            meta={"origin": "sidebar"},
        )

def reset_nsfw(user: str):
    # volta a bloquear
    set_fact(user, "virgem", True, {"fonte": "sidebar", "manual_reset": True})
