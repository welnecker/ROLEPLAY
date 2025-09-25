# core/textproc.py
from __future__ import annotations
import re
from typing import List

# --- Remoção de metacena entre parênteses/colchetes no início de linha ---
def strip_metacena(txt: str) -> str:
    if not txt:
        return txt
    out_lines: List[str] = []
    for ln in txt.replace("\r\n", "\n").split("\n"):
        # remove "(...)" ou "[...]" no INÍCIO da linha
        clean = re.sub(r"^[\(\[][^\)\]]*[\)\]]\s*", "", ln.strip())
        out_lines.append(clean)
    return "\n".join(out_lines).strip()


# --- Split de sentenças simples e robusto para PT (sem depender de bibliotecas externas) ---
# 1) Quebra em fim de frase: ., !, ?, … (retém o separador)
_SENT_END = re.compile(r"([\.!?…]+)(\s+|$)")

def _split_sentences(txt: str) -> List[str]:
    """
    Divide texto em sentenças preservando pontuação final.
    Ex.: "Oi. Tudo bem?" -> ["Oi.", "Tudo bem?"]
    """
    txt = (txt or "").strip()
    if not txt:
        return []
    parts: List[str] = []
    start = 0
    for m in _SENT_END.finditer(txt):
        end = m.end(1)  # inclui o(s) pontuador(es)
        sent = txt[start:end].strip()
        if sent:
            parts.append(sent)
        start = m.end(0)
    # resto (se não terminar em pontuação)
    tail = txt[start:].strip()
    if tail:
        parts.append(tail)
    return parts


# --- Empacotamento em parágrafos: 1–2 sentenças por parágrafo (configurável) ---
def formatar_roleplay_profissional(texto: str, max_frases_por_par: int = 2) -> str:
    """
    - Mantém parágrafos existentes se já houver quebras vazias (\\n\\n);
    - Caso contrário, divide por sentenças e reempacota em blocos com até N sentenças;
    - Garante separação por linha em branco entre parágrafos (\\n\\n).
    """
    if not texto:
        return texto

    t = texto.replace("\r\n", "\n")
    # normaliza espaços, SEM apagar quebras já existentes de parágrafo
    t = re.sub(r"[ \t]+", " ", t)

    # Se já tem parágrafos marcados por linhas em branco, respeita-os,
    # mas ainda garante no-máximo N sentenças por parágrafo.
    raw_parts = [p.strip() for p in re.split(r"\n{2,}", t) if p.strip()]
    paragraphs: List[str] = []

    if len(raw_parts) > 1:
        for part in raw_parts:
            sents = _split_sentences(part)
            if not sents:
                continue
            if len(sents) <= max_frases_por_par:
                paragraphs.append(" ".join(sents))
            else:
                for i in range(0, len(sents), max_frases_por_par):
                    chunk = " ".join(sents[i:i + max_frases_por_par]).strip()
                    if chunk:
                        paragraphs.append(chunk)
    else:
        # Não havia parágrafos: criar a partir de sentenças
        sents = _split_sentences(t)
        if not sents:
            return t.strip()
        for i in range(0, len(sents), max_frases_por_par):
            chunk = " ".join(sents[i:i + max_frases_por_par]).strip()
            if chunk:
                paragraphs.append(chunk)

    # Monta com quebra dupla (Markdown = parágrafo)
    out = "\n\n".join(paragraphs).strip()

    # Evita colar parágrafos por acaso:
    out = re.sub(r"\n{3,}", "\n\n", out)

    return out
