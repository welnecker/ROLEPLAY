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
    from core.repositories import get_fact, get_history_docs, set_fact
except Exception:
    # fallbacks leves para não quebrar a UI
    def get_fact(_u: str, _k: str, default=None):
        return default
    def get_history_docs(_u: str, limit: int = 400):
        return []
    def set_fact(*_a, **_k):
        return None

# NSFW gate (opcional)
try:
    from core.nsfw import nsfw_enabled
except Exception:
    def nsfw_enabled(_user: str) -> bool:
        return False

# Inferência de local: usamos infer_from_prompt e damos alias para infer_location
try:
    from core.locations import infer_from_prompt as infer_location
except Exception:
    def infer_location(_prompt: str) -> Optional[str]:
        return None

# --- página ---
st.set_page_config(page_title="Roleplay | Mary Massariol", layout="centered")
st.title("Roleplay | Mary Massariol")

# --- estado base ---
st.session_state.setdefault("usuario", "welnecker")
st.session_state.setdefault("modelo", "deepseek/deepseek-chat-v3-0324")
st.session_state.setdefault("history", [])              # type: List[Tuple[str, str]]
st.session_state.setdefault("history_loaded_for", None) # evita recarregar no rerun

# --- controles de topo ---
st.text_input("👤 Usuário", key="usuario")
st.selectbox(
    "🧠 Modelo",
    [
        "deepseek/deepseek-chat-v3-0324",
        "anthropic/claude-3.5-haiku",
        "thedrummer/anubis-70b-v1.1",
        "qwen/qwen3-max",
        "nousresearch/hermes-3-llama-3.1-405b",
    ],
    key="modelo",
)

usuario = st.session_state["usuario"]

# --- carregar histórico do Mongo por usuário (uma vez por troca de usuário) ---
if st.session_state["history_loaded_for"] != usuario:
    st.session_state["history"] = []
    try:
        docs = get_history_docs(usuario)
        # docs já vêm em ordem cronológica (seu repositório faz sort ascendente)
        for d in docs:
            u = (d.get("mensagem_usuario") or "").strip()
            a = (d.get("resposta_mary") or "").strip()
            if u:
                st.session_state["history"].append(("user", u))
            if a:
                st.session_state["history"].append(("assistant", a))
    except Exception as e:
        st.sidebar.warning(f"Não foi possível carregar o histórico: {e}")
    st.session_state["history_loaded_for"] = usuario

# --- sidebar (status) ---
try:
    local_atual = get_fact(usuario, "local_cena_atual", "—")
except Exception:
    local_atual = "—"

nsfw_badge = "✅ Liberado" if nsfw_enabled(usuario) else "🔒 Bloqueado"
st.sidebar.markdown(f"**NSFW:** {nsfw_badge}")
st.sidebar.caption(f"Local atual: {local_atual}")

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
    try:
        loc = infer_location(prompt)
        if loc:
            set_fact(usuario, "local_cena_atual", loc, {"fonte": "ui/auto"})
    except Exception:
        pass

    # gerar resposta (service já persiste no Mongo)
    with st.spinner("Gerando..."):
        try:
            resposta = gerar_resposta(usuario, prompt, model=st.session_state["modelo"])
        except Exception as e:
            resposta = f"Erro ao gerar resposta: {e}"

    # mostrar e guardar a resposta
    with st.chat_message("assistant", avatar="💚"):
        st.markdown(resposta)
    st.session_state["history"].append(("assistant", resposta))
