# core/nsfw.py
from __future__ import annotations
from typing import Optional
import re
from .repositories import get_fact

# --- padrões SEGUROS (sem \c) ---
_PRIV_LOC_PATTERNS = [
    r"\b(apartament\w+|apto\b|kitnet|loft|casa|sobrado|ph\b|penthous\w*|su[ií]te|hotel|motel|chal[eé]|airbnb|pousada|cabana)\b",
]
_SECLUDED_BEACH_PATTERNS = [
    r"\b(praia)\b.*\b(desert[ao]|isolad[ao]|vazi[ao])\b",
    r"\b(desert[ao]|isolad[ao]|vazi[ao])\b.*\b(praia)\b",
]

def _matches_any(text: str, patterns: list[str]) -> bool:
    t = (text or "").lower()
    # blindagem contra escapes ruins vindos do texto
    t = t.replace("\\", "\\\\")
    return any(re.search(p, t) for p in patterns)

def is_private_location(local_atual: Optional[str]) -> bool:
    if not local_atual:
        return False
    t = (local_atual or "").lower()
    if _matches_any(t, _PRIV_LOC_PATTERNS):
        return True
    if _matches_any(t, _SECLUDED_BEACH_PATTERNS):
        return True
    return False

def nsfw_enabled(usuario: str, local_atual: Optional[str] = None) -> bool:
    """
    Gate NSFW:
      1) Override manual (sidebar): on/off/auto
      2) Se local privado/deserto => ON
      3) Caso contrário, mantém regra anterior (virgem / primeira_vez)
    """
    # 1) override manual
    override = (get_fact(usuario, "nsfw_override", "") or "").lower()
    if override == "on":
        return True
    if override == "off":
        return False

    # 2) local privado/deserto
    if is_private_location(local_atual):
        return True

    # 3) legado (mantém compatibilidade)
    virgem = bool(get_fact(usuario, "virgem", True))
    if not virgem:
        return True
    # Se você grava um flag após primeira_vez, respeite aqui:
    if bool(get_fact(usuario, "primeira_vez_unlock", False)):
        return True

    return False
