# core/textproc.py
import re
from typing import List

# Split de sentenças seguro (evita dividir em abreviações simples e limpa espaços)
_SENT_SPLIT_RE = re.compile(
    r"""
    (?<!\b[A-Z])         # evita dividir após iniciais soltas (heurística leve)
    (?<=[.!?…])          # pontuação final de frase
    ["')\]]*             # aspas/fechos opcionais logo após o ponto
    \s+                  # espaçamento até a próxima
    """,
    re.VERBOSE | re.UNICODE
)

def strip_think_blocks(text: str) -> str:
    """
    Remove blocos <think>...</think> e tags soltas <think> </think>
    que às vezes aparecem como 'raciocínio interno'.
    """
    if not text:
        return text
    s = re.sub(r"<\s*think\s*>.*?<\s*/\s*think\s*>", "", text, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"</?\s*think\s*>", "", s, flags=re.IGNORECASE)
    return s

def strip_metacena(text: str) -> str:
    """
    Remove metacena do início de linha, ex.: "(sorrio)", "[olho]" etc.
    Mantém o restante do conteúdo.
    """
    if not text:
        return text
    lines: List[str] = []
    for ln in text.splitlines():
        ln2 = re.sub(r"^\s*[\(\[][^\)\]]*[\)\]]\s*", "", ln.strip())
        lines.append(ln2)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)  # compacta múltiplas linhas em branco
    return out.strip()

def _split_sentences(text: str) -> List[str]:
    """Quebra em sentenças e higieniza espaçamentos/pontuação."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return []
    parts = _SENT_SPLIT_RE.split(t)
    cleaned = []
    for s in parts:
        s = re.sub(r"\s+([,.;!?…])", r"\1", s.strip())  # remove espaço antes da pontuação
        if s:
            cleaned.append(s)
    return cleaned

def formatar_roleplay_profissional(texto: str, max_frases_por_par: int = 2) -> str:
    """
    Reorganiza o texto em parágrafos curtos (1–max_frases_por_par frases).
    Não cria conteúdo novo; apenas reagrupa e higieniza espaços.
    """
    if not texto:
        return texto

    # Respeita quebras de parágrafo já existentes, mas refaz em blocos curtos
    raw_paragraphs = [p for p in re.split(r"\n{2,}", texto) if p.strip()]
    sentences: List[str] = []
    for p in raw_paragraphs:
        sentences.extend(_split_sentences(p))

    if not sentences:
        return texto.strip()

    paras: List[str] = []
    buf: List[str] = []
    for s in sentences:
        buf.append(s)
        if len(buf) >= max_frases_por_par:
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))

    out = "\n\n".join(paras)
    out = re.sub(r"[ \t]+$", "", out, flags=re.MULTILINE)  # tira espaços à direita
    return out.strip()
