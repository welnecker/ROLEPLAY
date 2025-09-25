# main.py
from __future__ import annotations
from typing import Optional, List, Tuple
from datetime import datetime
import streamlit as st

# --- imports principais ---
try:
    from core.service import gerar_resposta
except Exception as e:
    st.error(f"Falha ao importar core.service: {e}")
    raise

# Repositório: fatos e histórico
try:
    from core.repositories import (
        get_fact, get_facts, get_history_docs, set_fact,
        delete_user_history, delete_last_interaction, delete_all_user_data,
        reset_nsfw, register_event, list_events, delete_event_by_id, delete_fact
    )
except Exception as e:
    st.error(f"Falha ao importar core.repositories: {e}")
    raise

# NSFW gate (opcional)
try:
    from core.nsfw import nsfw_enabled
except Exception:
    def nsfw_enabled(_user: str) -> bool:
        # fallback: considera virgem=False ou evento 'primeira_vez'
        try:
            v = get_fact(_user, "virgem", True)
            if v is False:
                return True
        except Exception:
            pass
        return False

# Inferência de local
try:
    from core.locations import infer_from_prompt as infer_location
except Exception:
    def infer_location(_prompt: str) -> Optional[str]:
        return None

# Bootstrap por personagem
try:
    from core.bootstrap import ensure_character_context
except Exception:
    def ensure_character_context(_usuario_key: str, _character: str) -> None:
        return None

# --- helpers ---
def _rerun():
    if hasattr(st, "rerun"): st.rerun()
    else: st.experimental_rerun()

def _reload_history(user_key: str):
    st.session_state["history"] = []
    try:
        docs = get_history_docs(user_key)
        for d in docs:
            u = (d.get("mensagem_usuario") or "").strip()
            a = (d.get("resposta_mary") or "").strip()
            if u: st.session_state["history"].append(("user", u))
            if a: st.session_state["history"].append(("assistant", a))
    except Exception as e:
        st.sidebar.warning(f"Não foi possível carregar o histórico: {e}")
    st.session_state["history_loaded_for"] = user_key

# --- página ---
st.set_page_config(page_title="Roleplay | Mary / Laura", layout="centered")
st.title("Roleplay | Mary / Laura")

# --- estado base ---
st.session_state.setdefault("usuario", "welnecker")
st.session_state.setdefault("personagem", "Mary")  # Mary | Laura
st.session_state.setdefault("modelo", "deepseek/deepseek-chat-v3-0324")
st.session_state.setdefault("history", [])               # type: List[Tuple[str, str]]
st.session_state.setdefault("history_loaded_for", None)
st.session_state.setdefault("auto_loc", True)

# --- controles de topo ---
cols = st.columns([2, 2, 2])
with cols[0]:
    st.text_input("👤 Usuário", key="usuario")
with cols[1]:
    st.selectbox("🧍 Personagem", ["Mary", "Laura"], key="personagem")
with cols[2]:
    MODEL_OPTIONS = [
        # OpenRouter
        "deepseek/deepseek-chat-v3-0324",
        "anthropic/claude-3.5-haiku",
        "thedrummer/anubis-70b-v1.1",
        "qwen/qwen3-max",
        "nousresearch/hermes-3-llama-3.1-405b",
        # Together
        "together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "together/Qwen/Qwen2.5-72B-Instruct",
        "together/google/gemma-2-27b-it",
    ]
    st.selectbox("🧠 Modelo", MODEL_OPTIONS, key="modelo")

usuario = st.session_state["usuario"]
personagem = st.session_state["personagem"]
modelo  = st.session_state["modelo"]

# chave composta por usuário + personagem (mantém contextos separados)
usuario_key = f"{usuario}::{personagem}"

# --- bootstrap do contexto canônico por personagem ---
ensure_character_context(usuario_key, personagem)

# --- carregar histórico (uma vez por troca de usuario/personagem) ---
if st.session_state["history_loaded_for"] != usuario_key:
    _reload_history(usuario_key)

# --- sidebar (status) ---
try:
    local_atual = get_fact(usuario_key, "local_cena_atual", "—")
except Exception:
    local_atual = "—"

nsfw_badge = "✅ Liberado" if nsfw_enabled(usuario_key) else "🔒 Bloqueado"
provider = "Together" if modelo.startswith("together/") else "OpenRouter"

st.sidebar.markdown(f"**NSFW:** {nsfw_badge}")
st.sidebar.caption(f"Local atual: {local_atual}")
st.sidebar.caption(f"Provedor: **{provider}**")

st.sidebar.markdown("---")
st.session_state["auto_loc"] = st.sidebar.checkbox("📍 Inferir local automaticamente", value=st.session_state["auto_loc"])

# --- sidebar (NSFW toggle simples) ---
st.sidebar.subheader("🔓 Status íntimo")
virgem_flag = bool(get_fact(usuario_key, "virgem", True))
nsfw_box = st.sidebar.checkbox("Ativar NSFW (virgem=False)", value=(not virgem_flag), help="Marca que a personagem não é virgem, liberando NSFW.")
if st.sidebar.button("💾 Salvar NSFW"):
    try:
        set_fact(usuario_key, "virgem", (not nsfw_box) is False, {"fonte": "ui/nsfw", "ts": datetime.utcnow().isoformat()})
        st.sidebar.success("NSFW atualizado.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao salvar NSFW: {e}")

# --- sidebar (manutenção) ---
st.sidebar.subheader("🧹 Manutenção")
colA, colB = st.sidebar.columns(2)
if colA.button("🔄 Resetar histórico"):
    try:
        delete_user_history(usuario_key)
        st.session_state["history"] = []
        st.session_state["history_loaded_for"] = None
        st.sidebar.success("Histórico apagado.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao resetar histórico: {e}")

if colB.button("⏪ Apagar último turno"):
    try:
        ok = delete_last_interaction(usuario_key)
        if ok:
            _reload_history(usuario_key)
            st.sidebar.info("Último turno apagado.")
            _rerun()
        else:
            st.sidebar.warning("Não havia interações para apagar.")
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar último turno: {e}")

if st.sidebar.button("🧨 Apagar TUDO (chat + memórias)"):
    try:
        delete_all_user_data(usuario_key)
        st.session_state["history"] = []
        st.session_state["history_loaded_for"] = None
        st.sidebar.success("Tudo apagado para este usuário/personagem.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar tudo: {e}")

if st.sidebar.button("🔒 Forçar NSFW OFF"):
    try:
        reset_nsfw(usuario_key)
        st.sidebar.success("NSFW desativado para este usuário/personagem.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao forçar NSFW OFF: {e}")

# --- sidebar (Memória Canônica) ---
st.sidebar.markdown("---")
st.sidebar.subheader("🧠 Memória Canônica")

mem_tipo = st.sidebar.radio("Tipo de memória", ["Fato", "Evento"], horizontal=True, key="mem_tipo")

if mem_tipo == "Fato":
    mem_chave = st.sidebar.text_input("Chave do fato (ex.: parceiro_atual, primeiro_encontro)", key="mem_chave")
    mem_valor = st.sidebar.text_area("Valor do fato", key="mem_valor", height=70)
    colf1, colf2 = st.sidebar.columns(2)
    if colf1.button("💾 Salvar fato"):
        chave = (mem_chave or "").strip()
        valor = (mem_valor or "").strip()
        if chave and valor:
            try:
                set_fact(usuario_key, chave, valor, {"fonte": "manual", "ts": datetime.utcnow().isoformat()})
                st.sidebar.success(f"Fato salvo: {chave}")
                st.session_state["mem_chave"] = ""
                st.session_state["mem_valor"] = ""
                _rerun()
            except Exception as e:
                st.sidebar.error(f"Falha ao salvar fato: {e}")
        else:
            st.sidebar.warning("Preencha chave e valor.")
    if colf2.button("🧽 Limpar campos (fato)"):
        st.session_state["mem_chave"] = ""
        st.session_state["mem_valor"] = ""
        _rerun()
else:
    tipo_evt = st.sidebar.text_input("Tipo do evento (ex.: primeiro_encontro, primeira_vez)", key="mem_chave_evt")
    desc_evt = st.sidebar.text_area("Descrição do evento (curta, factual)", key="mem_valor_evt", height=70)
    loc_evt  = st.sidebar.text_input("Local (opcional)", key="mem_local_evt", placeholder="Ex.: Padaria do Bairro")
    cole1, cole2 = st.sidebar.columns(2)
    if cole1.button("💾 Salvar evento"):
        tipo = (tipo_evt or "").strip()
        desc = (desc_evt or "").strip()
        loc  = (loc_evt or "").strip() or None
        if tipo and desc:
            try:
                register_event(usuario_key, tipo, desc, loc, {"fonte": "manual"})
                st.sidebar.success(f"Evento salvo: {tipo}")
                st.session_state["mem_chave_evt"] = ""
                st.session_state["mem_valor_evt"] = ""
                st.session_state["mem_local_evt"] = ""
                _rerun()
            except Exception as e:
                st.sidebar.error(f"Falha ao salvar evento: {e}")
        else:
            st.sidebar.warning("Preencha tipo e descrição.")
    if cole2.button("🧽 Limpar campos (evento)"):
        st.session_state["mem_chave_evt"] = ""
        st.session_state["mem_valor_evt"] = ""
        st.session_state["mem_local_evt"] = ""
        _rerun()

# lista de fatos
st.sidebar.markdown("**Fatos salvos**")
try:
    _facts = get_facts(usuario_key)
except Exception:
    _facts = {}
if _facts:
    for k, v in _facts.items():
        c1, c2 = st.sidebar.columns([4, 1])
        c1.write(f"- `{k}` → {v}")
        if c2.button("🗑️", key=f"del_fact_{k}"):
            try:
                delete_fact(usuario_key, k)
                st.sidebar.info(f"Fato apagado: {k}")
                _rerun()
            except Exception as e:
                st.sidebar.error(f"Falha ao apagar fato: {e}")
else:
    st.sidebar.caption("_Nenhum fato salvo._")

# lista de eventos (últimos 5)
st.sidebar.markdown("**Eventos (últimos 5)**")
try:
    _evs = list_events(usuario_key, limit=5)
except Exception:
    _evs = []
if _evs:
    for ev in _evs:
        _id = str(ev.get("_id"))
        ts  = ev.get("ts")
        tsf = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)
        c1, c2 = st.sidebar.columns([4, 1])
        c1.write(f"- **{ev.get('tipo','?')}** — {ev.get('descricao','?')} ({ev.get('local','—')}) em {tsf}")
        if c2.button("🗑️", key=f"del_evt_{_id}"):
            try:
                ok = delete_event_by_id(_id)
                if ok:
                    st.sidebar.info("Evento apagado.")
                    _rerun()
                else:
                    st.sidebar.warning("Não foi possível apagar o evento.")
            except Exception as e:
                st.sidebar.error(f"Falha ao apagar evento: {e}")
else:
    st.sidebar.caption("_Nenhum evento salvo._")

# --- render histórico já existente ---
for role, content in st.session_state["history"]:
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    else:
        with st.chat_message("assistant", avatar="💚"):
            st.markdown(content)

# --- input do chat ---
if prompt := st.chat_input(f"Envie sua mensagem para {personagem}"):
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state["history"].append(("user", prompt))

    # inferir/fixar local automaticamente (se possível)
    if st.session_state["auto_loc"]:
        try:
            loc = infer_location(prompt)
            if loc:
                set_fact(usuario_key, "local_cena_atual", loc, {"fonte": "ui/auto"})
        except Exception:
            pass

    # gerar resposta (service respeita o provider do slug e NÂO faz fallback)
    with st.spinner("Gerando..."):
        try:
            resposta = gerar_resposta(usuario_key, prompt, model=modelo, character=personagem)
        except Exception as e:
            resposta = f"Erro ao gerar resposta: {e}"

    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
    st.session_state["history"].append(("assistant", resposta))
