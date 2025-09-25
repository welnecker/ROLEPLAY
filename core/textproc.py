# core/textproc.py
import re
from typing import List

# ---------- utilidades seguras ----------
_WHITESPACE_RE = re.compile(r"\s+")

def _normalize_spaces(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", (text or "").strip())

def strip_metacena(text: str) -> str:
    """
    Remove marcadores de 'metacena' no início da linha, como:
    (sorrio) ou [olho pra você]. Replacement é CONSTANTE -> sem risco de '\c'.
    """
    out_lines: List[str] = []
    for ln in (text or "").splitlines():
        ln2 = re.sub(r"^\s*[\(\[][^\)\]]*[\)\]]\s*", "", ln)  # repl é "", constante
        out_lines.append(ln2)
    return "\n".join(out_lines).strip()

def _to_sentences(text: str) -> List[str]:
    """
    Divide em frases sem usar replacement variável.
    """
    t = _normalize_spaces(text)
    if not t:
        return []
    # Divide depois de . ! ? preservando a pontuação
    parts = re.split(r"(?<=[.!?])\s+", t)
    return [p.strip() for p in parts if p.strip()]

def formatar_roleplay_profissional(text: str, max_frases_por_par: int = 3) -> str:
    """
    Reorganiza em parágrafos curtos (até N frases).
    NENHUM re.sub com replacement vindo do modelo.
    """
    sents = _to_sentences(text)
    if not sents:
        return text or ""

    paras: List[str] = []
    for i in range(0, len(sents), max_frases_por_par):
        chunk = " ".join(sents[i:i + max_frases_por_par])
        paras.append(chunk)

    return "\n\n".join(paras)
