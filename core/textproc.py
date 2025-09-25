import re

def strip_metacena(txt: str) -> str:
    linhas = []
    for ln in txt.splitlines():
        ln2 = re.sub(r"^[\(\[][^\)\]]*[\)\]]\s*", "", ln.strip())
        linhas.append(ln2)
    return "\n".join(linhas)

def formatar_roleplay_profissional(txt: str, max_frases_por_par: int = 3) -> str:
    # Quebra por frases e recompõe parágrafos de até N frases
    frases = re.split(r"(?<=[.!?])\s+", txt.strip())
    out, bloco = [], []
    for f in filter(None, frases):
        bloco.append(f)
        if len(bloco) >= max_frases_por_par:
            out.append(" ".join(bloco))
            bloco = []
    if bloco:
        out.append(" ".join(bloco))
    return "\n\n".join(out)
