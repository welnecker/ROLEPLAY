# core/textproc.py
from __future__ import annotations
import re

# Split de frases seguro (não usa replacement)
_SENT_SPLIT = re.compile(r'(?<=[.!?…])\s+')

def strip_metacena(text: str) -> str:
    """
    Remove marcas de metacena no INÍCIO das linhas, como:
    (sorri) ...  ou  [olha para ele] ...
    Faz isso sem usar re.sub com replacement interpretável.
    """
    if not text:
        return text

    out_lines = []
    for raw in text.splitlines():
        ln = raw.lstrip()

        # Se a linha começa com (...) ou [...]
        if ln.startswith('(') or ln.startswith('['):
            close = ln.find(')') if ln.startswith('(') else ln.find(']')
            if close != -1:
                ln = ln[close + 1 :].lstrip()

        out_lines.append(ln)
    return "\n".join(out_lines)


def formatar_roleplay_profissional(text: str, max_frases_por_par: int = 3) -> str:
    """
    Agrupa em parágrafos curtos (até N frases por parágrafo).
    Não usa replacement com barras (evita 'bad escape \\c').
    """
    t = (text or "").strip()
    if not t:
        return t

    # Normaliza espaços sem usar escapes em replacement
    t = re.sub(r'[ \t]+', ' ', t)

    # Quebra em frases
    frases = _SENT_SPLIT.split(t)

    # Junta em blocos
    saida: list[str] = []
    buffer: list[str] = []
    for f in frases:
        f = f.strip()
        if not f:
            continue
        buffer.append(f)
        if len(buffer) >= max_frases_por_par:
            saida.append(' '.join(buffer))
            buffer = []
    if buffer:
        saida.append(' '.join(buffer))

    return '\n\n'.join(saida)
