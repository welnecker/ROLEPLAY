# core/locations.py
from __future__ import annotations
import re

# Dicionário opcional de equivalentes (mantenha o que você já tem)
_CANON_EQUIVALENTES = {
    "clube náutico": {"clube náutico", "nautico", "náutico", "balada", "clube"},
    "cafeteria oregon": {"café oregon", "cafe oregon", "oregon", "cafeteria oregon"},
    "praia de camburi": {"praia de camburi", "camburi", "posto 6", "quiosque posto 6"},
    "motel status": {"motel status", "status"},
    "enseada do suá": {"enseada do suá", "enseada"},
    "restaurante partido alto": {"partido alto", "restaurante partido alto"},
    "chalé rota do lagarto": {"chale rota do lagarto", "chalé rota do lagarto", "rota do lagarto", "montanha", "domingos martins"},
}

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())

def infer_from_prompt(prompt: str) -> str | None:
    t = (prompt or "").lower()
    # praia pública conhecida
    if re.search(r"\b(praia\s*de\s*camburi|camburi|posto\s*6|quiosque\s*posto\s*6)\b", t):
        return "praia de camburi"
    # praia deserta/isolada
    if (re.search(r"\b(praia)\b.*\b(desert[ao]|isolad[ao]|vazi[ao])\b", t) or
        re.search(r"\b(desert[ao]|isolad[ao]|vazi[ao])\b.*\b(praia)\b", t)):
        return "praia deserta"
    # academia (exemplo)
    if re.search(r"\b(academia|halter|barra|agachamento|esteira|gl[uú]teo|fisium)\b", t):
        return "academia fisium body"
    # boate
    if re.search(r"\b(boate|strip|palco|camarim|privado)\b", t):
        return "boate"
    # cafeteria
    if re.search(r"\b(cafeteria|café\s*oregon|oregon|capuccino|espresso)\b", t):
        return "cafeteria oregon"
    # restaurante
    if re.search(r"\b(partido\s*alto|restaurante|gar[cç]om|almo[cç]o|jantar)\b", t):
        return "restaurante partido alto"
    # motel / hotel / apê / casa / chalé (locais privados)
    if re.search(r"\b(motel|su[ií]te|hotel|pousada|chal[eé]|airbnb|cabana)\b", t):
        return "motel"
    if re.search(r"\b(apartament\w+|apto\b|kitnet|loft|minha casa|seu apartamento|em casa)\b", t):
        return "apartamento"
    # chalé rota do lagarto (montanha)
    if re.search(r"\b(chal[eé]|rota\s*do\s*lagarto|domingos\s*martins|montanha)\b", t):
        return "chalé rota do lagarto"
    return None
