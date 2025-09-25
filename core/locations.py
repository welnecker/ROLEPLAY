# core/locations.py
import re
from typing import Optional

_CANON_EQUIVALENTES = {
    "clube náutico": {"clube náutico", "nautico", "náutico", "balada", "clube"},
    "cafeteria oregon": {"café oregon", "cafe oregon", "oregon", "cafeteria oregon"},
    "praia de camburi": {"praia de camburi", "camburi", "posto 6", "quiosque posto 6"},
    "motel status": {"motel status", "status"},
    "enseada do suá": {"enseada do suá", "enseada"},
    "restaurante partido alto": {"partido alto", "restaurante partido alto"},
    "chalé rota do lagarto": {
        "chalé rota do lagarto", "chale rota do lagarto",
        "rota do lagarto", "chalé", "chale", "montanha", "montanhas"
    },
}

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())

def infer_from_prompt(prompt: str) -> Optional[str]:
    t = (prompt or "").lower()

    if re.search(r"\b(praia|areia|onda|biqu[ií]ni|sunga|quiosque|coco|mar|orla|guarda-?sol)\b", t, flags=re.UNICODE):
        return "praia de camburi"

    if re.search(r"\b(academia|fisium|halter(es)?|barra|anilha|agachamento|esteira|gl[uú]teo[s]?)\b", t, flags=re.UNICODE):
        return "academia fisium body"

    if re.search(r"\b(clube\s*náutico|náutico|balada|pista|dj)\b", t, flags=re.UNICODE):
        return "clube náutico"

    if re.search(r"\b(cafeteria|café\s*oregon|cafe\s*oregon|oregon|capuccino)\b", t, flags=re.UNICODE):
        return "cafeteria oregon"

    if re.search(r"\b(partido\s*alto|restaurante)\b", t, flags=re.UNICODE):
        return "restaurante partido alto"

    if re.search(r"\b(enseada\s*do\s*su[aá]|enseada)\b", t, flags=re.UNICODE):
        return "enseada do suá"

    if re.search(r"\b(motel\s*status|motel)\b", t, flags=re.UNICODE):
        return "motel status"

    # ✅ FIX: sem "\c" — use padrões válidos e feche os parênteses
    if re.search(r"\b(chal[eé]\b|rota\s+do\s+lagarto|montanhas?)\b", t, flags=re.UNICODE):
        return "chalé rota do lagarto"

    return None
