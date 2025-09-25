import re

_CANON_EQUIVALENTES = {
    "clube náutico": {"clube náutico", "nautico", "náutico", "balada", "clube"},
    "cafeteria oregon": {"café oregon", "cafe oregon", "oregon", "cafeteria oregon"},
    "praia de camburi": {"praia de camburi", "camburi", "posto 6", "quiosque posto 6"},
    "motel status": {"motel status", "status"},
    "enseada do suá": {"enseada do suá", "enseada"},
    "restaurante partido alto": {"partido alto", "restaurante partido alto"},
    "Chalé Rota do Lagarto": {"montanhas", "Chalé Rota do Lagarto"},
}

def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())

def infer_from_prompt(prompt: str) -> str | None:
    t = (prompt or "").lower()
    if re.search(r"\b(praia|areia|onda|biqu[ií]ni|sunga|quiosque|coco|mar)\b", t): return "praia de camburi"
    if re.search(r"\b(academia|halter|barra|agachamento|esteira|gl[uú]teo)\b", t):   return "academia fisium body"
    if re.search(r"\b(clube\s*náutico|balada|pista|dj)\b", t):                       return "clube náutico"
    if re.search(r"\b(cafeteria|café\s*oregon|oregon|capuccino)\b", t):              return "cafeteria oregon"
    if re.search(r"\b(partido\s*alto|restaurante)\b", t):                            return "restaurante partido alto"
    if re.search(r"\b(enseada\s*do\s*su[aá]|enseada)\b", t):                         return "enseada do suá"
    if re.search(r"\b(motel\s*status|motel)\b", t):                                  return "motel status"
    if re.search(r"\b(chalé\c*chalé|montanhas\b", t):                                  return "chalé Rota do Lagarto"  
    return None
