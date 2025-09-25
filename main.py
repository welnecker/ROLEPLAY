# main.py
from typing import Optional, List, Tuple
from datetime import datetime
import streamlit as st

# --- imports principais ---
try:
    from core.service import gerar_resposta
except Exception as e:
    st.error(f"Falha ao importar core.service: {e}")
    raise

# Repositório: fatos, eventos e histórico
try:
    from core.repositories import (
        get_fact, get_history_docs, set_fact,
        get_facts, register_event, delete_fact,
        list_events, delete_event_by_id,
        delete_user_history, delete_last_interaction,
        delete_all_user_data, reset_nsfw,
    )
except Exception:
    # fallbacks leves para não quebrar a UI
    def get_fact(_u: str, _k: str, default=None): return default
    def get_history_docs(_u: str, limit: int = 400): return []
    def set_fact(*_a, **_k): return None
    def get_facts(_u: str): return {}
    def register_event(*_a, **_k): return None
    def delete_fact(*_a, **_k): return None
    def list_events(_u: str, limit: int = 5): return []
    def delete_event_by_id(*_a, **_k): return None
    def delete_user_history(_u: str): return 0
    def delete_last_interaction(_u: str): return False
    def delete_all_user_data(_u: str): return {}
    def reset_nsfw(_u: str): return None

# NSFW gate (opcional)
try:
    from core.nsfw import nsfw_enabled
except Exception:
    def nsfw_enabled(_user: str) -> bool:
        return False

# Inferência de local
try:
    from core.locations import infer_from_prompt as infer_location
except Exception:
    def infer_location(_prompt: str) -> Optional[str]:
        return None

# --- helpers ---
def _rerun():
    # compat: Streamlit >= 1.27 usa st.rerun()
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

def _reload_history(user: str):
    """Recarrega histórico do Mongo para o usuário (ordem cronológica)."""
    st.session_state["history"] = []
    try:
        docs = get_history_docs(user)
        for d in docs:
            u = (d.get("mensagem_usuario") or "").strip()
            a = (d.get("resposta_mary") or "").strip()
            if u:
                st.session_state["history"].append(("user", u))
            if a:
                st.session_state["history"].append(("assistant", a))
    except Exception as e:
        st.sidebar.warning(f"Não foi possível carregar o histórico: {e}")
    st.session_state["history_loaded_for"] = user

# --- página ---
st.set_page_config(page_title="Roleplay | Mary Massariol", layout="centered")
st.title("Roleplay | Mary Massariol")

# --- estado base ---
st.session_state.setdefault("usuario", "welnecker")
st.session_state.setdefault("modelo", "deepseek/deepseek-chat-v3-0324")
st.session_state.setdefault("history", [])               # type: List[Tuple[str, str]]
st.session_state.setdefault("history_loaded_for", None)  # evita recarregar no rerun
st.session_state.setdefault("auto_loc", True)            # inferência automática do local

# campos de Memória (UI)
st.session_state.setdefault("mem_tipo", "Fato")
st.session_state.setdefault("mem_chave", "")
st.session_state.setdefault("mem_valor", "")
st.session_state.setdefault("mem_local", "")

# --- controles de topo ---
st.text_input("👤 Usuário", key="usuario")

# Lista de modelos (sem fallback automático para OpenRouter)
MODEL_OPTIONS = [
    # OpenRouter
    "deepseek/deepseek-chat-v3-0324",
    "anthropic/claude-3.5-haiku",
    "thedrummer/anubis-70b-v1.1",
    "qwen/qwen3-max",
    "nousresearch/hermes-3-llama-3.1-405b",

    # Together (use exatamente estes slugs na sua conta Together)
    "together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
    "together/Qwen/Qwen2.5-72B-Instruct",
    "together/google/gemma-2-27b-it",
]
st.selectbox("🧠 Modelo", MODEL_OPTIONS, key="modelo")

usuario = st.session_state["usuario"]
modelo  = st.session_state["modelo"]

# --- carregar histórico do Mongo por usuário (uma vez por troca de usuário) ---
if st.session_state["history_loaded_for"] != usuario:
    _reload_history(usuario)

# --- sidebar (status) ---
try:
    local_atual = get_fact(usuario, "local_cena_atual", "—")
except Exception:
    local_atual = "—"

nsfw_badge = "✅ Liberado" if nsfw_enabled(usuario) else "🔒 Bloqueado"
provider = "Together" if modelo.startswith("together/") else "OpenRouter"

st.sidebar.markdown(f"**NSFW:** {nsfw_badge}")
st.sidebar.caption(f"Local atual: {local_atual}")
st.sidebar.caption(f"Provedor: **{provider}**")

st.sidebar.markdown("---")
st.session_state["auto_loc"] = st.sidebar.checkbox("📍 Inferir local automaticamente", value=st.session_state["auto_loc"])

# --- sidebar (manutenção) ---
st.sidebar.subheader("🧹 Manutenção")
colA, colB = st.sidebar.columns(2)

if colA.button("🔄 Resetar histórico"):
    try:
        delete_user_history(usuario)
        st.session_state["history"] = []
        st.session_state["history_loaded_for"] = None
        st.sidebar.success("Histórico apagado.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao resetar histórico: {e}")

if colB.button("⏪ Apagar último turno"):
    try:
        ok = delete_last_interaction(usuario)
        if ok:
            _reload_history(usuario)
            st.sidebar.info("Último turno apagado.")
            _rerun()
        else:
            st.sidebar.warning("Não havia interações para apagar.")
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar último turno: {e}")

if st.sidebar.button("🧨 Apagar TUDO (chat + memórias)"):
    try:
        delete_all_user_data(usuario)
        st.session_state["history"] = []
        st.session_state["history_loaded_for"] = None
        st.sidebar.success("Tudo apagado para este usuário.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar tudo: {e}")

if st.sidebar.button("🔒 Forçar NSFW OFF"):
    try:
        reset_nsfw(usuario)
        st.sidebar.success("NSFW desativado para este usuário.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao forçar NSFW OFF: {e}")

# --- sidebar (Memória Canônica) ---
st.sidebar.markdown("---")
st.sidebar.subheader("🧠 Memória Canônica")

# alternador
st.session_state["mem_tipo"] = st.sidebar.radio("Tipo de memória", ["Fato", "Evento"], horizontal=True, key="mem_tipo")

if st.session_state["mem_tipo"] == "Fato":
    st.session_state["mem_chave"] = st.sidebar.text_input(
        "Chave do fato (ex.: parceiro_atual, primeiro_encontro)",
        value=st.session_state["mem_chave"], key="mem_chave"
    )
    st.session_state["mem_valor"] = st.sidebar.text_area(
        "Valor do fato",
        value=st.session_state["mem_valor"], key="mem_valor", height=70
    )
    colf1, colf2 = st.sidebar.columns(2)
    if colf1.button("💾 Salvar fato"):
        chave = (st.session_state["mem_chave"] or "").strip()
        valor = (st.session_state["mem_valor"] or "").strip()
        if chave and valor:
            try:
                set_fact(usuario, chave, valor, {"fonte": "manual", "ts": datetime.utcnow().isoformat()})
                st.sidebar.success(f"Fato salvo: {chave}")
                st.session_state["mem_chave"] = ""
                st.session_state["mem_valor"] = ""
            except Exception as e:
                st.sidebar.error(f"Falha ao salvar fato: {e}")
        else:
            st.sidebar.warning("Preencha chave e valor.")
    if colf2.button("🧽 Limpar campos (fato)"):
        st.session_state["mem_chave"] = ""
        st.session_state["mem_valor"] = ""

else:
    st.session_state["mem_chave"] = st.sidebar.text_input(
        "Tipo do evento (ex.: primeiro_encontro, primeira_vez)",
        value=st.session_state["mem_chave"], key="mem_chave_evt"
    )
    st.session_state["mem_valor"] = st.sidebar.text_area(
        "Descrição do evento (curta, factual)",
        value=st.session_state["mem_valor"], key="mem_valor_evt", height=70
    )
    st.session_state["mem_local"] = st.sidebar.text_input(
        "Local (opcional)",
        value=st.session_state["mem_local"], key="mem_local_evt", placeholder="Ex.: Praia de Camburi"
    )
    cole1, cole2 = st.sidebar.columns(2)
    if cole1.button("💾 Salvar evento"):
        tipo = (st.session_state["mem_chave"] or "").strip()
        desc = (st.session_state["mem_valor"] or "").strip()
        loc  = (st.session_state["mem_local"] or "").strip() or None
        if tipo and desc:
            try:
                register_event(usuario, tipo, desc, loc, {"fonte": "manual"})
                st.sidebar.success(f"Evento salvo: {tipo}")
                st.session_state["mem_chave"] = ""
                st.session_state["mem_valor"] = ""
                st.session_state["mem_local"] = ""
            except Exception as e:
                st.sidebar.error(f"Falha ao salvar evento: {e}")
        else:
            st.sidebar.warning("Preencha tipo e descrição.")
    if cole2.button("🧽 Limpar campos (evento)"):
        st.session_state["mem_chave"] = ""
        st.session_state["mem_valor"] = ""
        st.session_state["mem_local"] = ""

# lista de fatos
st.sidebar.markdown("**Fatos salvos**")
try:
    _facts = get_facts(usuario)
except Exception:
    _facts = {}
if _facts:
    for k, v in _facts.items():
        c1, c2 = st.sidebar.columns([4, 1])
        c1.write(f"- `{k}` → {v}")
        if c2.button("🗑️", key=f"del_fact_{k}"):
            try:
                delete_fact(usuario, k)
                st.sidebar.info(f"Fato apagado: {k}")
                _rerun()
            except Exception as e:
                st.sidebar.error(f"Falha ao apagar fato: {e}")
else:
    st.sidebar.caption("_Nenhum fato salvo._")

# lista de eventos (últimos 5)
st.sidebar.markdown("**Eventos (últimos 5)**")
try:
    _evs = list_events(usuario, limit=5)
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
                delete_event_by_id(_id)
                st.sidebar.info("Evento apagado.")
                _rerun()
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
if prompt := st.chat_input("Envie sua mensagem para Mary"):
    # mostra e guarda a mensagem do usuário
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state["history"].append(("user", prompt))

    # inferir/fixar local automaticamente (se possível)
    if st.session_state["auto_loc"]:
        try:
            loc = infer_location(prompt)
            if loc:
                set_fact(usuario, "local_cena_atual", loc, {"fonte": "ui/auto"})
        except Exception:
            pass

    # gerar resposta (o service faz o roteamento de provedor; NÃO faz fallback automático)
    with st.spinner("Gerando..."):
        try:
            resposta = gerar_resposta(usuario, prompt, model=modelo)
        except Exception as e:
            resposta = f"Erro ao gerar resposta: {e}"

    # mostrar e guardar a resposta
    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
    st.session_state["history"].append(("assistant", resposta))
