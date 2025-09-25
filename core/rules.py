import re
from typing import Optional, Dict

RE_CHAIR = re.compile(r".")  # placeholder para evitar import vazio

_RE_PROIBIDO_CABELO = re.compile(r"\b(castanh\w+|lo(ir|ur)\w*|ruiv\w*|vermelh\w*|caramel\w*|mel|dourad\w*|platinad\w*|acinzentad\w*)\b", re.IGNORECASE)
_RE_PROIBIDO_CURSO  = re.compile(r"\b(arquitetur\w*|direito|medicin\w*|letras|psicolog\w*|administraç\w*|econom\w*|sistemas?\b.*inform|\bSI\b)\b", re.IGNORECASE)
_RE_PROIBIDO_FACUL  = re.compile(r"\b(FAU|USP|UNICAMP|UFRJ|PUC|UFSCAR|UFMG|UNESP|UNB|UFPE|UFBA|UFPR|IFES|Est[áa]cio|Anhanguera|FATEC|Mackenzie)\b", re.IGNORECASE)
_RE_MAE_NAO_JOSELINA = re.compile(r"\bm[ãa]e\b(?![^\.]{0,60}\bJoselina\b)", re.IGNORECASE)

def reforco_system() -> Dict[str, str]:
    return {"role": "system", "content": (
        "CORREÇÃO/CONSISTÊNCIA:\n"
        "- Cabelo: 'Meus cabelos são negros e volumosos.'\n"
        "- Curso: 'Eu estudo Design de moda na UFES.'\n"
        "- Mãe: 'O nome da minha mãe é Joselina.'\n"
    )}

def violou_mary(txt: str) -> bool:
    return any([
        _RE_PROIBIDO_CABELO.search(txt),
        _RE_PROIBIDO_CURSO.search(txt),
        _RE_PROIBIDO_FACUL.search(txt),
        _RE_MAE_NAO_JOSELINA.search(txt),
    ])
