# main.py
from typing import Optional, List, Tuple
import streamlit as st

# --- imports principais ---
try:
    from core.service import gerar_resposta
except Exception as e:
    st.error(f"Falha ao importar core.service: {e}")
    raise

# Repositório: fatos e histórico
try:
    from core.repositories import get_fact, get_history_docs, set_fact, get_facts, list_events
except Exception:
    # fallbacks leves para não quebrar a UI
    def get_fact(_u: str, _k: str, default=None):
        return default
    def get_history_docs(_u: str, limit: int = 400):
        return []
    def set_fact(*_a, **_k):
        return None
    def get_facts(_u: str):
        return {}
    def list_events(_u: str, limit: int = 5):
        return []

# Utilitários de manutenção (podem não existir)
try:
    from core.repositories import (
        delete_user_history,
        delete_last_interaction,
        delete_all_user_data,
    )
except Exception:
    def delete_user_history(_u: str): ...
    def delete_last_interaction(_u: str): return False
    def delete_all_user_data(_u: str): ...

# NSFW gate (com ativar/desativar)
try:
    from core.nsfw import nsfw_enabled, enable_nsfw, reset_nsfw
except Exception:
    def nsfw_enabled(_user: str) -> bool: return False
    def enable_nsfw(_user: str): ...
    def reset_nsfw(_user: str): ...

# Inferência de local
try:
    from core.locations import infer_from_prompt as infer_location
except Exception:
    def infer_location(_prompt: str) -> Optional[str]:
        return None

# --- helpers ---
def _rerun():
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

nsfw_on = nsfw_enabled(usuario)
nsfw_badge = "✅ Liberado" if nsfw_on else "🔒 Bloqueado"
provider = "Together" if modelo.startswith("together/") else "OpenRouter"

st.sidebar.markdown(f"**NSFW:** {nsfw_badge}")
st.sidebar.caption(f"Local atual: {local_atual}")
st.sidebar.caption(f"Provedor: **{provider}**")

st.sidebar.markdown("---")
st.session_state["auto_loc"] = st.sidebar.checkbox(
    "📍 Inferir local automaticamente",
    value=st.session_state["auto_loc"],
    help=(
        "Se ligado, o app tenta detectar o cenário (ex.: Praia de Camburi, "
        "Academia Fisium Body, Clube Náutico etc.) a partir do seu texto e "
        "salva em `local_cena_atual` para manter a coerência das cenas."
    ),
)

# --- NSFW: ON/OFF direto na UI ---
st.sidebar.subheader("🔓 NSFW")
col_n1, col_n2 = st.sidebar.columns(2)
if col_n1.button("Liberar NSFW"):
    try:
        enable_nsfw(usuario)
        st.sidebar.success("NSFW liberado para este usuário.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao liberar NSFW: {e}")

if col_n2.button("Bloquear NSFW"):
    try:
        reset_nsfw(usuario)
        st.sidebar.info("NSFW bloqueado para este usuário.")
        _rerun()
    except Exception as e:
        st.sidebar.error(f"Falha ao bloquear NSFW: {e}")

# --- Memória Canônica (leitura rápida) ---
st.sidebar.markdown("---")
st.sidebar.subheader("🧠 Memória Canônica")

facts = {}
events = []
try:
    facts = get_facts(usuario) or {}
except Exception:
    facts = {}

try:
    events = list_events(usuario, limit=5) or []
except Exception:
    events = []

# Fatos
if facts:
    st.sidebar.markdown("**Fatos**")
    for k, v in facts.items():
        st.sidebar.write(f"- `{k}` → {v}")
else:
    st.sidebar.caption("_Nenhum fato salvo._")

# Eventos
st.sidebar.markdown("**Eventos (últimos 5)**")
if events:
    for ev in events:
        tipo = ev.get("tipo", "?")
        desc = ev.get("descricao", "?")
        loc = ev.get("local", "—")
        ts  = ev.get("ts")
        when = ts.strftime("%Y-%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts or "sem data")
        st.sidebar.write(f"- **{tipo}** — {desc} ({loc}) em {when}")
else:
    st.sidebar.caption("_Nenhum evento registrado._")

# --- Manutenção ---
st.sidebar.markdown("---")
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

    # gerar resposta
    with st.spinner("Gerando..."):
        try:
            resposta = gerar_resposta(usuario, prompt, model=modelo)
        except Exception as e:
            resposta = f"Erro ao gerar resposta: {e}"

    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
    st.session_state["history"].append(("assistant", resposta))
