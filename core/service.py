from typing import List, Dict
from .persona import PERSONA_MARY, HISTORY_BOOT
from .repositories import save_interaction, get_history_docs, set_fact, get_fact
from .rules import violou_mary, reforco_system
from .locations import infer_from_prompt
from .textproc import strip_metacena, formatar_roleplay_profissional
from .openrouter import chat
from .tokens import toklen

def _montar_historico(usuario: str, limite_tokens: int = 120_000) -> List[Dict[str, str]]:
    docs = get_history_docs(usuario)
    if not docs: return HISTORY_BOOT[:]
    total, out = 0, []
    for d in reversed(docs):
        u = d.get("mensagem_usuario") or ""
        a = d.get("resposta_mary") or ""
        t = toklen(u) + toklen(a)
        if total + t > limite_tokens: break
        out.append({"role": "user", "content": u})
        out.append({"role": "assistant", "content": a})
        total += t
    return list(reversed(out)) if out else HISTORY_BOOT[:]

def gerar_resposta(usuario: str, prompt_usuario: str, model: str) -> str:
    # Inferir e fixar local (se achar)
    loc = infer_from_prompt(prompt_usuario) or ""
    if loc:
        set_fact(usuario, "local_cena_atual", loc, {"fonte": "service"})

    hist = _montar_historico(usuario)
    local_atual = get_fact(usuario, "local_cena_atual", "")
    estilo = {"role": "system", "content":
        ("ESTILO: adulto e direto; parágrafos curtos; desejo com classe; "
         "coerência estrita com o local atual.")}

    messages: List[Dict[str, str]] = (
        [{"role": "system", "content": PERSONA_MARY}, estilo]
        + hist
        + [{"role": "user", "content": f"LOCAL_ATUAL: {local_atual}\n\n{prompt_usuario}"}]
    )

    payload = {"model": model, "messages": messages, "max_tokens": 2048, "temperature": 0.6, "top_p": 0.9}
    data = chat(payload)
    resposta = data["choices"][0]["message"]["content"]

    # pós-processo leve
    if violou_mary(resposta):
        data2 = chat({**payload, "messages": [messages[0], reforco_system()] + messages[1:]})
        resposta = data2["choices"][0]["message"]["content"]

    resposta = strip_metacena(resposta)
    resposta = formatar_roleplay_profissional(resposta, max_frases_por_par=3)
    save_interaction(usuario, prompt_usuario, resposta, model)
    return resposta

