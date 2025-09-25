# core/locations.py
from __future__ import annotations
import re

# canônicos (Mary + Laura)
_CANON_EQUIVALENTES = {
    # Mary
    "clube náutico": {"clube náutico", "nautico", "náutico", "balada", "clube"},
    "cafeteria oregon": {"café oregon", "cafe oregon", "oregon", "cafeteria oregon"},
    "praia de camburi": {"praia de camburi", "camburi", "posto 6", "quiosque posto 6"},
    "motel status": {"motel status", "status"},
    "enseada do suá": {"enseada do suá", "enseada"},
    "restaurante partido alto": {"partido alto", "restaurante partido alto"},

    # Laura
    "boate aurora": {"boate aurora", "boate", "strip club", "casa noturna aurora"},
    "padaria do bairro": {"padaria", "pão na chapa", "pingado", "café expresso", "padoca"},
}

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())

def resolve_canon(nome: str) -> str:
    t = _norm(nome)
    for canon, variantes in _CANON_EQUIVALENTES.items():
        for v in variantes:
            if v in t:
                return canon
    return t

def infer_from_prompt(prompt: str) -> str | None:
    t = (prompt or "").lower()

    # praia
    if re.search(r"\b(praia|areia|ondas?|quiosque|coco|orla|mar|biqu[ií]ni|sunga)\b", t):
        return "praia de camburi"
    # academia (se precisar no futuro)
    if re.search(r"\b(academia|halter|barra|agachamento|esteira|gl[uú]teo)\b", t):
        return "academia fisium body"

    # mary: balada/clube
    if re.search(r"\b(clube\s*náutico|náutico|balada|pista|dj)\b", t):
        return "clube náutico"
    if re.search(r"\b(cafeteria|café\s*oregon|oregon|capuccino)\b", t):
        return "cafeteria oregon"
    if re.search(r"\b(partido\s*alto|restaurante)\b", t):
        return "restaurante partido alto"
    if re.search(r"\b(enseada\s*do\s*su[aá]|enseada)\b", t):
        return "enseada do suá"
    if re.search(r"\b(motel\s*status|motel)\b", t):
        return "motel status"

    # laura: boate/padaria
    if re.search(r"\b(boate\s*aurora|boate|strip\s*club|casa\s*noturna)\b", t):
        return "boate aurora"
    if re.search(r"\b(padaria|padoca|p[aã]o\s+na\s+chapa|pingado|caf[eé]\s*expresso)\b", t):
        return "padaria do bairro"

    return None
