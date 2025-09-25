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

# Utilitários de manutenção (podem não existir)
try:
    from core.repositories import (
        delete_user_history,
        delete_last_interaction,
        delete_all_user_data,
        reset_nsfw,  # opcional
    )
except Exception:
    def delete_user_history(_u: str): ...
    def delete_last_interaction(_u: str): ...
    def delete_all_user_data(_u: str): ...
    def reset_nsfw(_u: str): ...

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
st.session_state.setdefault("history", [])               # type: List[Tuple[str, str]]
st.session_state.setdefault("history_loaded_for", None)  # evita recarregar no rerun

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

        # ✅ Together (exemplos; ajuste para os slugs que você usa na Together)
        "together/meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
        "together/Qwen/Qwen2.5-72B-Instruct",
        "together/google/gemma-2-27b-it",
    ],
    key="modelo",
)


usuario = st.session_state["usuario"]

# --- carregar histórico do Mongo por usuário (uma vez por troca de usuário) ---
if st.session_state["history_loaded_for"] != usuario:
    st.session_state["history"] = []
    try:
        docs = get_history_docs(usuario)
        # docs já vêm em ordem cronológica (asc) no repositório
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

# --- sidebar (manutenção) ---
st.sidebar.markdown("---")
st.sidebar.subheader("🧹 Manutenção")

colA, colB = st.sidebar.columns(2)
if colA.button("🔄 Resetar histórico"):
    try:
        delete_user_history(usuario)
        st.session_state["history"] = []
        st.sidebar.success("Histórico apagado.")
    except Exception as e:
        st.sidebar.error(f"Falha ao resetar histórico: {e}")

if colB.button("⏪ Apagar último turno"):
    try:
        delete_last_interaction(usuario)
        # Remove da UI os últimos 2 registros (user + assistant), se existirem
        if len(st.session_state["history"]) >= 2:
            st.session_state["history"] = st.session_state["history"][:-2]
        else:
            st.session_state["history"] = []
        st.sidebar.info("Último turno apagado.")
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar último turno: {e}")

if st.sidebar.button("🧨 Apagar TUDO (chat + memórias)"):
    try:
        delete_all_user_data(usuario)
        st.session_state["history"] = []
        st.session_state["history_loaded_for"] = None
        st.sidebar.success("Tudo apagado para este usuário.")
    except Exception as e:
        st.sidebar.error(f"Falha ao apagar tudo: {e}")

# opcional: volta a bloquear NSFW
if st.sidebar.button("🔒 Forçar NSFW OFF"):
    try:
        reset_nsfw(usuario)
        st.sidebar.success("NSFW desativado para este usuário.")
    except Exception as e:
        st.sidebar.error(f"Falha ao forçar NSFW OFF: {e}")

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
